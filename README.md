<p align='center'>
  <img src='assets/logo.svg' width='250'>
</p>

# Panop: Automated Mobile Knowledge Management System

Panop is a completely local, zero-cloud knowledge capture pipeline. It connects directly to your Android Chrome session via USB or Wi-Fi (ADB remote debugging) and intelligently sweeps, categorizes, and organizes your academic articles and books into Zotero-ready formats.

## Features
- **Auto-Close Magic:** When Panop captures an academic tab from your Android device, it automatically executes a DevTools command to silently shut down the tab on your phone, keeping your mobile browser permanently clean.
- **Wireless Wi-Fi Syncing:** Works seamlessly over standard USB cords, or securely across recognized Wi-Fi networks by simply typing your phone's Wireless Debugging IP Address straight into the Panop UI.
- **Zero-Configuration Setup:** Panop automatically downloads and sandboxes Google's Android Platform Tools (`adb`). No global SDK installations or command-line fiddling required by the user.
- **Smart Routing:** Define custom academic and literature domains for "Articles" vs "Books". Panop generates detailed Markdown bookmarks containing parsed abstract data.
- **Zotero Integration:** Generates grouped `.ris` batches automatically bucketed by ISO week (e.g. `articles_week_43.ris`).

## Architecture
- **Backend:** Python (FastAPI + BeautifulSoup) driving Android Debug Bridge (`adb`) protocols to query live Chrome tabs over `localhost:9222`.
- **Application:** Electron + NodeJS wrapper providing a sleek aesthetic dashboard to customize rules, ping the server, view logs, and natively export output directories. The FastAPI engine runs entirely invisibly as a packaged subprocess.

## ðŸ” Security & Privacy
Panop connects to your phone using Android's native cryptographic RSA handshake. All metadata parsing occurs locally on your machine using `BeautifulSoup`â€”not via cloud AI endpoints. No URLs, history, or tokens are ever sent to external networks.

##  Usage
Launch the executable and allow it to sit in the background. It polls Android on a hardcoded 6-hour interval, ripping closed parsed tabs and securely updating your Zotero output folders.


