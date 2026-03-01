import json
import os

# ─────────────────────────────────────────────
#  App branding
# ─────────────────────────────────────────────
APP_NAME          = "Aeyori"
APP_VERSION       = "1.0.0"

# ─────────────────────────────────────────────
#  Constants
# ─────────────────────────────────────────────
SERVER_URL        = "https://karutabot-production.up.railway.app"
CONFIG_FILE       = "config.json"
MAX_DROPS_PER_DAY = 40
DROP_COOLDOWN_MIN = 30
DROP_JITTER_MIN   = 2
DROP_JITTER_MAX   = 6
KARUTA_ID         = 646937666251915264

# ─────────────────────────────────────────────
#  Glass dark color theme
# ─────────────────────────────────────────────
C = {
    "bg":       "#0a0e1a",       # deep navy background
    "bg2":      "#0f1528",       # slightly lighter bg
    "card":     "#111827",       # glass card base
    "card2":    "#1a2235",       # elevated card
    "border":   "#1e2d47",       # subtle border
    "accent":   "#00d4ff",       # cyan accent
    "accent2":  "#0099cc",       # darker cyan
    "accent3":  "#00ff9d",       # green accent
    "glow":     "#00d4ff33",     # accent glow (transparent)
    "green":    "#00e676",
    "red":      "#ff4569",
    "yellow":   "#ffd740",
    "text":     "#e8f0fe",
    "muted":    "#546e8a",
    "white":    "#ffffff",
    "dark":     "#070b14",
}

# ─────────────────────────────────────────────
#  Config helpers — supports multiple accounts
# ─────────────────────────────────────────────
def default_account():
    return {
        "name":       "Account 1",
        "token":      "",
        "channel_id": "",
        "max_drops":  MAX_DROPS_PER_DAY,
        "jitter_min":  DROP_JITTER_MIN,
        "jitter_max":  DROP_JITTER_MAX,
        "vote_mode":  "auto",       # "auto" | "semi" | "off"
        "enabled":    True,
    }

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            data = json.load(f)
        # Migrate old single-account format
        if "accounts" not in data:
            data = {"accounts": [{
                "name":       "Account 1",
                "token":      data.get("token", ""),
                "channel_id": data.get("channel_id", ""),
                "max_drops":  data.get("max_drops", MAX_DROPS_PER_DAY),
                "jitter_min":  DROP_JITTER_MIN,
                "jitter_max":  DROP_JITTER_MAX,
                "enabled":    True,
            }]}
        return data
    return {"accounts": [default_account()]}

def save_config(data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)
