# Architecture

Panop is a two-process desktop application plus an optional browser extension.

```
┌──────────────────────────────┐        ┌───────────────────────────┐
│      Electron desktop app     │  HTTP  │     FastAPI server         │
│      (panop-gui/)             │ <────> │     (panop-server/)        │
│  • dashboard, rules, logs     │  :8000 │  • polling scheduler       │
│  • spawns the server as a     │        │  • metadata parsing        │
│    hidden subprocess          │        │  • RIS / Zotero export     │
└──────────────────────────────┘        └─────────────┬─────────────┘
                                                       │ adb + DevTools
                                                       │ localhost:9222
                                              ┌────────▼─────────┐
                                              │  Android Chrome   │
                                              │  (open tabs)      │
                                              └──────────────────┘
```

## Components

### `panop-server/` — FastAPI backend
The engine. A single `main.py` (~2.5k lines) that:
- **Schedules** capture passes on `interval_hours`.
- **Bridges** to the phone: launches a sandboxed `adb` (auto-downloaded to
  `panop_output/platform-tools/`), forwards Chrome's debugging socket, and reads open tabs
  over the DevTools protocol on `localhost:9222`.
- **Parses** each captured page with `requests`/`cloudscraper` + `BeautifulSoup`, extracting
  title, abstract, and DOI. All parsing is local — no cloud AI.
- **Deduplicates** via `panop_history.json` (canonicalized URL + DOI).
- **Learns** category routing from your corrections (`panop_ai_profiles.json`, keyword
  profiles per category).
- **Exports** grouped `.ris` batches by ISO week, and optionally pushes to the Zotero web API.

### `panop-gui/` — Electron desktop app
A thin Electron + Node wrapper (`index.js`) that renders the dashboard (`index.html`),
spawns the FastAPI server as a hidden subprocess (in packaged builds), and lets you edit
rules, trigger a manual pass, view logs, and open the output folder.

### `panop-extension/` — optional Chrome extension
A lightweight extension (`manifest.json`, `background.js`, `popup.js`) for one-tap capture
from desktop Chrome, complementing the mobile sweep.

## Data flow per pass

1. Scheduler fires (or **Run now** clicked).
2. Server lists open Chrome tabs on the phone via DevTools.
3. Tabs are filtered against your Articles/Books domain rules.
4. Each kept tab is fetched + parsed locally for metadata.
5. New (non-duplicate) entries are written to `ris/` and the history ledger.
6. The captured tabs are closed on the phone via a DevTools command.

## Privacy posture
Panop never sends your URLs, history, or tokens to any external service. The only outbound
requests are (a) the phone↔computer debugging bridge on your LAN, and (b) fetching each
captured article's own page to parse its metadata. See the README's *Security & Privacy*
section.
