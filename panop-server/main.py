import os, json, threading, time, urllib.request, zipfile, subprocess, math, csv, re
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
            "port": 8000,
            "bookmark_folder": "Panop",          # name of Panop subfolder inside Outros Favoritos
            "zotero_api_key": "",                 # Zotero Web API key
            "zotero_user_id": "",                 # Zotero numeric user ID
            "zotero_collection_key": "",          # optional: target collection key
            "close_tabs_after_save": False,       # opt-in: close tab on phone after successful save
            "chrome_profile": "Default"           # Chrome profile folder name
        }
        with open(ENV_FILE, "w") as f: json.dump(env, f)
        return env
    try:
        with open(ENV_FILE, "r") as f:
            env = json.load(f)
        # Back-fill new keys if missing (upgrade path)
        changed = False
        for k, v in [("bookmark_folder","Panop"),("zotero_api_key",""),("zotero_user_id",""),("zotero_collection_key",""),("close_tabs_after_save", False), ("chrome_profile", "Default")]:
            if k not in env: env[k] = v; changed = True
        if changed: save_env(env)
        return env
    except:
        return {"root_dir":"panop_output","interval_hours":6,"catch_uncategorized":False,"strict_domain_scan":True,"port":8000,"bookmark_folder":"Panop","zotero_api_key":"","zotero_user_id":"","zotero_collection_key":""}

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

def normalize_title(t):
    """Normalize title for fuzzy matching."""
    if not t: return ""
    return re.sub(r'\s+', ' ', t.lower().strip())

def merge_entries(old, new):
    """Lossless merge of two dictionary entries. Favors more detailed data."""
    merged = old.copy()
    # Fields to prefer from 'new' if 'old' is missing/empty
    for field in ["abstract", "category", "cat_id", "date", "source", "author"]:
        if not merged.get(field) and new.get(field):
            merged[field] = new[field]
    
    # URL preference: prefer /abs/ over /pdf/ for Arxiv, etc.
    if "/pdf/" in merged.get("url", "") and "/abs/" in new.get("url", ""):
        merged["url"] = new["url"]
    
    # Category preference: prefer specific category over 'uncategorized'
    if merged.get("cat_id") == "uncategorized" and new.get("cat_id") != "uncategorized":
        merged["cat_id"] = new["cat_id"]
        merged["category"] = new["category"]
        
    return merged

def consolidate_history():
    """Finds items with the same title and merges them into single records."""
    h = load_history()
    by_title = {}
    to_delete = []
    
    for url, item in h.items():
        title = normalize_title(item.get("title"))
        if not title or title in {"untitled", "untitled pdf", "loading..."}:
            continue
            
        if title in by_title:
            existing_url = by_title[title]
            # Merge!
            h[existing_url] = merge_entries(h[existing_url], item)
            to_delete.append(url)
            # If the new URL looks more 'canonical' (like /abs/), swap the primary key
            if "/abs/" in url and "/pdf/" in existing_url:
                h[url] = h.pop(existing_url)
                by_title[title] = url
        else:
            by_title[title] = url
            
    if to_delete:
        for url in to_delete:
            if url in h: del h[url]
        save_history(h)
    return len(to_delete)

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
    """Returns metadata dict. On network failure returns None.
    Caps response at 200KB to prevent huge pages from bloating memory.
    """
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"}, stream=True)
        if resp.status_code == 200:
            # Read at most 200 KB — enough for title + abstract, avoids loading giant pages
            raw = b""
            for chunk in resp.iter_content(chunk_size=8192):
                raw += chunk
                if len(raw) > 200_000:
                    break
            html = raw.decode("utf-8", errors="ignore")
            soup = BeautifulSoup(html, 'html.parser')
            metadata = {}
            metadata["canonical_url"] = resp.url
            # Cap extracted text at 50K chars — more than enough for keyword matching
            text = soup.get_text()
            metadata["text"] = text[:50_000].lower()
            t = soup.find("meta", {"name": "citation_title"})
            metadata["title"] = t.get("content", "") if t else (soup.title.string if soup.title else "")
            ab = soup.find("meta", {"name": "description"})
            if ab: metadata["abstract"] = ab.get("content", "")
            del soup, html, raw, text  # explicitly free memory
            return metadata
    except Exception:
        pass
    return None

