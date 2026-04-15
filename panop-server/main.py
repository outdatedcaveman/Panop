import os
import json
import rispy
from fastapi import FastAPI, Request
from pydantic import BaseModel
from typing import Optional
from bs4 import BeautifulSoup
import requests
from datetime import datetime

app = FastAPI(title="Panop Backend Server")

class TabData(BaseModel):
    url: str
    title: str
    timestamp: str
    is_pdf: bool

# Output directories
OUTPUT_DIR = "panop_output"
RIS_DIR = os.path.join(OUTPUT_DIR, "ris")
ARTICLES_DIR = os.path.join(OUTPUT_DIR, "Android Articles")
BOOKS_DIR = os.path.join(OUTPUT_DIR, "Android Books")
CONFIG_FILE = os.path.join(OUTPUT_DIR, "panop_config.json")
HISTORY_FILE = os.path.join(OUTPUT_DIR, "panop_history.json")

os.makedirs(RIS_DIR, exist_ok=True)
os.makedirs(ARTICLES_DIR, exist_ok=True)
os.makedirs(BOOKS_DIR, exist_ok=True)

# Default Config
DEFAULT_CONFIG = {
    "articles_domains": ["arxiv.org", "nature.com", "sciencedirect.com", "ncbi.nlm.nih.gov", "springer.com", "ieeexplore.ieee.org"],
    "books_domains": ["goodreads.com", "amazon.com", "libgen.is", "gutenberg.org"],
    "rules": {
        "trust_all_pdfs": True,
        "strict_mode": False
    }
}

def load_config():
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w") as f:
            json.dump(DEFAULT_CONFIG, f, indent=4)
        return DEFAULT_CONFIG
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)

def load_history():
    if not os.path.exists(HISTORY_FILE):
        return {}
    with open(HISTORY_FILE, "r") as f:
        return json.load(f)

def save_history(history):
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=4)

def get_current_week_ris_path(category="articles"):
    # Group by ISO week (e.g., week_43.ris)
    week_num = datetime.now().isocalendar()[1]
    return os.path.join(RIS_DIR, f"{category}_week_{week_num}.ris")

def extract_metadata(url: str):
    metadata = {"title": "", "authors": [], "journal": "", "year": "", "doi": "", "abstract": ""}
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            title_tag = soup.find("meta", {"name": "citation_title"})
            metadata["title"] = title_tag.get("content", "") if title_tag else (soup.title.string if soup.title else "")
            metadata["authors"] = [tag.get("content", "") for tag in soup.find_all("meta", {"name": "citation_author"})]
            j_tag = soup.find("meta", {"name": "citation_journal_title"})
            if j_tag: metadata["journal"] = j_tag.get("content", "")
            d_tag = soup.find("meta", {"name": "citation_publication_date"})
            if d_tag: metadata["year"] = d_tag.get("content", "")[:4]
            doi_tag = soup.find("meta", {"name": "citation_doi"})
            if doi_tag: metadata["doi"] = doi_tag.get("content", "")
            ab_tag = soup.find("meta", {"name": "citation_abstract"}) or soup.find("meta", {"name": "description"})
            if ab_tag: metadata["abstract"] = ab_tag.get("content", "")
    except Exception as e:
        pass
    return metadata

@app.post("/api/v1/process-tab")
def process_tab(data: TabData):
    history = load_history()
    # 1. Deduplication ID
    if data.url in history:
        return {"status": "ignored", "reason": "Already processed"}
        
    config = load_config()
    url_lower = data.url.lower()

    # 2. Categorization Logic
    is_article = any(d in url_lower for d in config["articles_domains"])
    is_book = any(d in url_lower for d in config["books_domains"])
    is_pdf = data.is_pdf and config["rules"].get("trust_all_pdfs", True)
    
    category = None
    if is_article or is_pdf:
        category = "articles"
    elif is_book:
        category = "books"
        
    if not category:
        return {"status": "ignored", "reason": "Domain not tracked"}
        
    print(f"Captured new {category}: {data.url}")
    
    # 3. Pull Metadata
    metadata = extract_metadata(data.url) if not data.is_pdf else {}
    title = metadata.get("title") or data.title or "Untitled"
    safe_title = "".join([c for c in title if c.isalpha() or c.isdigit() or c==' ']).rstrip()
    if not safe_title: safe_title = str(int(datetime.now().timestamp()))
    
    # 4. Save Bookmark Markdown
    target_dir = ARTICLES_DIR if category == "articles" else BOOKS_DIR
    bm_file = os.path.join(target_dir, f"{safe_title.replace(' ', '_')}.md")
    
    with open(bm_file, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n**URL:** {data.url}\n**Captured:** {data.timestamp}\n**Category:** {category}\n")
        if metadata.get("abstract"):
            f.write(f"\n## Abstract\n{metadata['abstract']}\n")

    # 5. Append to Weekly .RIS Batch
    ris_path = get_current_week_ris_path(category)
    entry = {"type_of_reference": "JOUR" if category == "articles" else "BOOK", "title": title, "url": data.url}
    if metadata["authors"]: entry["authors"] = metadata["authors"]
    if metadata["journal"]: entry["journal_name"] = metadata["journal"]
    if metadata["year"]: entry["year"] = metadata["year"]
    if metadata["doi"]: entry["doi"] = metadata["doi"]
    if metadata["abstract"]: entry["abstract"] = metadata["abstract"]
    
    # Read existing appended RIS or create new list
    entries = []
    if os.path.exists(ris_path):
        with open(ris_path, "r", encoding="utf-8") as f:
            try: entries = rispy.load(f)
            except: pass
    entries.append(entry)
    with open(ris_path, "w", encoding="utf-8") as f:
        rispy.dump(entries, f)

    # 6. Mark as Processed safely mapping history stats
    history[data.url] = {"title": title, "category": category, "date": data.timestamp}
    save_history(history)
    
    return {"status": "success", "category": category}

# Mount point just for the GUI to fetch live history and configs dynamically
@app.get("/api/v1/config")
def get_config(): return load_config()

@app.post("/api/v1/config")
def update_config(req_data: dict):
    with open(CONFIG_FILE, "w") as f:
        json.dump(req_data, f, indent=4)
    return {"status": "updated"}

@app.get("/api/v1/history")
def get_history(): return load_history()

if __name__ == "__main__":
    import uvicorn
    import multiprocessing
    multiprocessing.freeze_support()
    uvicorn.run(app, host="0.0.0.0", port=8000)
