import os, json, rispy, threading, time, urllib.request, zipfile, subprocess, math
from collections import Counter
from bs4 import BeautifulSoup
import requests
from datetime import datetime
from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel
from typing import List, Dict, Any
import uvicorn
import multiprocessing

app = FastAPI(title="Panop Backend Server")

OUTPUT_DIR = "panop_output"
RIS_DIR = os.path.join(OUTPUT_DIR, "ris")
CONFIG_FILE = os.path.join(OUTPUT_DIR, "panop_config.json")
HISTORY_FILE = os.path.join(OUTPUT_DIR, "panop_history.json")
LEARNING_FILE = os.path.join(OUTPUT_DIR, "panop_ai_profiles.json")

def init_dirs():
    os.makedirs(RIS_DIR, exist_ok=True)
    config = load_config()
    for cat in config.get("categories", []):
        os.makedirs(os.path.join(OUTPUT_DIR, cat.get("dest_folder", cat["name"])), exist_ok=True)

DEFAULT_CONFIG = {
    "categories": [
        {
            "id": "articles",
            "name": "Articles",
            "dest_folder": "Android Articles",
            "domain_keywords": ["arxiv.org", "nature.com"],
            "body_required": ["abstract", "introduction", "conclusion", "references"],
            "body_forbidden": ["shopping cart", "checkout"],
            "tab_group": ""
        },
        {
            "id": "books",
            "name": "Books",
            "dest_folder": "Android Books",
            "domain_keywords": ["goodreads.com", "amazon.com", "springer.com"],
            "body_required": ["isbn", "paperback", "hardcover", "publisher"],
            "body_forbidden": ["skillet", "kitchen", "toy"],
            "tab_group": ""
        }
    ],
    "rules": {"trust_all_pdfs": True},
    "wireless_ips": []
}

def load_json(path, default):
    if not os.path.exists(path): return default
    try:
        with open(path, "r", encoding="utf-8") as f: return json.load(f)
    except: return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f: json.dump(data, f, indent=4)

def load_config():
    if not os.path.exists(CONFIG_FILE):
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        save_json(CONFIG_FILE, DEFAULT_CONFIG)
        return DEFAULT_CONFIG
    return load_json(CONFIG_FILE, DEFAULT_CONFIG)

def load_history(): return load_json(HISTORY_FILE, {})
def save_history(h): save_json(HISTORY_FILE, h)
def load_profiles(): return load_json(LEARNING_FILE, {})
def save_profiles(p): save_json(LEARNING_FILE, p)

def get_words(text):
    return [w for w in "".join([c if c.isalnum() else " " for c in text.lower()]).split() if len(w) > 3]

def update_ai_profile(category_id, text):
    profiles = load_profiles()
    if category_id not in profiles: profiles[category_id] = {}
    words = get_words(text)
    for w in words: profiles[category_id][w] = profiles[category_id].get(w, 0) + 1
    save_profiles(profiles)

def get_ai_prediction(text):
    profiles = load_profiles()
    if not profiles: return None
    words = get_words(text)
    scores = {}
    for cat_id, profile in profiles.items():
        score = sum(profile.get(w, 0) for w in words)
        if score > 0: scores[cat_id] = score
    if not scores: return None
    best_cat = max(scores, key=scores.get)
    if scores[best_cat] > 20: return best_cat
    return None

def ensure_adb():
    adb_dir = os.path.join(OUTPUT_DIR, "platform-tools")
    adb_exe = os.path.join(adb_dir, "platform-tools", "adb.exe")
    if not os.path.exists(adb_exe):
        zip_path = os.path.join(OUTPUT_DIR, "tools.zip")
        urllib.request.urlretrieve("https://dl.google.com/android/repository/platform-tools-latest-windows.zip", zip_path)
        with zipfile.ZipFile(zip_path, 'r') as z: z.extractall(adb_dir)
        os.remove(zip_path)
    return adb_exe

