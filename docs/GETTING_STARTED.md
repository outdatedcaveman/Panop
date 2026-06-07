# Getting started with Panop

This guide takes you from zero to your first captured batch of references. No prior
command-line experience is assumed beyond installing Python and Node once.

## 1. What you need

| Requirement | Why | Where |
|---|---|---|
| **Python 3.10+** | Runs the capture server | [python.org/downloads](https://www.python.org/downloads/) — tick *"Add Python to PATH"* during install |
| **Node.js 18+** | Runs the desktop app | [nodejs.org](https://nodejs.org/) (LTS) |
| **An Android phone** | The source of tabs | Any modern Android with Chrome |

You do **not** need to install the Android SDK or `adb` yourself — Panop downloads a
sandboxed copy automatically the first time it needs it.

## 2. Enable debugging on your phone

Panop reads your open Chrome tabs through Android's official debugging bridge. You
enable it once:

1. Open **Settings → About phone** and tap **Build number** seven times to unlock
   *Developer options*.
2. Go to **Settings → System → Developer options**.
3. Turn on **USB debugging** (for cable) and/or **Wireless debugging** (for Wi-Fi).
4. In **Chrome on the phone**, open `chrome://flags`, search for *"Enable command line on
   non-rooted devices"* is **not** needed — Panop uses the standard DevTools protocol, which
   is on by default once USB/Wireless debugging is enabled.

> **First connection always over USB.** Even if you plan to use Wi-Fi, connect the cable
> once and accept the *"Allow USB debugging?"* prompt (tick *"Always allow from this
> computer"*). That stores the RSA key pair so future wireless connections are trusted.

## 3. Start Panop

Panop is two pieces: a **server** (does the work) and a **desktop app** (the dashboard).
Start the server first.

### Server

```powershell
cd panop-server
pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Leave that window open. On Windows you can instead double-click `panop-server/start.bat`.

### Desktop app

In a second terminal:

```powershell
cd panop-gui
npm install
npm start
```

The Panop window opens. (If you downloaded a packaged build from
[Releases](https://github.com/outdatedcaveman/Panop/releases), just run the executable —
it launches the server for you.)

## 4. Connect your phone

- **USB:** plug in the cable. Panop shows *"Device connected"* within a few seconds.
- **Wi-Fi:** on the phone, open **Developer options → Wireless debugging** and note the
  **IP address & port** shown there. Type that IP into the Panop UI's connection field and
  click **Connect**. Phone and computer must be on the same network.

See **[ADB_PAIRING.md](ADB_PAIRING.md)** if the device doesn't show up.

## 5. Define your categories

In the dashboard, set the domains that count as **Articles** vs **Books** (e.g.
`arxiv.org`, `nature.com`, `link.springer.com` for articles). Panop only captures tabs whose
URL matches a rule, so nothing unrelated gets swept up.

## 6. Capture

Panop polls your phone on a 6-hour interval by default (configurable — see
[CONFIGURATION.md](CONFIGURATION.md)). On each pass it:

1. Reads the open Chrome tabs over the debugging bridge.
2. Keeps the ones matching your Article/Book rules, parses their metadata.
3. Silently closes those tabs on the phone (keeping your mobile browser clean).
4. Writes grouped `.ris` batches into your output folder, bucketed by ISO week.

To force a pass without waiting, click **Run now** in the dashboard.

## 7. Import into Zotero

In Zotero: **File → Import…** and select the latest `articles_week_NN.ris` from your output
folder (default `panop_output/ris/`). Your references appear with parsed metadata attached.

---

Next: **[CONFIGURATION.md](CONFIGURATION.md)** · **[ADB_PAIRING.md](ADB_PAIRING.md)** · **[TROUBLESHOOTING.md](TROUBLESHOOTING.md)**
