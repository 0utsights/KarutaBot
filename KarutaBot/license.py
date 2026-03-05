import requests
from config import SERVER_URL

# ─────────────────────────────────────────────
#  License validation against Aeyori API
# ─────────────────────────────────────────────

def validate_key(key):
    """Validate license key against Aeyori API. Returns (success, reason, features)."""
    try:
        r = requests.get(f"{SERVER_URL}/api/keys/validate/{key.strip()}", timeout=5)
        data = r.json()
        if r.status_code == 200 and data.get("valid"):
            return True, "OK", data.get("features", {})
        return False, data.get("detail", "Invalid key"), {}
    except Exception as e:
        return False, f"Error: {str(e)}", {}


def start_heartbeat(key):
    """Periodically re-validate the key. Exit if it becomes invalid."""
    import time
    while True:
        time.sleep(60)
        try:
            r = requests.get(f"{SERVER_URL}/api/keys/validate/{key.strip()}", timeout=5)
            if r.status_code != 200:
                import os
                os._exit(0)
        except:
            pass


def release_key(key):
    """No-op for new system — keys aren't session-locked."""
    pass
