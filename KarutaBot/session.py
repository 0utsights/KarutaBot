"""
session.py — Aeyori session reporting

Called by gui.py when a bot session starts and stops.
Posts to the Aeyori API so the dashboard stats stay current.
Uses the same HttpOnly cookie auth as the web frontend (Bearer token
sent via Authorization header using the active license key as identity).
"""

import threading
import requests
from config import SERVER_URL
from license import get_tier, _active_key

# Tracks active session IDs per account name so stop() knows what to close
_sessions: dict[str, str] = {}
_lock = threading.Lock()


def _headers() -> dict:
    """Use the active license key as a bearer token for bot → API calls."""
    key = _active_key
    if key:
        return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    return {"Content-Type": "application/json"}


def start(account_name: str) -> str | None:
    """
    Tell the API a session has started for this account.
    Returns the session_id string, or None if the call failed.
    Runs synchronously — call from a thread if needed (start_bot already runs in one).
    """
    try:
        res = requests.post(
            f"{SERVER_URL}/api/sessions/start",
            json={"account_name": account_name, "tier": get_tier() or "semi"},
            headers=_headers(),
            timeout=8,
        )
        if res.status_code == 200:
            session_id = res.json().get("session_id")
            if session_id:
                with _lock:
                    _sessions[account_name] = session_id
            return session_id
    except Exception:
        pass  # Never crash the bot over stats
    return None


def end(account_name: str, drops_done: int, cards_grabbed: int) -> None:
    """
    Tell the API a session has ended with final stats.
    Safe to call even if start() failed — silently no-ops if no session_id.
    """
    with _lock:
        session_id = _sessions.pop(account_name, None)
    if not session_id:
        return
    try:
        requests.post(
            f"{SERVER_URL}/api/sessions/end",
            json={
                "session_id": session_id,
                "drops_done": drops_done,
                "cards_grabbed": cards_grabbed,
            },
            headers=_headers(),
            timeout=8,
        )
    except Exception:
        pass  # Never crash the bot over stats
