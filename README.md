<div align="center">

# Aeyori

**Open source automation bot for the Discord card game Karuta.**

[![Python](https://img.shields.io/badge/Python-3.11+-blue?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)
[![Discord](https://img.shields.io/badge/Karuta-Automation-7289da?style=flat-square&logo=discord&logoColor=white)](https://aeyori.com)

[**aeyori.com**](https://aeyori.com) — want a pre-packaged Windows exe with a user dashboard? Get it there, free.

</div>

---

## What It Does

Aeyori automates the repetitive parts of Karuta so you can focus on the parts you actually enjoy.

- **Auto drop & grab** — drops cards on a timer and grabs any card matching your wishlist using real-time OCR
- **Wishlist detection** — looks up wish counts via `k!lu` and only grabs cards people actually want
- **Auto daily / quiz** — claims your daily reward and answers the quiz automatically
- **Auto work & visit** — runs work and shrine visit commands on cooldown
- **Auto vote** — completes the Karuta voting flow via headless browser
- **Multi-account** — run multiple Discord accounts simultaneously, each with their own settings
- **Burn tagging** — automatically tags low-value cards for burning

---

## Requirements

- Python 3.11 or higher
- Windows (the bot automates Discord — Linux/Mac support is limited, however does work)
- A Discord account that plays Karuta
- Your Discord token (see below)

---

## Installation

**1. Clone the repo**
```bash
git clone https://github.com/0utsights/aeyori-bot.git
cd aeyori-bot
```

**2. Create a virtual environment**
```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux / Mac
source venv/bin/activate
```

**3. Install dependencies**
```bash
pip install -r requirements.txt
```

> ⚠️ EasyOCR and PyTorch are large installs (~1GB). This will take a few minutes on first run.

**4. Run the app**
```bash
python KarutaBot/main.py
```

---

## Getting Your Discord Token

(instructions on this can also be found in the app, if you need help don't hesitate to reach out to me on discord through my github profile)

1. Open Discord in your **browser** (not the desktop app)
2. Press `F12` to open DevTools → go to the **Console** tab
3. Paste this and press Enter:
```js
(webpackChunkdiscord_app.push([[''],{},e=>{m=[];for(let c in e.c)m.push(e.c[c])}]),m).find(m=>m?.exports?.default?.getToken!==void 0).exports.default.getToken()
```
4. Copy the token that appears — paste it into the Aeyori token field

---

## Configuration

On first launch a `config.json` is created in the same directory. You can edit this directly or use the in-app settings panel.

Key settings per account:

| Setting | Description |
|---|---|
| `token` | Your Discord token |
| `channel_id` | The channel ID where you play Karuta |
| `max_drops` | Max drops per day (default: 40) |
| `vote_mode` | `auto`, `semi`, or `off` |
| `auto_burn` | Automatically burn low-value cards |
| `macros` | Toggle individual automations on/off |

---

## Packaging as a Windows Exe

If you want a single portable `.exe` file instead of running from source:

**1. Install PyInstaller**
```bash
pip install pyinstaller
```

**2. Build**
```bash
pyinstaller --onefile --noconsole --name "Aeyori" --icon=KarutaBot/icon.ico --collect-all easyocr --collect-all torch KarutaBot/launcher.py
```

> ⚠️ The build will take several minutes and the output exe will be ~250MB due to PyTorch being bundled.

**3. Find your exe**
```
dist/Aeyori.exe
```

Windows will show a SmartScreen warning on first launch since the exe is unsigned — click **More info → Run anyway**. This is expected for unsigned indie software.

---

## How OCR Works

When Karuta drops cards, Aeyori:

1. Downloads the drop image from Discord
2. Crops each card into name, series, and print number regions
3. Runs EasyOCR on each region to extract text
4. Cleans OCR noise with regex (fixes stray caps, missing spaces, border artifacts)
5. Sends `k!lu <name>` to look up wish counts
6. If multiple results come back, fuzzy-matches against the detected series name
7. Grabs the card with the highest wish count — skips if no wishlist matches

---

## Project Structure

```
KarutaBot/
├── main.py        — entry point, launches the GUI
├── gui.py         — main window, account panels, settings
├── bot.py         — Discord automation loop, drop/grab/daily logic
├── ocr.py         — EasyOCR card image parser
├── vote.py        — Selenium voting automation
├── session.py     — session tracking
├── config.py      — constants, config load/save
├── launcher.py    — PyInstaller entry point with dependency installer
└── icon.ico       — app icon
requirements.txt
```

---

## Want the Managed Version?

If you don't want to deal with Python and just want a working `.exe` with automatic updates, a user dashboard, and session tracking — that's [aeyori.com](https://aeyori.com). Free tier available.

---

## Disclaimer

Aeyori automates a user account (selfbot), which is against Discord's Terms of Service. Use at your own risk. The authors are not responsible for any account actions taken by Discord.

---

## License

MIT — do whatever you want with it.
