"""
license.py — Key validation, heartbeat, and session management.

After a successful validate_key() call, the resolved tier and feature-set
are stored in module-level globals so any part of the app can query them
via get_tier() / get_features() without re-hitting the network.
"""

import time
import uuid

import requests

from config import SERVER_URL

# ── Module-level session state ───────────────────────────
_active_key: str | None = None
_tier:       str | None = None
_features:   dict       = {}


# ── Public accessors ─────────────────────────────────────
def get_tier() -> str | None:
    return _tier


def get_features() -> dict:
    """Return the feature dict for the current tier, e.g.:
    semi: {"drop": True, "grab": True, "daily": False, ..., "multi_account": False}
    full: {"drop": True, "grab": True, "daily": True,  ..., "multi_account": True}
    Falls back to an empty dict if no key has been validated yet.
    """
    return dict(_features)


def feature_allowed(name: str) -> bool:
    """Convenience helper — returns True if the current tier includes `name`."""
    return bool(_features.get(name, False))


# ── Key validation ───────────────────────────────────────
def validate_key(key: str) -> tuple[bool, str, dict]:
    """Hit /api/keys/validate/<key> on the Aeyori API.

    Returns (success, reason, features).
    On success also writes the tier + features into module globals.
    """
    global _active_key, _tier, _features

    try:
        r = requests.get(
            f"{SERVER_URL}/api/keys/validate/{key.upper().strip()}",
            timeout=8,
        )
        data = r.json()
    except Exception as e:
        return False, f"Could not reach server: {e}", {}

    if r.status_code != 200 or not data.get("valid"):
        reason = data.get("detail", "Invalid or expired key")
        return False, reason, {}

    # ── Store session state ──────────────────────────────
    _active_key = key.upper().strip()
    _tier       = data.get("tier", "semi")
    _features   = data.get("features", {})

    return True, "OK", dict(_features)


# ── Heartbeat ────────────────────────────────────────────
def start_heartbeat(key: str, interval: int = 60) -> None:
    """Re-validates the key every `interval` seconds from a daemon thread.
    If the server returns non-200 (key revoked, expired, etc.) the process
    is killed immediately via os._exit so there's no way to keep running
    on a bad key even if the UI is already open.
    Network errors are ignored so a brief connection blip won't kill the app.
    """
    import os
    while True:
        time.sleep(interval)
        try:
            r = requests.get(
                f"{SERVER_URL}/api/keys/validate/{key.upper().strip()}",
                timeout=8,
            )
            if r.status_code != 200:
                os._exit(0)
        except Exception:
            pass  # network blip — keep trying, don't kill on connectivity loss


# ── Session release ──────────────────────────────────────
def release_key(key: str) -> None:
    """No-op — the Aeyori API is stateless; keys aren't session-locked."""
    pass


# ── HWID helper ──────────────────────────────────────────
def _get_hwid() -> str:
    """Stable per-machine identifier derived from the MAC address."""
    return str(uuid.getnode())
