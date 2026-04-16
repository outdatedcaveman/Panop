import os, json, threading, time, urllib.request, zipfile, subprocess, math, csv
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

ENV_FILE = "panop_env.json"

def get_env():
    if not os.path.exists(ENV_FILE):
        env = {
            "root_dir": "panop_output",
            "interval_hours": 6,
            "catch_uncategorized": False,
            "strict_domain_scan": True,
            "port": 8000
        }
        with open(ENV_FILE, "w") as f: json.dump(env, f)
        return env
    try:
        with open(ENV_FILE, "r") as f: return json.load(f)
    except: 
        return {
            "root_dir": "panop_output",
            "interval_hours": 6,
            "catch_uncategorized": False,
            "strict_domain_scan": True,
            "port": 8000
        }

def save_env(env):
    with open(ENV_FILE, "w") as f: json.dump(env, f, indent=4)

def OUTPUT_DIR(): return get_env().get("root_dir", "panop_output")
def RIS_DIR(): return os.path.join(OUTPUT_DIR(), "ris")
def EXPORT_DIR(): return os.path.join(OUTPUT_DIR(), "exports")
def CONFIG_FILE(): return os.path.join(OUTPUT_DIR(), "panop_config.json")
def HISTORY_FILE(): return os.path.join(OUTPUT_DIR(), "panop_history.json")
def LEARNING_FILE(): return os.path.join(OUTPUT_DIR(), "panop_ai_profiles.json")

def init_dirs():
    os.makedirs(OUTPUT_DIR(), exist_ok=True)
    os.makedirs(RIS_DIR(), exist_ok=True)
    os.makedirs(EXPORT_DIR(), exist_ok=True)
    config = load_config()
    for cat in config.get("categories", []):
        d = cat.get("dest_folder", cat["name"])
        target = d if os.path.isabs(d) else os.path.join(OUTPUT_DIR(), d)
        os.makedirs(target, exist_ok=True)

