"""User settings stored in ~/.aram_player/config.json (editable from the app's Settings screen).
Environment variables still win, for developers."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

PATH = Path.home() / ".aram_player" / "config.json"
DEFAULTS = {"ai_enabled": False, "api_key": "", "workspace_id": "", "model": "haiku",
            "record": False}
_lock = threading.Lock()


def load() -> dict:
    try:
        return DEFAULTS | json.loads(PATH.read_text())
    except Exception:
        return dict(DEFAULTS)


def save(update: dict) -> dict:
    with _lock:
        cfg = load() | {k: v for k, v in update.items() if k in DEFAULTS}
        PATH.parent.mkdir(parents=True, exist_ok=True)
        PATH.write_text(json.dumps(cfg, indent=1))
        try:
            os.chmod(PATH, 0o600)  # API key: readable by this user only
        except OSError:
            pass
        return cfg


def api_key() -> str:
    return os.environ.get("ANTHROPIC_API_KEY") or load()["api_key"]


def workspace_id() -> str:
    return os.environ.get("ANTHROPIC_WORKSPACE_ID") or load()["workspace_id"]


def model_alias() -> str:
    return os.environ.get("ARAM_MODEL") or load()["model"]


def recording() -> bool:
    return bool(load().get("record"))


def ai_enabled() -> bool:
    if os.environ.get("ARAM_NO_AI") == "1":
        return False
    if os.environ.get("ANTHROPIC_API_KEY"):
        return True
    cfg = load()
    return bool(cfg["ai_enabled"] and cfg["api_key"])


def public() -> dict:
    """Settings for the UI - never returns the full key."""
    cfg = load()
    k = api_key()
    return {"ai_enabled": ai_enabled(), "model": model_alias(), "workspace_id": workspace_id(),
            "record": recording(),
            "has_key": bool(k), "key_hint": (k[:7] + "…" + k[-4:]) if len(k) > 12 else ""}
