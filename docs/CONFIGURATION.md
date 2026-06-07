# Configuration

Panop stores its settings in `panop_config.json` inside your output directory (default
`panop_output/`). You can edit most of these from the desktop app's settings panel; the
table below documents every field for reference.

| Setting | Default | What it does |
|---|---|---|
| `root_dir` | `panop_output` | Where Panop writes everything (RIS batches, history, downloaded `adb`). Point this at a Google Drive folder for automatic cloud backup. |
| `interval_hours` | `6` | How often Panop polls the phone for new tabs. |
| `port` | `8000` | Port the local server listens on. |
| `bookmark_folder` | `Panop` | Name of the Chrome bookmark folder Panop reads/writes. |
| `catch_uncategorized` | `false` | If `true`, capture matching tabs even when no Article/Book rule matches, into an "uncategorized" bucket. |
| `strict_domain_scan` | `true` | Require a domain-rule match before capturing a tab. Turn off to capture more aggressively. |
| `zotero_api_key` | `""` | Optional — enables direct push to Zotero's web API instead of `.ris` export. |
| `zotero_user_id` | `""` | Your Zotero numeric user ID (from your Zotero settings page). |
| `zotero_collection_key` | `""` | Optional — target a specific Zotero collection. |

## Output layout

```
panop_output/
├── ris/                       # articles_week_NN.ris, books_week_NN.ris
├── exports/                   # generated Markdown bookmark files
├── platform-tools/            # auto-downloaded Android adb (sandboxed)
├── panop_config.json          # your settings
├── panop_history.json         # dedup ledger (what's already been captured)
└── panop_ai_profiles.json     # learned category profiles
```

## Categories & domain rules

Each category has a list of domains. A tab is captured when its host matches a domain in
an **Articles** or **Books** category. Examples:

- **Articles:** `arxiv.org`, `nature.com`, `sciencedirect.com`, `link.springer.com`, `ieeexplore.ieee.org`
- **Books:** `books.google.com`, `archive.org`, `annas-archive.org`

Panop also learns from your corrections: when you re-categorize a captured item, it updates
a lightweight keyword profile (`panop_ai_profiles.json`) so similar tabs route better next time.

## Cloud backup

Because everything lives under `root_dir`, the simplest backup is to set `root_dir` to a
path inside your Google Drive / Dropbox / OneDrive folder, e.g.
`C:\Users\you\My Drive\Panop`. Panop's history and outputs then sync automatically.
