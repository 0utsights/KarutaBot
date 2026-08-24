# Aeyori

Aeyori is an open-source, user-operated workflow client for experimenting with
OCR, scheduling, and configurable routines around the Discord card game Karuta.
It is a personal project, not an official Karuta or Discord product.

> [!IMPORTANT]
> Aeyori automates a Discord user account. Discord prohibits self-bots and other
> user-account automation, and Karuta may apply additional rules or penalties.
> Using Aeyori on a live account can lead to restrictions or a permanent ban.
> There is no "undetectable" mode and no guarantee of account safety.

The complete client is free. Optional support for the project does not unlock
automation features or provide a gameplay advantage.

## Project goals

- Keep the implementation inspectable and locally operated.
- Make each workflow independently configurable and easy to stop.
- Explore OCR-assisted classification and cooldown-aware scheduling.
- Document platform risk instead of making anti-detection claims.
- Keep functional access separate from optional financial support.

## Current experiments

- Card-image OCR and wishlist-assisted review
- User-configured drop and grab routines
- Daily, work, visit, and vote workflow scheduling
- Independent local profiles and activity logs
- Conservative retry, cooldown, and stop controls

These descriptions explain what the software does; they are not a promise that
the workflows comply with Discord, Karuta, top.gg, or any other service.

## Before running it

Read [SAFETY.md](SAFETY.md). In particular:

- Use a separate test account only if the relevant services permit it.
- Never share or commit a Discord token. Treat it like a password.
- Keep credentials in the local configuration created by the application.
- Start with one workflow, observe it, and use the stop control if behavior is
  unexpected.
- Do not use Aeyori to harass users, overwhelm services, evade enforcement, or
  bypass access controls.

## Run from source

Requirements:

- Python 3.11 or newer
- Windows is the best-tested platform
- Roughly 1 GB of free space for EasyOCR and PyTorch dependencies

```bash
git clone https://github.com/0utsights/KarutaBot.git
cd KarutaBot
python -m venv venv
```

Activate the environment:

```powershell
# Windows
.\venv\Scripts\Activate.ps1
```

```bash
# Linux or macOS
source venv/bin/activate
```

Then install and run:

```bash
pip install -r requirements.txt
python KarutaBot/main.py
```

The application creates a local `config.json` on first launch. Aeyori needs
user-supplied Discord credentials because it operates as a user-account client.
The repository intentionally does not provide instructions for extracting tokens
from browser traffic. If you choose to proceed, do not paste a token into support
messages, screenshots, issue reports, or source control.

## Configuration

| Setting | Purpose |
| --- | --- |
| `token` | Sensitive local Discord credential; never share it |
| `channel_id` | Channel selected for the user-controlled workflow |
| `max_drops` | User-defined daily action ceiling |
| `vote_mode` | `auto`, `semi`, or `off` |
| `auto_burn` | Optional low-value-card tagging workflow |
| `macros` | Independent switches for each routine |

## Build a Windows executable

```bash
pip install pyinstaller
pyinstaller --onefile --noconsole --name "Aeyori" \
  --icon=KarutaBot/icon.ico \
  --collect-all easyocr --collect-all torch \
  KarutaBot/launcher.py
```

The generated executable is written to `dist/Aeyori.exe`. PyTorch and OCR make
the binary large. A Windows reputation warning is not proof that a file is safe;
prefer a release published by this repository and verify its SHA-256 digest when
one is provided.

## Architecture

```text
KarutaBot/
├── main.py       application entry point
├── gui.py        local controls, profiles, and activity display
├── bot.py        workflow coordination and cooldown handling
├── ocr.py        local card-image OCR pipeline
├── vote.py       optional browser-assisted vote workflow
├── config.py     defaults and local configuration
└── launcher.py   packaged application entry point
```

## Responsible contributions

Changes that improve transparency, credential handling, stop controls,
observability, testability, and conservative defaults are welcome. Contributions
whose main purpose is detection evasion, CAPTCHA bypass, rate-limit bypass, or
concealing automated behavior are out of scope.

## Availability and support

- Source and functional features: free
- Managed download and dashboard: [aeyori.com](https://aeyori.com)
- Optional supporter benefits: cosmetic and community recognition only

See [SAFETY.md](SAFETY.md) for the full risk statement.