def fetch_page_content(url):
    metadata = {"title": "", "authors": [], "journal": "", "abstract": "", "text": ""}
    try:
        resp = requests.get(url, timeout=5, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            metadata["text"] = soup.get_text().lower()
            t = soup.find("meta", {"name": "citation_title"})
            metadata["title"] = t.get("content", "") if t else (soup.title.string if soup.title else "")
            metadata["authors"] = [tag.get("content", "") for tag in soup.find_all("meta", {"name": "citation_author"})]
            j = soup.find("meta", {"name": "citation_journal_title"})
            if j: metadata["journal"] = j.get("content", "")
            ab = soup.find("meta", {"name": "description"})
            if ab: metadata["abstract"] = ab.get("content", "")
    except Exception: pass
    return metadata

def run_adb_sweep():
    try:
        adb_exe = ensure_adb()
        config = load_config()
        init_dirs()
        for ip in config.get("wireless_ips", []):
            subprocess.run([adb_exe, "connect", ip], capture_output=True)
            
        subprocess.run([adb_exe, "forward", "tcp:9222", "localabstract:chrome_devtools_remote"], capture_output=True)
        resp = requests.get("http://127.0.0.1:9222/json/list", timeout=5)
        if resp.status_code != 200: return
        tabs = resp.json()
        history = load_history()
        categories = config.get("categories", [])
        
        for tab in tabs:
            url = tab.get("url", "")
            if url.startswith("chrome://") or not url or url in history: continue
            
            url_lower = url.lower()
            is_pdf = url_lower.endswith(".pdf")
            
            matched_category = None
            ai_discovered = False
            metadata = {}

            # Strict Logic Router
            for cat in categories:
                domains = cat.get("domain_keywords", [])
                body_req = cat.get("body_required", [])
                body_forb = cat.get("body_forbidden", [])
                
                domain_match = any(d.lower() in url_lower for d in domains if d)
                
                if domain_match or (not domains):
                    # Fetch body if required keywords exist
                    if (body_req or body_forb) and not metadata and not is_pdf:
                        metadata = fetch_page_content(url)
                    
                    text = metadata.get("text", "")
                    req_match = all(kw.lower() in text for kw in body_req if kw) if body_req else True
                    forb_match = any(kw.lower() in text for kw in body_forb if kw) if body_forb else False
                    
                    if req_match and not forb_match:
                        matched_category = cat
                        break

            # AI Fallback Recommender
            if not matched_category and not is_pdf:
                if not metadata: metadata = fetch_page_content(url)
                text = metadata.get("text", "")
                if text:
                    ai_cat_id = get_ai_prediction(text)
                    if ai_cat_id:
                        matched_category = next((c for c in categories if c["id"] == ai_cat_id), None)
                        ai_discovered = True

            if matched_category:
                if not metadata and not is_pdf: metadata = fetch_page_content(url)
                title = metadata.get("title") or tab.get("title", "Untitled")
                safe_t = "".join([c for c in title if c.isalpha() or c.isdigit() or c==' ']).rstrip()
                if not safe_t: safe_t = str(int(datetime.now().timestamp()))
                
                # AI Learning
                if text := metadata.get("text"): update_ai_profile(matched_category["id"], text)

                target_dir = os.path.join(OUTPUT_DIR, matched_category.get("dest_folder", matched_category["name"]))
                with open(os.path.join(target_dir, f"{safe_t.replace(' ', '_')}.md"), "w", encoding="utf-8") as f:
                    f.write(f"# {title}\n**URL:** {url}\n**Category:** {matched_category['name']}\n")
                    if ai_discovered: f.write("**Note:** Discovered by AI Content Recommender\n")
                    if metadata.get("abstract"): f.write(f"\n## Abstract\n{metadata['abstract']}\n")

                history[url] = {"title": title, "category": matched_category["name"], "cat_id": matched_category["id"], "date": datetime.now().isoformat(), "ai_learned": ai_discovered}
                save_history(history)
                
                tab_id = tab.get("id")
                if tab_id: requests.get(f"http://127.0.0.1:9222/json/close/{tab_id}", timeout=2)

    except Exception: pass

def adb_loop():
    while True:
        run_adb_sweep()
        time.sleep(21600)

@app.on_event("startup")
def start_background_jobs():
    init_dirs()
    threading.Thread(target=adb_loop, daemon=True).start()

@app.get("/api/v1/config")
def get_config(): return load_config()

@app.post("/api/v1/config")
def update_config(req_data: dict):
    save_json(CONFIG_FILE, req_data)
    init_dirs()
    return {"status": "updated"}

@app.get("/api/v1/history")
def get_history(): return load_history()

class EditItem(BaseModel):
    url: str
    title: str
    category_id: str

@app.post("/api/v1/history/edit")
def edit_history(item: EditItem):
    h = load_history()
    if item.url in h:
        config = load_config()
        cat = next((c for c in config["categories"] if c["id"] == item.category_id), None)
        h[item.url]["title"] = item.title
        if cat:
            h[item.url]["cat_id"] = cat["id"]
            h[item.url]["category"] = cat["name"]
        save_history(h)
    return {"status": "ok"}

class DeleteItem(BaseModel):
    urls: List[str]

@app.post("/api/v1/history/delete")
def delete_history(item: DeleteItem):
    h = load_history()
    for u in item.urls:
        if u in h: del h[u]
    save_history(h)
    return {"status": "ok"}

@app.post("/api/v1/fetch_now")
def fetch_now(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_adb_sweep)
    return {"status": "fetching"}

@app.get("/api/v1/system_paths")
def get_paths():
    return {"output_dir": os.path.abspath(OUTPUT_DIR)}

if __name__ == "__main__":
    multiprocessing.freeze_support()
    uvicorn.run(app, host="127.0.0.1", port=8000)
