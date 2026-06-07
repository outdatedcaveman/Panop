# Troubleshooting

## The server won't start

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError` on launch | Run `pip install -r requirements.txt` inside `panop-server/` |
| `[Errno 10048] address already in use` | Port 8000 is taken. Change `port` in `panop_config.json`, or stop the other process |
| `python` not recognized | Python isn't on PATH. Reinstall Python and tick *"Add Python to PATH"* |

## The desktop app shows "server offline"

1. Confirm the server window is running and printed `Uvicorn running on http://127.0.0.1:8000`.
2. Make sure the app's port matches the server's `port` setting.
3. If you launched the packaged executable, the bundled server may have failed to start —
   run the standalone server (above) in a terminal to see the error.

## My phone connects but nothing is captured

- **No matching rules.** Panop only captures tabs whose URL matches an Articles/Books
  domain rule. Add the domains you read from, or set `strict_domain_scan: false`.
- **No academic tabs open.** Panop reads *currently open* Chrome tabs. Open a few article
  pages on the phone and click **Run now**.
- **Already captured.** Panop dedupes against `panop_history.json` — a tab captured before
  won't be captured again. Check the output folder for an existing entry.

## Tabs are read but not closed on the phone

- Bring **Chrome to the foreground** on the phone during a pass.
- Some Android OEM battery managers suspend Chrome's debugging socket — disable battery
  optimization for Chrome.

## RIS imports look incomplete in Zotero

- Panop parses metadata from the page; paywalled or JS-only pages may expose little. The
  DOI is captured when present, so re-running Zotero's *"Find Available PDF"* / metadata
  retrieval after import usually fills the gaps.

## Where are my files?

Everything is under `root_dir` (default `panop_output/`). RIS batches are in
`panop_output/ris/`. If you set `root_dir` to a cloud-synced folder, look there.

## Still stuck?

Open an issue at <https://github.com/outdatedcaveman/Panop/issues> with:
- your OS and Python/Node versions,
- the server terminal output,
- whether the phone shows as `device` under `adb devices` (see [ADB_PAIRING.md](ADB_PAIRING.md)).
