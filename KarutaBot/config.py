import json
import os

# ─────────────────────────────────────────────
#  Constants
# ─────────────────────────────────────────────
SERVER_URL        = "https://karutabot-production.up.railway.app"
CONFIG_FILE       = "config.json"
MAX_DROPS_PER_DAY = 40
DROP_COOLDOWN_MIN = 30
DROP_JITTER_MAX   = 6
KARUTA_ID         = 646937666251915264

# ─────────────────────────────────────────────
#  Color theme
# ─────────────────────────────────────────────
C = {
    "bg":      "#2b2d31",
    "card":    "#313338",
    "dark":    "#1e1f22",
    "accent":  "#5865f2",
    "accent2": "#4752c4",
    "green":   "#23a55a",
    "red":     "#f23f43",
    "yellow":  "#f0b232",
    "text":    "#dbdee1",
    "muted":   "#949ba4",
    "white":   "#ffffff",
}

# ─────────────────────────────────────────────
#  Config file helpers
# ─────────────────────────────────────────────
def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {"token": "", "channel_id": "", "max_drops": MAX_DROPS_PER_DAY}

def save_config(data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f)
