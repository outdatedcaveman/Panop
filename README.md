<p align='center'>
  <img src='assets/logo.svg' width='250'>
</p>

# Panop: Automated Mobile Knowledge Management System

Panop is a completely local, zero-cloud knowledge capture pipeline. It connects directly to your Android Chrome session via USB or Wi-Fi (ADB remote debugging) and intelligently sweeps, categorizes, and organizes your academic articles and books into Zotero-ready formats.

## Features
- **Auto-Close Magic:** When Panop captures an academic tab from your Android device, it automatically executes a DevTools command to silently shut down the tab on your phone, keeping your mobile browser permanently clean.
- **Wireless Wi-Fi Syncing:** Works seamlessly over standard USB cords, or securely across recognized Wi-Fi networks by simply typing your phone's Wireless Debugging IP address straight into the Panop UI.
- **Zero-Configuration Setup:** Panop automatically downloads and sandboxes Google's Android Platform Tools (`adb`). No global SDK installations or command-line fiddling required.
- **Smart Routing:** Define custom academic and literature domains for "Articles" vs "Books". Panop generates detailed Markdown bookmarks containing parsed abstract data.
- **Zotero Integration:** Generates grouped `.ris` batches automatically bucketed by ISO week (e.g. `articles_week_43.ris`).

## Architecture
- **Backend:** Python (FastAPI + BeautifulSoup) driving Android Debug Bridge (`adb`) protocols to query live Chrome tabs over `localhost:9222`.
- **Application:** Electron + Node.js wrapper providing a dashboard to customize rules, ping the server, view logs, and export output directories. The FastAPI engine runs entirely invisibly as a packaged subprocess.
- **Browser extension:** An optional Chrome extension (`panop-extension/`) for one-tap capture.

## Requirements
- **Python 3.10+** (backend server)
- **Node.js 18+** (Electron desktop app)
- An **Android device** with [USB or Wireless debugging](https://developer.android.com/tools/adb) enabled

## Install & run

Panop has two parts — a Python server and an Electron GUI. Run the server first, then launch the GUI.

### 1. Backend server

```powershell
cd panop-server
pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

(On Windows you can just double-click `panop-server/start.bat`.)

### 2. Desktop app

```powershell
cd panop-gui
npm install
npm start
```

### 3. Connect your phone
- **USB:** plug in your Android device and accept the debugging prompt.
- **Wi-Fi:** enable Wireless Debugging on your phone and enter its IP address in the Panop UI.

## Security & Privacy
Panop connects to your phone using Android's native cryptographic RSA handshake. All metadata parsing occurs locally on your machine using `BeautifulSoup` — not via cloud AI endpoints. No URLs, history, or tokens are ever sent to external networks.

## Usage
Launch the app and allow it to sit in the background. It polls Android on a 6-hour interval, capturing and closing parsed tabs and updating your Zotero output folders.

## License
MIT — see [LICENSE](LICENSE).
