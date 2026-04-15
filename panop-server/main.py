import os, json, rispy, threading, time, urllib.request, zipfile, subprocess
from bs4 import BeautifulSoup
import requests
from datetime import datetime
from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel
import uvicorn
import multiprocessing

app = FastAPI(title="Panop Backend Server")

OUTPUT_DIR = "panop_output"
RIS_DIR = os.path.join(OUTPUT_DIR, "ris")
CONFIG_FILE = os.path.join(OUTPUT_DIR, "panop_config.json")
HISTORY_FILE = os.path.join(OUTPUT_DIR, "panop_history.json")

def init_dirs():
    os.makedirs(RIS_DIR, exist_ok=True)
    config = load_config()
    for cat in config.get("categories", []):
        d = os.path.join(OUTPUT_DIR, cat.get("dest_folder", cat["name"]))
        os.makedirs(d, exist_ok=True)

DEFAULT_CONFIG = {
    "categories": [
        {
            "id": "articles",
            "name": "Articles",
            "dest_folder": "Android Articles",
            "domain_keywords": ["arxiv.org", "nature.com", "sciencedirect.com", "ncbi.nlm.nih.gov", "springer.com", "ieeexplore.ieee.org", "frontiersin.org", "ncbi.nlm.nih.gov"],
            "must_be_book": False
        },
        {
            "id": "books",
            "name": "Books",
            "dest_folder": "Android Books",
            "domain_keywords": ["goodreads.com", "amazon.com", "libgen.is", "gutenberg.org", "springer.com", "taylorandfrancis.com", "oup.com"],
            "must_be_book": True
        }
    ],
    "rules": {"trust_all_pdfs": True, "strict_mode": False},
    "wireless_ips": []
}

def load_config():
    if not os.path.exists(CONFIG_FILE):
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        with open(CONFIG_FILE, "w") as f: json.dump(DEFAULT_CONFIG, f, indent=4)
        return DEFAULT_CONFIG
    with open(CONFIG_FILE, "r") as f: return json.load(f)

def load_history():
    if not os.path.exists(HISTORY_FILE): return {}
    with open(HISTORY_FILE, "r") as f: return json.load(f)

def save_history(history):
    with open(HISTORY_FILE, "w") as f: json.dump(history, f, indent=4)

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
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
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
    print("Running ADB sweep...")
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
            is_pdf = url_lower.endswith(".pdf") and config.get("rules", {}).get("trust_all_pdfs", True)

            matched_category = None
            metadata = {}

            # Route resolution
            for cat in categories:
                domains = cat.get("domain_keywords", [])
                if any(d.lower() in url_lower for d in domains) or (is_pdf and cat["id"] == "articles"):
                    if cat.get("must_be_book") and not is_pdf:
                        metadata = fetch_page_content(url)
                        text = metadata["text"]
                        # Strict book filtration: ignore shop skillets unless they contain book ISBN identifiers
                        if any(kw in text for kw in ["isbn", "paperback", "hardcover", "publisher", "edition", "epub"]):
                            matched_category = cat
                            break
                    else:
                        matched_category = cat
                        break
            
            if matched_category:
                print(f"Captured: {url} into {matched_category['name']}")
                if not metadata and not is_pdf:
                    metadata = fetch_page_content(url)
                
                title = metadata.get("title") or tab.get("title", "Untitled")
                safe_t = "".join([c for c in title if c.isalpha() or c.isdigit() or c==' ']).rstrip()
                if not safe_t: safe_t = str(int(datetime.now().timestamp()))
                
                target_dir = os.path.join(OUTPUT_DIR, matched_category.get("dest_folder", matched_category["name"]))
                with open(os.path.join(target_dir, f"{safe_t.replace(' ', '_')}.md"), "w", encoding="utf-8") as f:
                    f.write(f"# {title}\n**URL:** {url}\n**Category:** {matched_category['name']}\n")
                    if metadata.get("abstract"): f.write(f"\n## Abstract\n{metadata['abstract']}\n")

                # RIS Generation bucketed
                week_num = datetime.now().isocalendar()[1]
                ris_path = os.path.join(RIS_DIR, f"{matched_category['id']}_week_{week_num}.ris")
                entry = {"type_of_reference": "BOOK" if matched_category.get("must_be_book") else "JOUR", "title": title, "url": url}
                if metadata.get("authors"): entry["authors"] = metadata["authors"]
                if metadata.get("journal"): entry["journal_name"] = metadata["journal"]
                
                entries = []
                if os.path.exists(ris_path):
                    with open(ris_path, "r", encoding="utf-8") as f:
                        try: entries = rispy.load(f)
                        except: pass
                entries.append(entry)
                with open(ris_path, "w", encoding="utf-8") as f: rispy.dump(entries, f)

                history[url] = {"title": title, "category": matched_category["name"], "date": datetime.now().isoformat()}
                save_history(history)
                
                # Auto-Close securely
                tab_id = tab.get("id")
                if tab_id:
                    requests.get(f"http://127.0.0.1:9222/json/close/{tab_id}", timeout=2)

    except Exception as e: print("Sweep err:", e)

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
    with open(CONFIG_FILE, "w") as f: json.dump(req_data, f, indent=4)
    init_dirs()
    return {"status": "updated"}

@app.get("/api/v1/history")
def get_history(): return load_history()

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
