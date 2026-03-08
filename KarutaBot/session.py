"""
session.py — Aeyori session reporting

Called by gui.py when a bot session starts and stops.
Posts to the Aeyori API so the dashboard stats stay current.
Uses the same HttpOnly cookie auth as the web frontend (Bearer token
sent via Authorization header using the active license key as identity).
"""

import threading
import requests
import license
from config import SERVER_URL


# Tracks active session IDs per account name so stop() knows what to close
_sessions: dict[str, str] = {}
_lock = threading.Lock()


def _headers() -> dict:
    """Use the active license key as a bearer token for bot → API calls."""
    key = license._active_key   # access at call time, not import time
    if key:
        return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    return {"Content-Type": "application/json"}


def start(account_name: str) -> str | None:
    try:
        res = requests.post(
            f"{SERVER_URL}/api/sessions/start",
            json={"account_name": account_name, "tier": license.get_tier() or "semi"},
            headers=_headers(),
            timeout=8,
        )
        if res.status_code == 200:
            session_id = res.json().get("session_id")
            if session_id:
                with _lock:
                    _sessions[account_name] = session_id
                print(f"[session] Started: {session_id}")
            return session_id
        else:
            print(f"[session] start failed: {res.status_code} {res.text}")
    except Exception as e:
        print(f"[session] start error: {e}")
    return None


def end(account_name: str, drops_done: int, cards_grabbed: int) -> None:
    with _lock:
        session_id = _sessions.pop(account_name, None)
    if not session_id:
        print(f"[session] end called but no session_id for '{account_name}' — was start() called?")
        return
    try:
        res = requests.post(
            f"{SERVER_URL}/api/sessions/end",
            json={
                "session_id": session_id,
                "drops_done": drops_done,
                "cards_grabbed": cards_grabbed,
            },
            headers=_headers(),
            timeout=8,
        )
        if res.status_code == 200:
            print(f"[session] Ended: {drops_done} drops, {cards_grabbed} grabs")
        else:
            print(f"[session] end failed: {res.status_code} {res.text}")
    except Exception as e:
        print(f"[session] end error: {e}")
