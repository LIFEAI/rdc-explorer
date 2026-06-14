"""
mru_manager.py — Global MRU + Settings manager
Stores data in %APPDATA%/RDC_Explorer/ (Windows) or ~/.config/RDC_Explorer/ (Mac/Linux)
"""
import json
import os
import sys
from pathlib import Path

APP_NAME = "RDC_Explorer"
MAX_MRU = 20


def _config_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", Path.home())
    else:
        base = Path.home() / ".config"
    d = Path(base) / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load(filename: str) -> dict:
    path = _config_dir() / filename
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save(filename: str, data: dict):
    path = _config_dir() / filename
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ── MRU ──────────────────────────────────────────────────────────────────────

def _get_mru() -> dict:
    d = _load("mru.json")
    d.setdefault("recent_files", [])
    d.setdefault("recent_folders", [])
    d.setdefault("pinned_files", [])
    d.setdefault("pinned_folders", [])
    d.setdefault("recent_ops", [])
    return d


def _push(lst: list, item: str) -> list:
    lst = [x for x in lst if x != item]
    lst.insert(0, item)
    return lst[:MAX_MRU]


def add_file(path: str):
    d = _get_mru()
    d["recent_files"] = _push(d["recent_files"], path)
    _save("mru.json", d)


def add_folder(path: str):
    d = _get_mru()
    d["recent_folders"] = _push(d["recent_folders"], path)
    _save("mru.json", d)


def pin_file(path: str):
    d = _get_mru()
    d["pinned_files"] = _push(d["pinned_files"], path)
    _save("mru.json", d)


def pin_folder(path: str):
    d = _get_mru()
    d["pinned_folders"] = _push(d["pinned_folders"], path)
    _save("mru.json", d)


def add_operation(desc: str):
    d = _get_mru()
    d["recent_ops"] = _push(d["recent_ops"], desc)
    _save("mru.json", d)


def get_recent_files() -> list:
    return _get_mru()["recent_files"]


def get_recent_folders() -> list:
    return _get_mru()["recent_folders"]


def get_pinned_files() -> list:
    return _get_mru()["pinned_files"]


def get_pinned_folders() -> list:
    return _get_mru()["pinned_folders"]


def get_recent_ops() -> list:
    return _get_mru()["recent_ops"]


def clear_mru():
    _save("mru.json", {
        "recent_files": [],
        "recent_folders": [],
        "pinned_files": [],
        "pinned_folders": [],
        "recent_ops": [],
    })


# ── Settings ─────────────────────────────────────────────────────────────────

def load_settings() -> dict:
    d = _load("settings.json")
    d.setdefault("rdc2_root", "")
    d.setdefault("theme", "dark")
    d.setdefault("api_keys", {"anthropic": "", "openai": "", "google": ""})
    d.setdefault("window", {"x": 100, "y": 100, "w": 1200, "h": 800})
    return d


def save_settings(settings: dict):
    _save("settings.json", settings)