DEFAULT_CONFIG = {
    "categories": [
        {
            "id": "articles", "name": "Articles", "dest_folder": "Android Articles",
            "domain_keywords": ["arxiv.org", "nature.com"], "body_required": ["abstract"],
            "body_required_mode": "ALL", "body_forbidden": [], "tab_group": "", "max_age_days": ""
        },
        {
            "id": "books", "name": "Books", "dest_folder": "Android Books",
            "domain_keywords": ["goodreads.com"], "body_required": ["isbn"],
            "body_required_mode": "ANY", "body_forbidden": [], "tab_group": "", "max_age_days": ""
        }
    ],
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
    if not os.path.exists(CONFIG_FILE()):
        os.makedirs(OUTPUT_DIR(), exist_ok=True)
        save_json(CONFIG_FILE(), DEFAULT_CONFIG)
        return DEFAULT_CONFIG
    return load_json(CONFIG_FILE(), DEFAULT_CONFIG)

def load_history(): return load_json(HISTORY_FILE(), {})
def save_history(h): save_json(HISTORY_FILE(), h)
def load_profiles(): return load_json(LEARNING_FILE(), {})
def save_profiles(p): save_json(LEARNING_FILE(), p)

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
    adb_dir = os.path.join(OUTPUT_DIR(), "platform-tools")
    adb_exe = os.path.join(adb_dir, "platform-tools", "adb.exe")
    if not os.path.exists(adb_exe):
        zip_path = os.path.join(OUTPUT_DIR(), "tools.zip")
        urllib.request.urlretrieve("https://dl.google.com/android/repository/platform-tools-latest-windows.zip", zip_path)
        with zipfile.ZipFile(zip_path, 'r') as z: z.extractall(adb_dir)
        os.remove(zip_path)
    return adb_exe

def fetch_page_content(url):
    metadata = {"title": "", "abstract": "", "text": ""}
    try:
        resp = requests.get(url, timeout=4, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            metadata["text"] = soup.get_text().lower()
            t = soup.find("meta", {"name": "citation_title"})
            metadata["title"] = t.get("content", "") if t else (soup.title.string if soup.title else "")
            ab = soup.find("meta", {"name": "description"})
            if ab: metadata["abstract"] = ab.get("content", "")
    except Exception: pass
    return metadata

def add_chrome_bookmark(url, title, category_name):
    profile = os.environ.get("USERPROFILE")
    if not profile: return
    book_path = os.path.join(profile, "AppData", "Local", "Google", "Chrome", "User Data", "Default", "Bookmarks")
    if not os.path.exists(book_path): return
    try:
        with open(book_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        other = data.get("roots", {}).get("other", {})
        if "children" not in other:
            other["children"] = []
            
        panop_folder = next((c for c in other["children"] if c.get("name") == "Panop" and c.get("type") == "folder"), None)
        if not panop_folder:
            stamp = str(int(time.time() * 1000000))
            panop_folder = {"children": [], "date_added": stamp, "date_last_used": "0", "name": "Panop", "type": "folder"}
            other["children"].append(panop_folder)
            
        cat_folder = next((c for c in panop_folder["children"] if c.get("name") == category_name and c.get("type") == "folder"), None)
        if not cat_folder:
            stamp = str(int(time.time() * 1000000))
            cat_folder = {"children": [], "date_added": stamp, "date_last_used": "0", "name": category_name, "type": "folder"}
            panop_folder["children"].append(cat_folder)
            
        if not any(c.get("url") == url for c in cat_folder["children"]):
            stamp = str(int(time.time() * 1000000))
            cat_folder["children"].append({"date_added": stamp, "name": title, "type": "url", "url": url})
            with open(book_path, "w", encoding="utf-8") as f:
                json.dump(data, f)
    except Exception:
        pass

def run_adb_sweep():
    try:
        adb_exe = ensure_adb()
        config = load_config()
        env = get_env()
        init_dirs()
        for ip in config.get("wireless_ips", []):
            subprocess.run([adb_exe, "connect", ip], capture_output=True)
            
        subprocess.run([adb_exe, "forward", "tcp:9222", "localabstract:chrome_devtools_remote"], capture_output=True)
        resp = requests.get("http://127.0.0.1:9222/json/list", timeout=300)
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

            for cat in categories:
                domains = cat.get("domain_keywords", [])
                body_req = cat.get("body_required", [])
                body_req_mode = cat.get("body_required_mode", "ALL")
                body_forb = cat.get("body_forbidden", [])
                tab_group = cat.get("tab_group", "")
                
                # Substring matching
                domain_match = any(d.lower() in url_lower for d in domains if d)
                
                # Tab Group constraint checking (cheap)
                group_match = True
                if tab_group: group_match = tab_group.lower() in str(tab).lower()
                
                if group_match:
                    # Expensive logic evaluation pipeline
                    bypass_body_scan = False
                    
                    if env.get("strict_domain_scan", False):
                        # Strict mode: Only fetch heavy body text if the URL domain string matches explicit domain list perfectly
                        # If the category has NO domains, strict mode blocks the body scan to prevent scraping the whole internet.
                        if domains and domain_match:
                            bypass_body_scan = False
                        else:
                            bypass_body_scan = True
                            
                    if (domain_match or not domains):
                        if (body_req or body_forb) and not metadata and not is_pdf and not bypass_body_scan:
                            metadata = fetch_page_content(url)
                    
                        text = metadata.get("text", "")
                        if body_req_mode == "ANY":
                            req_match = any(kw.lower() in text for kw in body_req if kw) if body_req else True
                        else:
                            req_match = all(kw.lower() in text for kw in body_req if kw) if body_req else True
                        forb_match = any(kw.lower() in text for kw in body_forb if kw) if body_forb else False
                        
                        if req_match and not forb_match:
                            matched_category = cat
                            break

            # Attempt AI prediction if user enables Uncategorized capturing or AI distribution mappings
            if not matched_category and not is_pdf and (env.get("catch_uncategorized", False)):
                if not metadata: metadata = fetch_page_content(url)
                text = metadata.get("text", "")
                if text:
                    ai_cat_id = get_ai_prediction(text)
                    if ai_cat_id:
                        matched_category = next((c for c in categories if c["id"] == ai_cat_id), None)
                        ai_discovered = True

            # Uncategorized Catcher Switch
            if not matched_category and env.get("catch_uncategorized", False):
                matched_category = {"name": "Uncategorized", "id": "uncategorized", "dest_folder": os.path.join(OUTPUT_DIR(), "Uncategorized")}

            if matched_category:
                if not metadata and not is_pdf: metadata = fetch_page_content(url)
                title = metadata.get("title") or tab.get("title", "Untitled")
                safe_t = "".join([c for c in title if c.isalpha() or c.isdigit() or c==' ']).rstrip()
                if not safe_t: safe_t = str(int(datetime.now().timestamp()))
                
                if text := metadata.get("text"): 
                    if matched_category["id"] != "uncategorized":
                        update_ai_profile(matched_category["id"], text)

                d = matched_category.get("dest_folder", matched_category["name"])
                target_dir = d if os.path.isabs(d) else os.path.join(OUTPUT_DIR(), d)
                os.makedirs(target_dir, exist_ok=True)
                
                with open(os.path.join(target_dir, f"{safe_t.replace(' ', '_')}.md"), "w", encoding="utf-8") as f:
                    f.write(f"# {title}\n**URL:** {url}\n**Category:** {matched_category['name']}\n")
                    if ai_discovered: f.write("**Note:** Discovered by AI Content Recommender\n")
                    if metadata.get("abstract"): f.write(f"\n## Abstract\n{metadata['abstract']}\n")

                history[url] = {"title": title, "category": matched_category["name"], "cat_id": matched_category["id"], "date": datetime.now().isoformat(), "ai_learned": ai_discovered}
                save_history(history)
                add_chrome_bookmark(url, title, matched_category["name"])
                
                tab_id = tab.get("id")
                # Removed json/close execution to preserve tabs gracefully on Android and prevent data destruction paranoia

    except Exception as e:
        pass

def adb_loop():
    while True:
        run_adb_sweep()
        hours = get_env().get("interval_hours", 6)
        if hours < 0.1: hours = 0.1
        time.sleep(hours * 3600)

@app.on_event("startup")
def start_background_jobs():
    init_dirs()
    threading.Thread(target=adb_loop, daemon=True).start()

@app.get("/api/v1/config")
def get_co(): return load_config()

@app.post("/api/v1/config")
def update_co(req_data: dict):
    save_json(CONFIG_FILE(), req_data)
    init_dirs()
    return {"status": "updated"}

@app.get("/api/v1/env")
def read_env(): return get_env()

@app.post("/api/v1/env")
def update_ev(data: dict):
    save_env(data)
    init_dirs()
    return {"status": "ok"}

@app.get("/api/v1/history")
def get_hi(): return load_history()

class EditItem(BaseModel):
    old_url: str
    url: str
    title: str
    category_id: str
    date: str

@app.post("/api/v1/history/edit")
def edit_hi(item: EditItem):
    h = load_history()
    if item.old_url in h:
        val = h[item.old_url]
        val["title"] = item.title
        val["date"] = item.date
        config = load_config()
        cat = next((c for c in config["categories"] if c["id"] == item.category_id), None)
        if cat: val.update({"cat_id": cat["id"], "category": cat["name"]})
        
        if item.url != item.old_url:
            del h[item.old_url]
            h[item.url] = val
        save_history(h)
    return {"status": "ok"}

class DeleteItem(BaseModel): urls: List[str]

@app.post("/api/v1/history/delete")
def del_hi(item: DeleteItem):
    h = load_history()
    for u in item.urls:
        if u in h: del h[u]
    save_history(h)
    return {"status": "ok"}

@app.post("/api/v1/fetch_now")
def f_now(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_adb_sweep)
    return {"status": "fetching"}

@app.get("/api/v1/system_paths")
def get_pa(): return {"output_dir": os.path.abspath(OUTPUT_DIR()), "export_dir": os.path.abspath(EXPORT_DIR())}

@app.post("/api/v1/export/{format}")
def export_db(format: str):
    os.makedirs(EXPORT_DIR(), exist_ok=True)
    h = load_history()
    out = os.path.join(EXPORT_DIR(), f"panop_database_{int(time.time())}")
    
    if format == "json":
        with open(out+".json", "w") as f: json.dump(h, f, indent=4)
    elif format == "csv":
        with open(out+".csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["URL", "Title", "Category", "Date", "AI Learned"])
            for url, data in h.items():
                w.writerow([url, data.get("title",""), data.get("category",""), data.get("date",""), data.get("ai_learned",False)])
    elif format == "md":
        with open(out+".md", "w", encoding="utf-8") as f:
            f.write("# Panop Database Export\n\n")
            for url, data in h.items():
                f.write(f"- **{data.get('category','')}**: [{data.get('title','')}]({url}) ({data.get('date','')})\n")
    elif format == "zip":
        with zipfile.ZipFile(out+".zip", 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(OUTPUT_DIR()):
                if "exports" in root: continue
                for file in files:
                    fp = os.path.join(root, file)
                    zf.write(fp, os.path.relpath(fp, OUTPUT_DIR()))
    return {"status": "ok", "path": out+"."+format}

if __name__ == "__main__":
    multiprocessing.freeze_support()
    uvicorn.run(app, host="127.0.0.1", port=8000)
