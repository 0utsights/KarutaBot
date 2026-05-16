import json
import os

# ─────────────────────────────────────────────
#  App Branding
# ─────────────────────────────────────────────
APP_NAME       = "Aeyori"
APP_VERSION    = "1.0.0"
ADMIN_PASSWORD = "8764abc213"
LICENSED_MODE  = False

# ─────────────────────────────────────────────
#  Constants
# ─────────────────────────────────────────────
SERVER_URL        = "https://aeyori-production.up.railway.app"
CONFIG_FILE       = "config.json"
MAX_DROPS_PER_DAY = 40
DROP_COOLDOWN_MIN = 30
DROP_JITTER_MIN   = 2
DROP_JITTER_MAX   = 6
KARUTA_ID         = 646937666251915264

FULL_ACCESS_FEATURES = {
    "drop": True,
    "grab": True,
    "daily": True,
    "vote": True,
    "work": True,
    "visit": True,
    "multi_account": True,
}

DEFAULT_BLESSINGS = {
    "dexterity": False,
    "evasion": False,
    "leadership": False,
    "generosity": False,
    "empathy": False,
    "diligence": False,
}

# ─────────────────────────────────────────────
#  Glass Dark Color Theme
# ─────────────────────────────────────────────
C = {
    "bg":       "#0a0e1a",
    "bg2":      "#0f1528",
    "card":     "#111827",
    "card2":    "#1a2235",
    "border":   "#1e2d47",
    "accent":   "#00d4ff",
    "accent2":  "#0099cc",
    "accent3":  "#00ff9d",
    "glow":     "#00d4ff33",
    "green":    "#00e676",
    "red":      "#ff4569",
    "yellow":   "#ffd740",
    "text":     "#e8f0fe",
    "muted":    "#546e8a",
    "white":    "#ffffff",
    "dark":     "#070b14",
}


# ─────────────────────────────────────────────
#  Config Helpers
# ─────────────────────────────────────────────
def default_account():
    return {
        "name": "Account 1",
        "token": "",
        "channel_id": "",
        "max_drops": MAX_DROPS_PER_DAY,
        "jitter_min": DROP_JITTER_MIN,
        "jitter_max": DROP_JITTER_MAX,
        "vote_mode": "auto",  # "auto" | "semi" | "off"
        "show_browser": False,
        "visit_card_code": "",
        "visit_tag": "visit",
        "auto_burn": False,
        "enabled": True,
        "blessings": dict(DEFAULT_BLESSINGS),
        "macros": {
            "daily": True,
            "vote": True,
            "work": True,
            "drop": True,
            "grab": True,
            "visit": True,
        },
    }


def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            data = json.load(f)

        if "accounts" not in data:
            data = {"accounts": [{
                "name": "Account 1",
                "token": data.get("token", ""),
                "channel_id": data.get("channel_id", ""),
                "max_drops": data.get("max_drops", MAX_DROPS_PER_DAY),
                "jitter_min": DROP_JITTER_MIN,
                "jitter_max": DROP_JITTER_MAX,
                "enabled": True,
                "blessings": dict(DEFAULT_BLESSINGS),
            }]}

        defaults = default_account()
        default_blessings = defaults["blessings"]
        default_macros = defaults["macros"]

        for acc in data.get("accounts", []):
            blessings = acc.setdefault("blessings", {})
            for key, value in default_blessings.items():
                blessings.setdefault(key, value)

            if "macros" not in acc:
                acc["macros"] = dict(default_macros)

        return data

    return {"accounts": [default_account()]}


def save_config(data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)
