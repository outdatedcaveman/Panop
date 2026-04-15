import os, json, rispy, threading, time, urllib.request, zipfile, subprocess
from bs4 import BeautifulSoup
import requests
from datetime import datetime
from fastapi import FastAPI, Request
from pydantic import BaseModel
import uvicorn
import multiprocessing

app = FastAPI(title="Panop Backend Server")

class TabData(BaseModel):
    url: str; title: str; timestamp: str; is_pdf: bool

OUTPUT_DIR = "panop_output"
RIS_DIR = os.path.join(OUTPUT_DIR, "ris")
ARTICLES_DIR = os.path.join(OUTPUT_DIR, "Android Articles")
BOOKS_DIR = os.path.join(OUTPUT_DIR, "Android Books")
CONFIG_FILE = os.path.join(OUTPUT_DIR, "panop_config.json")
HISTORY_FILE = os.path.join(OUTPUT_DIR, "panop_history.json")

for d in [RIS_DIR, ARTICLES_DIR, BOOKS_DIR]: os.makedirs(d, exist_ok=True)

DEFAULT_CONFIG = {
    "articles_domains": ["arxiv.org", "nature.com", "sciencedirect.com", "ncbi.nlm.nih.gov", "springer.com", "ieeexplore.ieee.org"],
    "books_domains": ["goodreads.com", "amazon.com", "libgen.is", "gutenberg.org"],
    "rules": {"trust_all_pdfs": True, "strict_mode": False},
    "wireless_ips": []
}

def load_config():
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w") as f: json.dump(DEFAULT_CONFIG, f, indent=4)
        return DEFAULT_CONFIG
    with open(CONFIG_FILE, "r") as f: return json.load(f)

# ... (omitting history functions unchanged) ...

def load_history():
    if not os.path.exists(HISTORY_FILE): return {}
    with open(HISTORY_FILE, "r") as f: return json.load(f)


def save_history(history):
    with open(HISTORY_FILE, "w") as f: json.dump(history, f, indent=4)

def get_current_week_ris_path(category="articles"):
    week_num = datetime.now().isocalendar()[1]
    return os.path.join(RIS_DIR, f"{category}_week_{week_num}.ris")

def extract_metadata(url: str):
    metadata = {"title": "", "authors": [], "journal": "", "year": "", "doi": "", "abstract": ""}
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            t = soup.find("meta", {"name": "citation_title"})
            metadata["title"] = t.get("content", "") if t else (soup.title.string if soup.title else "")
            metadata["authors"] = [tag.get("content", "") for tag in soup.find_all("meta", {"name": "citation_author"})]
            j = soup.find("meta", {"name": "citation_journal_title"})
            if j: metadata["journal"] = j.get("content", "")
            d = soup.find("meta", {"name": "citation_publication_date"})
            if d: metadata["year"] = d.get("content", "")[:4]
            doi = soup.find("meta", {"name": "citation_doi"})
            if doi: metadata["doi"] = doi.get("content", "")
            ab = soup.find("meta", {"name": "citation_abstract"}) or soup.find("meta", {"name": "description"})
            if ab: metadata["abstract"] = ab.get("content", "")
    except Exception: pass
    return metadata

def ensure_adb():
    adb_dir = os.path.join(OUTPUT_DIR, "platform-tools")
    adb_exe = os.path.join(adb_dir, "platform-tools", "adb.exe")
    if not os.path.exists(adb_exe):
        zip_path = os.path.join(OUTPUT_DIR, "tools.zip")
        urllib.request.urlretrieve("https://dl.google.com/android/repository/platform-tools-latest-windows.zip", zip_path)
        with zipfile.ZipFile(zip_path, 'r') as z: z.extractall(adb_dir)
        os.remove(zip_path)
    return adb_exe

def adb_loop():
    while True:
        try:
            adb_exe = ensure_adb()
            config = load_config()
            for ip in config.get("wireless_ips", []):
                subprocess.run([adb_exe, "connect", ip], capture_output=True)
                
            subprocess.run([adb_exe, "forward", "tcp:9222", "localabstract:chrome_devtools_remote"], capture_output=True)
            
            resp = requests.get("http://127.0.0.1:9222/json/list", timeout=3)
            if resp.status_code == 200:
                tabs = resp.json()
                history = load_history()
                
                for tab in tabs:
                    url = tab.get("url", "")
                    if url.startswith("chrome://") or not url or url in history: continue
                    
                    url_lower = url.lower()
                    is_art = any(d in url_lower for d in config["articles_domains"])
                    is_bk = any(d in url_lower for d in config["books_domains"])
                    is_pdf = url_lower.endswith(".pdf") and config["rules"].get("trust_all_pdfs", True)
                    
                    cat = "articles" if (is_art or is_pdf) else ("books" if is_bk else None)
                    if cat:
                        print(f"ADB captured and closing: {url}")
                        metadata = extract_metadata(url) if not is_pdf else {}
                        title = metadata.get("title") or tab.get("title", "Untitled")
                        safe_t = "".join([c for c in title if c.isalpha() or c.isdigit() or c==' ']).rstrip()
                        if not safe_t: safe_t = str(int(datetime.now().timestamp()))
                        
                        target_dir = ARTICLES_DIR if cat == "articles" else BOOKS_DIR
                        with open(os.path.join(target_dir, f"{safe_t.replace(' ', '_')}.md"), "w", encoding="utf-8") as f:
                            f.write(f"# {title}\n**URL:** {url}\n**Category:** {cat}\n")
                            if metadata.get("abstract"): f.write(f"\n## Abstract\n{metadata['abstract']}\n")

                        ris = get_current_week_ris_path(cat)
                        entry = {"type_of_reference": "JOUR" if cat=="articles" else "BOOK", "title": title, "url": url}
                        if metadata["authors"]: entry["authors"] = metadata["authors"]
                        if metadata["journal"]: entry["journal_name"] = metadata["journal"]
                        
                        entries = []
                        if os.path.exists(ris):
                            with open(ris, "r", encoding="utf-8") as f:
                                try: entries = rispy.load(f)
                                except: pass
                        entries.append(entry)
                        with open(ris, "w", encoding="utf-8") as f: rispy.dump(entries, f)

                        history[url] = {"title": title, "category": cat, "date": datetime.now().isoformat()}
                        save_history(history)
                        
                        # MAGIC AUTO-CLOSE TAB
                        tab_id = tab.get("id")
                        if tab_id:
                            requests.get(f"http://127.0.0.1:9222/json/close/{tab_id}", timeout=2)
                            
        except Exception: pass
        time.sleep(21600)  # Sleep exactly 6 hours!

@app.on_event("startup")
def start_background_jobs():
    threading.Thread(target=adb_loop, daemon=True).start()

# For Electron GUI
@app.get("/api/v1/config")
def get_config(): return load_config()

@app.post("/api/v1/config")
def update_config(req_data: dict):
    with open(CONFIG_FILE, "w") as f: json.dump(req_data, f, indent=4)
    return {"status": "updated"}

@app.get("/api/v1/history")
def get_history(): return load_history()

if __name__ == "__main__":
    multiprocessing.freeze_support()
    uvicorn.run(app, host="127.0.0.1", port=8000)