def get_pdf_title(url, tab_title=""):
    """Best-effort title resolution for PDF URLs.
    1. Use DevTools tab title if Chrome already resolved it.
    2. For arxiv: fetch the /abs/ page and extract the H1 title.
    3. Fallback: clean up the filename from the URL path.
    """
    if tab_title and tab_title.strip().lower() not in ("", "untitled", "loading..."):
        return tab_title.strip()

    url_lower = url.lower()

    # arxiv special case: swap /pdf/ → /abs/ to get real paper title
    if "arxiv.org/pdf/" in url_lower or "arxiv.org/e-print/" in url_lower:
        try:
            abs_url = url.replace("/pdf/", "/abs/").replace("/e-print/", "/abs/")
            abs_url = abs_url.split("?")[0].rstrip(".pdf")
            resp = requests.get(abs_url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')
                h1 = soup.find("h1", class_="title")
                if h1:
                    # arxiv wraps "Title:" in a span inside the h1 — strip it
                    for span in h1.find_all("span"): span.decompose()
                    return h1.get_text(strip=True)
        except Exception:
            pass

    # Generic: derive a readable name from the URL path
    try:
        from urllib.parse import urlparse, unquote
        path = unquote(urlparse(url).path)
        name = path.rstrip("/").split("/")[-1]
        name = name.rsplit(".", 1)[0]  # strip extension
        name = name.replace("-", " ").replace("_", " ").strip()
        if name:
            return name
    except Exception:
        pass

    return "Untitled PDF"

def add_chrome_bookmark(url, title, category_name):
    """Saves a bookmark into a dedicated Panop subfolder inside 'Outros Favoritos'.
    Structure: Outros Favoritos > [bookmark_folder] > [category_name]
    Never touches any of the user's existing folders.
    The Panop parent folder name is configurable via System Settings > bookmark_folder.
    """
    env = get_env()
    profile_name = env.get("chrome_profile", "Default") or "Default"
    
    profile = os.environ.get("USERPROFILE")
    if not profile: return
    book_path = os.path.join(profile, "AppData", "Local", "Google", "Chrome", "User Data", profile_name, "Bookmarks")
    if not os.path.exists(book_path):
        # Fallback to search if specific one fails? No, let's stick to config.
        return
    try:
        with open(book_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Chrome internal key for "Outros Favoritos" is always "other"
        other = data.get("roots", {}).get("other", {})
        if "children" not in other:
            other["children"] = []

        env = get_env()
        panop_folder_name = env.get("bookmark_folder", "Panop") or "Panop"

        # Level 1: find or create the Panop parent folder
        panop_folder = next(
            (c for c in other["children"] if c.get("type") == "folder" and c.get("name", "") == panop_folder_name),
            None
        )
        if not panop_folder:
            stamp = str(int(time.time() * 1000000))
            panop_folder = {"children": [], "date_added": stamp, "date_last_used": "0",
                            "guid": "", "name": panop_folder_name, "type": "folder"}
            other["children"].append(panop_folder)

        # Level 2: find or create the category subfolder inside Panop
        cat_folder = next(
            (c for c in panop_folder["children"] if c.get("type") == "folder" and c.get("name", "").lower() == category_name.lower()),
            None
        )
        if not cat_folder:
            stamp = str(int(time.time() * 1000000))
            cat_folder = {"children": [], "date_added": stamp, "date_last_used": "0",
                          "guid": "", "name": category_name, "type": "folder"}
            panop_folder["children"].append(cat_folder)

        # Add bookmark only if URL not already present in this folder
        if not any(c.get("url") == url for c in cat_folder.get("children", [])):
            stamp = str(int(time.time() * 1000000))
            cat_folder["children"].append({
                "date_added": stamp, "date_last_used": "0", "guid": "",
                "name": title, "type": "url", "url": url
            })
            with open(book_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            return True
    except Exception:
        pass
    return False


def send_to_zotero(url, title, abstract, category_name):
    """Posts a new item to the Zotero Web API. Requires API key + user ID in env.
    Item type is 'webpage'. Returns True on success.
    """
    env = get_env()
    api_key = env.get("zotero_api_key", "").strip()
    user_id = env.get("zotero_user_id", "").strip()
    if not api_key or not user_id:
        return False
    try:
        item = {
            "itemType": "webpage",
            "title": title,
            "url": url,
            "abstractNote": abstract or "",
            "websiteTitle": "",
            "date": datetime.now().strftime("%Y-%m-%d"),
            "tags": [{"tag": category_name}],
            "collections": [env["zotero_collection_key"]] if env.get("zotero_collection_key") else []
        }
        headers = {"Zotero-API-Key": api_key, "Content-Type": "application/json"}
        endpoint = f"https://api.zotero.org/users/{user_id}/items"
        resp = requests.post(endpoint, json=[item], headers=headers, timeout=10)
        return resp.status_code in (200, 201)
    except Exception:
        return False

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

            # Title: prefer page metadata, fall back to PDF-aware resolution, then DevTools title
            if is_pdf:
                title = get_pdf_title(url, tab.get("title", ""))
            else:
                title = (metadata or {}).get("title") or tab.get("title", "") or "Untitled"
            return (url, cat, title, metadata or {}, tab.get("id"))

        # Run up to 8 tabs in parallel — enough throughput without hammering RAM/CPU
        WORKERS = 8
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = {pool.submit(process_tab, tab, cat, needs_fetch): (tab, cat)
                       for tab, cat, needs_fetch in candidates}

            for future in as_completed(futures):
                try:
                    result = future.result()
                    if result is None:
                        continue
                    url, matched_category, title, metadata, tab_id = result

                    # Skip if another parallel worker already saved this url
                    h = load_history()
                    if url in h:
                        continue
                    
                    # PROACTIVE DEDUPLICATION: Check for title collision
                    norm = normalize_title(title)
                    existing_url = None
                    if norm not in {"", "untitled", "untitled pdf"}:
                        for u, item in h.items():
                            if normalize_title(item.get("title")) == norm:
                                existing_url = u
                                break
                    
                    if existing_url:
                        # Merge this "new" found tab into the existing history record
                        h[existing_url] = merge_entries(h[existing_url], {
                            "url": url, "title": title, "category": matched_category["name"],
                            "cat_id": matched_category["id"], "abstract": metadata.get("abstract", ""),
                            "date": datetime.now().isoformat()
                        })
                        save_history(h)
                        sweep_status["tabs_matched"] += 1
                        continue

                    safe_t = "".join([c for c in title if c.isalpha() or c.isdigit() or c == ' ']).rstrip()
                    if not safe_t: safe_t = str(int(datetime.now().timestamp()))

                    if metadata.get("text") and matched_category["id"] != "uncategorized":
                        update_ai_profile(matched_category["id"], metadata["text"])

                    d = matched_category.get("dest_folder", matched_category["name"])
                    target_dir = d if os.path.isabs(d) else os.path.join(OUTPUT_DIR(), d)
                    os.makedirs(target_dir, exist_ok=True)

                    # Save rich .json entry (replaces old .md)
                    entry_data = {
                        "url": url,
                        "canonical_url": metadata.get("canonical_url", url),
                        "title": title,
                        "category": matched_category["name"],
                        "category_id": matched_category["id"],
                        "abstract": metadata.get("abstract", ""),
                        "date_saved": datetime.now().isoformat(),
                        "source": "panop-android"
                    }
                    fname = safe_t.replace(' ', '_')[:80]  # cap filename length
                    with open(os.path.join(target_dir, f"{fname}.json"), "w", encoding="utf-8") as f:
                        json.dump(entry_data, f, indent=2, ensure_ascii=False)

                    z_ok = send_to_zotero(url, title, metadata.get("abstract", ""), matched_category["name"])
                    b_ok = add_chrome_bookmark(url, title, matched_category["name"])

                    history[url] = {
                        "title": title,
                        "category": matched_category["name"],
                        "cat_id": matched_category["id"],
                        "date": datetime.now().isoformat(),
                        "abstract": metadata.get("abstract", ""),
                        "canonical_url": metadata.get("canonical_url", url),
                        "ai_learned": False,
                        "file": os.path.join(target_dir, f"{fname}.json"),
                        "z_synced": z_ok,
                        "b_synced": b_ok
                    }
                    save_history(history)
                    sweep_status["tabs_matched"] += 1

                    # AUTO-CLEANUP: Close tab on phone ONLY if enabled AND saved to BOTH Zotero and Bookmarks
                    if env.get("close_tabs_after_save") and tab_id and z_ok and b_ok:
                        try:
                            # DevTools close endpoint: POST http://localhost:9222/json/close/[id]
                            requests.post(f"http://127.0.0.1:9222/json/close/{tab_id}", timeout=5)
                        except Exception:
                            pass

                except Exception:
                    continue

    except Exception as e:
        sweep_status["last_error"] = str(e)
    finally:
        sweep_status["running"] = False

def adb_loop():
    """Background timer loop. Waits for the configured interval FIRST,
    then sweeps. This means startup is instant — sweeps only happen on schedule
    or when the user manually clicks FETCH NOW.
    """
    while True:
        hours = get_env().get("interval_hours", 6)
        if hours < 0.1: hours = 0.1
        time.sleep(hours * 3600)  # wait first, then sweep
        run_adb_sweep()

@app.on_event("startup")
def start_background_jobs():
    import gc
    init_dirs()
    # Kill any stale panop-server siblings left from a previous crashed run
    try:
        import psutil
        me = os.getpid()
        for proc in psutil.process_iter(['pid', 'name']):
            if proc.info['name'] and 'panop-server' in proc.info['name'].lower() and proc.info['pid'] != me:
                proc.kill()
    except Exception:
        pass
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

@app.get("/api/v1/history/meta")
def get_hi_meta():
    """Lightweight endpoint: returns count + a version token.
    The UI polls this cheaply to know whether a full reload is needed."""
    h = load_history()
    return {"count": len(h), "version": hash(tuple(sorted(h.keys()))) & 0xFFFFFFFF}


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
        if u in h:
            # Also delete the associated file from disk if it exists
            file_path = h[u].get("file", "")
            if file_path and os.path.exists(file_path):
                try: os.remove(file_path)
                except Exception: pass
            del h[u]
    save_history(h)
    return {"status": "ok"}

@app.post("/api/v1/fetch_now")
def f_now(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_adb_sweep)
    return {"status": "fetching"}

enrich_status = {"running": False, "total": 0, "done": 0, "updated": 0, "last_run": None}

def run_enrich():
    """Background pass: re-fetches metadata for history entries with missing/bad titles."""
    global enrich_status
    enrich_status.update({"running": True, "done": 0, "updated": 0, "last_run": datetime.now().isoformat()})
    try:
        h = load_history()
        # Safety: back up history before any mutations
        import shutil
        hf = HISTORY_FILE()
        if os.path.exists(hf):
            shutil.copy2(hf, hf + ".bak")
        BAD = {"", "untitled", "untitled pdf", "loading..."}
        candidates = [(url, item) for url, item in h.items()
                      if (item.get("title") or "").strip().lower() in BAD]
        enrich_status["total"] = len(candidates)
        def enrich_one(args):
            url, item = args
            is_pdf = url.lower().endswith(".pdf")
            try:
                if is_pdf:
                    title = get_pdf_title(url, "")
                    canonical = url  # PDFs: don't try to canonicalize
                else:
                    meta = fetch_page_content(url)
                    title = (meta or {}).get("title", "").strip() if meta else ""
                    canonical = (meta or {}).get("canonical_url", url) if meta else url
                    # Only accept canonical if same domain (avoid auth redirect traps)
                    from urllib.parse import urlparse
                    if urlparse(canonical).netloc != urlparse(url).netloc:
                        canonical = url
                title_ok = title and title.strip().lower() not in BAD
                return (url, title if title_ok else None, canonical)
            except Exception:
                pass
            return (url, None, url)
        with ThreadPoolExecutor(max_workers=15) as pool:
            futures = {pool.submit(enrich_one, (url, item)): url for url, item in candidates}
            for future in as_completed(futures):
                enrich_status["done"] += 1
                result = future.result()
                if not result: continue
                orig_url, title, canonical = result
                if not title and canonical == orig_url: continue
                h2 = load_history()
                if orig_url not in h2: continue
                entry = h2[orig_url]
                changed = False
                if title:
                    entry["title"] = title
                    changed = True
                # Update URL key if canonicalized and not already present
                if canonical != orig_url and canonical not in h2:
                    entry["original_url"] = orig_url  # keep a breadcrumb
                    del h2[orig_url]
                    h2[canonical] = entry
                    changed = True
                if changed:
                    save_history(h2)
                    enrich_status["updated"] += 1
        
        # Autonomous cleanup pass for any remaining orphans
        m_count = consolidate_history()
        enrich_status["updated"] += m_count
    finally:
        enrich_status["running"] = False

def run_bulk_sync(sync_type=None):
    """Retries Zotero/Bookmark sync for all entries marked as unsynced."""
    h = load_history()
    changed = False
    for url, item in h.items():
        if (sync_type is None or sync_type == 'zotero') and not item.get("z_synced"):
            if send_to_zotero(url, item.get("title"), item.get("abstract"), item.get("category")):
                item["z_synced"] = True
                changed = True
        if (sync_type is None or sync_type == 'bookmark') and not item.get("b_synced"):
            if add_chrome_bookmark(url, item.get("title"), item.get("category")):
                item["b_synced"] = True
                changed = True
    if changed:
        save_history(h)

@app.post("/api/v1/history/sync")
def trigger_sync(type: str = None):
    # run in background
    threading.Thread(target=run_bulk_sync, args=(type,), daemon=True).start()
    return {"status": "started"}

@app.post("/api/v1/history/sync_single")
def sync_single(url: str, type: str):
    h = load_history()
    if url not in h: return {"status": "error", "message": "not found"}
    item = h[url]
    ok = False
    if type == 'zotero':
        ok = send_to_zotero(url, item.get("title"), item.get("abstract"), item.get("category"))
        if ok: item["z_synced"] = True
    elif type == 'bookmark':
        ok = add_chrome_bookmark(url, item.get("title"), item.get("category"))
        if ok: item["b_synced"] = True
    
    if ok:
        save_history(h)
        return {"status": "ok"}
    return {"status": "error"}

@app.post("/api/v1/history/merge")
def manual_merge():
    merged_count = consolidate_history()
    return {"status": "ok", "merged": merged_count}

@app.post("/api/v1/history/enrich")
def enrich_hi(background_tasks: BackgroundTasks):
    if enrich_status["running"]:
        return {"status": "already_running"}
    background_tasks.add_task(run_enrich)
    return {"status": "started"}

@app.get("/api/v1/history/enrich/status")
def enrich_hi_status(): return enrich_status

@app.get("/api/v1/history/duplicates")
def get_dupes():
    """Returns groups of history entries that share the same normalized title.
    Useful for spotting DOI vs. direct URL duplicates.
    """
    import re
    h = load_history()
    norm = {}
    for url, item in h.items():
        key = re.sub(r'\s+', ' ', (item.get('title') or '').lower().strip())
        if not key or key in {'untitled', 'untitled pdf'}: continue
        norm.setdefault(key, []).append({'url': url, 'title': item.get('title'), 'category': item.get('category'), 'date': item.get('date')})
    dupes = {k: v for k, v in norm.items() if len(v) > 1}
    return {'total_groups': len(dupes), 'groups': dupes}

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
