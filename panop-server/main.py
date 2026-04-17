import os, json, threading, time, urllib.request, zipfile, subprocess, math, csv
from concurrent.futures import ThreadPoolExecutor, as_completed
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

# Live sweep status — readable by the UI via /api/v1/status
sweep_status = {
    "last_run": None,
    "adb_connected": False,
    "device_id": None,
    "tabs_seen": 0,
    "tabs_new": 0,
    "tabs_matched": 0,
    "running": False,
    "last_error": None
}

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

history_lock = threading.Lock()

def save_history(h):
    with history_lock:
        save_json(HISTORY_FILE(), h)
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
    """Returns metadata dict. On network failure returns empty dict (caller detects via missing 'text' key)."""
    try:
        resp = requests.get(url, timeout=12, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            metadata = {}
            metadata["text"] = soup.get_text().lower()
            t = soup.find("meta", {"name": "citation_title"})
            metadata["title"] = t.get("content", "") if t else (soup.title.string if soup.title else "")
            ab = soup.find("meta", {"name": "description"})
            if ab: metadata["abstract"] = ab.get("content", "")
            return metadata
    except Exception:
        pass
    return None  # None = fetch failed/timed out (distinct from empty body)

def add_chrome_bookmark(url, title, category_name):
    """Saves a bookmark into the user's existing Chrome 'Outro Favoritos' (Other Bookmarks),
    placing it directly inside a folder matching the category name. Creates the folder if missing."""
    profile = os.environ.get("USERPROFILE")
    if not profile: return
    book_path = os.path.join(profile, "AppData", "Local", "Google", "Chrome", "User Data", "Default", "Bookmarks")
    if not os.path.exists(book_path): return
    try:
        with open(book_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        # 'other' IS 'Outro Favoritos' in Portuguese Chrome
        other = data.get("roots", {}).get("other", {})
        if "children" not in other:
            other["children"] = []
        
        # Look for an existing folder with this category name directly inside Outro Favoritos
        cat_folder = next(
            (c for c in other["children"] if c.get("type") == "folder" and c.get("name", "").lower() == category_name.lower()),
            None
        )
        if not cat_folder:
            stamp = str(int(time.time() * 1000000))
            cat_folder = {"children": [], "date_added": stamp, "date_last_used": "0", "guid": "", "name": category_name, "type": "folder"}
            other["children"].append(cat_folder)
        
        # Add bookmark only if not already present
        if not any(c.get("url") == url for c in cat_folder.get("children", [])):
            stamp = str(int(time.time() * 1000000))
            cat_folder["children"].append({"date_added": stamp, "date_last_used": "0", "guid": "", "name": title, "type": "url", "url": url})
            with open(book_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass

def run_adb_sweep():
    global sweep_status
    sweep_status["running"] = True
    sweep_status["last_run"] = datetime.now().isoformat()
    sweep_status["last_error"] = None
    sweep_status["tabs_seen"] = 0
    sweep_status["tabs_new"] = 0
    sweep_status["tabs_matched"] = 0
    try:
        adb_exe = ensure_adb()
        config = load_config()
        env = get_env()
        init_dirs()
        
        # Check what devices are actually connected
        dev_result = subprocess.run([adb_exe, "devices"], capture_output=True, text=True)
        lines = [l.strip() for l in dev_result.stdout.splitlines() if l.strip() and "List of" not in l and "offline" not in l]
        sweep_status["adb_connected"] = len(lines) > 0
        sweep_status["device_id"] = lines[0].split("\t")[0] if lines else None
        
        if not sweep_status["adb_connected"]:
            for ip in config.get("wireless_ips", []):
                subprocess.run([adb_exe, "connect", ip], capture_output=True)
            # Re-check after connect attempts
            dev_result = subprocess.run([adb_exe, "devices"], capture_output=True, text=True)
            lines = [l.strip() for l in dev_result.stdout.splitlines() if l.strip() and "List of" not in l and "offline" not in l]
            sweep_status["adb_connected"] = len(lines) > 0
            sweep_status["device_id"] = lines[0].split("\t")[0] if lines else None

        if not sweep_status["adb_connected"]:
            sweep_status["last_error"] = "No Android device found via ADB. Connect phone via USB (with USB Debugging on) or add its IP in System Settings."
            sweep_status["running"] = False
            return
            
        subprocess.run([adb_exe, "forward", "tcp:9222", "localabstract:chrome_devtools_remote"], capture_output=True)
        resp = requests.get("http://127.0.0.1:9222/json/list", timeout=30)
        if resp.status_code != 200:
            sweep_status["last_error"] = f"DevTools returned HTTP {resp.status_code}. Make sure Chrome is open and in the foreground on your phone."
            sweep_status["running"] = False
            return
        tabs = resp.json()
        sweep_status["tabs_seen"] = len(tabs)
        history = load_history()
        categories = config.get("categories", [])
        strict = env.get("strict_domain_scan", True)
        catch_uncat = env.get("catch_uncategorized", False)

        # ── PHASE 1: Pure string matching (no network, instant) ──────────────
        # Build list of (tab, cat, needs_body_fetch) for candidates only
        candidates = []  # (tab, matched_cat_no_body_check, needs_fetch)
        for tab in tabs:
            url = tab.get("url", "")
            if not url or url.startswith("chrome://") or url in history:
                continue
            sweep_status["tabs_new"] += 1
            url_lower = url.lower()
            is_pdf = url_lower.endswith(".pdf")

            domain_matched_cat = None
            needs_fetch = False

            for cat in categories:
                domains = cat.get("domain_keywords", [])
                body_req = cat.get("body_required", [])
                body_forb = cat.get("body_forbidden", [])
                tab_group = cat.get("tab_group", "")

                if tab_group and tab_group.lower() not in str(tab).lower():
                    continue

                domain_match = any(d.lower() in url_lower for d in domains if d) if domains else True

                if not domain_match and strict and domains:
                    continue  # strict mode: skip if no domain match

                if domain_match or not domains:
                    # If no body keywords needed, match immediately
                    if not body_req and not body_forb and not is_pdf:
                        domain_matched_cat = cat
                        needs_fetch = False  # still fetch for title/abstract
                        break
                    elif not is_pdf:
                        domain_matched_cat = cat
                        needs_fetch = True
                        break

            if domain_matched_cat:
                candidates.append((tab, domain_matched_cat, needs_fetch))
            elif catch_uncat and not any(url.startswith("chrome://") for _ in [1]):
                candidates.append((tab, {"name": "Uncategorized", "id": "uncategorized",
                                         "dest_folder": os.path.join(OUTPUT_DIR(), "Uncategorized")}, True))

        sweep_status["tabs_seen"] = len(tabs)

        # ── PHASE 2: Parallel page fetches for candidates ────────────────────
        def process_tab(tab, cat, needs_fetch):
            """Worker: fetch page if needed, run body keyword check, return result or None.
            Key rule: if fetch FAILS (timeout/network error) but the URL domain-matched,
            we still include the tab — trust the domain. Only exclude when page loads
            successfully and keywords are provably absent.
            """
            url = tab.get("url", "")
            url_lower = url.lower()
            is_pdf = url_lower.endswith(".pdf")
            body_req = cat.get("body_required", [])
            body_req_mode = cat.get("body_required_mode", "ALL")
            body_forb = cat.get("body_forbidden", [])
            domains = cat.get("domain_keywords", [])
            domain_matched = any(d.lower() in url_lower for d in domains if d) if domains else True

            metadata = None
            if needs_fetch and not is_pdf:
                metadata = fetch_page_content(url)  # returns None on failure

            fetch_failed = metadata is None
            text = (metadata or {}).get("text", "")

            if fetch_failed:
                # Fetch timed out / network error.
                # If domain clearly matched → trust it and include.
                # If no domain list (open category) → skip (too risky without body check).
                if domain_matched and domains:
                    req_match = True
                    forb_match = False
                else:
                    return None
            else:
                # Page loaded — apply body keyword rules strictly
                if body_req_mode == "ANY":
                    req_match = any(kw.lower() in text for kw in body_req if kw) if body_req else True
                else:
                    req_match = all(kw.lower() in text for kw in body_req if kw) if body_req else True
                forb_match = any(kw.lower() in text for kw in body_forb if kw) if body_forb else False

            if not req_match or forb_match:
                return None

            # Title: prefer page metadata, fall back to DevTools tab title
            title = (metadata or {}).get("title") or tab.get("title", "Untitled")
            return (url, cat, title, metadata or {})

        # Run up to 20 tabs in parallel
        WORKERS = 20
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = {pool.submit(process_tab, tab, cat, needs_fetch): (tab, cat)
                       for tab, cat, needs_fetch in candidates}

            for future in as_completed(futures):
                try:
                    result = future.result()
                    if result is None:
                        continue
                    url, matched_category, title, metadata = result

                    # Skip if another parallel worker already saved this url
                    history = load_history()
                    if url in history:
                        continue

                    safe_t = "".join([c for c in title if c.isalpha() or c.isdigit() or c == ' ']).rstrip()
                    if not safe_t: safe_t = str(int(datetime.now().timestamp()))

                    if metadata.get("text") and matched_category["id"] != "uncategorized":
                        update_ai_profile(matched_category["id"], metadata["text"])

                    d = matched_category.get("dest_folder", matched_category["name"])
                    target_dir = d if os.path.isabs(d) else os.path.join(OUTPUT_DIR(), d)
                    os.makedirs(target_dir, exist_ok=True)

                    with open(os.path.join(target_dir, f"{safe_t.replace(' ', '_')}.md"), "w", encoding="utf-8") as f:
                        f.write(f"# {title}\n**URL:** {url}\n**Category:** {matched_category['name']}\n")
                        if metadata.get("abstract"): f.write(f"\n## Abstract\n{metadata['abstract']}\n")

                    history[url] = {"title": title, "category": matched_category["name"],
                                    "cat_id": matched_category["id"],
                                    "date": datetime.now().isoformat(), "ai_learned": False}
                    save_history(history)
                    add_chrome_bookmark(url, title, matched_category["name"])
                    sweep_status["tabs_matched"] += 1

                except Exception:
                    continue

    except Exception as e:
        sweep_status["last_error"] = str(e)
    finally:
        sweep_status["running"] = False

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
    # Merge: never let a save wipe out wireless_ips unless the user explicitly cleared them
    existing = load_config()
    # If incoming request has empty wireless_ips but stored copy has entries, preserve stored ones
    if not req_data.get("wireless_ips") and existing.get("wireless_ips"):
        req_data["wireless_ips"] = existing["wireless_ips"]
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

@app.get("/api/v1/status")
def get_status(): return sweep_status

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
