import hashlib
import uuid
import os
import requests
from config import SERVER_URL

# ─────────────────────────────────────────────
#  Hardware ID
# ─────────────────────────────────────────────
def get_hwid():
    raw = str(uuid.getnode())
    return hashlib.sha256(raw.encode()).hexdigest()[:32]

# ─────────────────────────────────────────────
#  License server communication
# ─────────────────────────────────────────────
def validate_key(key):
    hwid = get_hwid()
    try:
        r = requests.post(f"{SERVER_URL}/auth", json={"key": key, "hwid": hwid}, timeout=5)
        data = r.json()
        return data.get("success"), data.get("reason", "Unknown error")
    except:
        return False, "Could not reach license server. Check your internet."

def start_heartbeat(key):
    import time
    hwid = get_hwid()
    while True:
        try:
            r = requests.post(f"{SERVER_URL}/heartbeat", json={"key": key, "hwid": hwid}, timeout=5)
            if not r.json().get("success"):
                os._exit(0)
        except:
            pass
        time.sleep(30)

def release_key(key):
    hwid = get_hwid()
    try:
        requests.post(f"{SERVER_URL}/release", json={"key": key, "hwid": hwid}, timeout=5)
    except:
        pass
