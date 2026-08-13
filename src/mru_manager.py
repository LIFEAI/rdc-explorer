"""
mru_manager.py — Global MRU + Settings manager
Stores data in %APPDATA%/RDC_Dashboard/ (Windows) or ~/.config/RDC_Dashboard/ (Mac/Linux)
"""
import json
import os
import sys
import shutil
from pathlib import Path

APP_NAME = "RDC_Dashboard"
MAX_MRU = 20
DOCUMENT_SEARCH_PATTERNS = ("*.pdf", "*.docx", "*.pptx")
REQUIRED_SEARCH_EXCLUSIONS = ("**/_working/**", "**/*temp*/**", "**/*tmp*/**")


def _config_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", Path.home())
    else:
        base = Path.home() / ".config"
    d = Path(base) / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def crash_log_path() -> Path:
    """Persistent diagnostic log for unhandled desktop-app failures."""
    return _config_dir() / "crash.log"


def _resource_path(filename: str) -> Path:
    """Resolve a file bundled by PyInstaller or located in the source tree."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / filename


def search_config_path() -> Path:
    """Portable search settings live beside the executable, never in AppData."""
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parent.parent
    return base / "rg-search.json"


def load_search_config() -> dict:
    target = search_config_path()
    if not target.exists():
        shutil.copyfile(_resource_path("rg-search.default.json"), target)
    config = json.loads(target.read_text(encoding="utf-8"))
    # Existing portable profiles keep their roots and preferences; a feature update
    # only appends the requested document types that were previously unavailable.
    changed = False
    for profile in config.get("profiles", []):
        included = profile.setdefault("include", [])
        for pattern in DOCUMENT_SEARCH_PATTERNS:
            if pattern not in included:
                included.append(pattern)
                changed = True
        exclusions = profile.setdefault("exclude", [])
        for pattern in REQUIRED_SEARCH_EXCLUSIONS:
            if pattern not in exclusions:
                exclusions.append(pattern)
                changed = True
        profile.setdefault("options", {}).setdefault("max_total_results", 5000)
        profile.setdefault("options", {}).setdefault("search_time_limit_seconds", 12)
        profile.setdefault("search_documents", False)
    if changed:
        save_search_config(config)
    return config


def save_search_config(config: dict):
    search_config_path().write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")


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


def add_operation(desc: str):
    d = _get_mru()
    d["recent_ops"] = _push(d["recent_ops"], desc)
    _save("mru.json", d)


def get_recent_files() -> list:
    return _get_mru()["recent_files"]


def get_recent_folders() -> list:
    return _get_mru()["recent_folders"]


def get_recent_ops() -> list:
    return _get_mru()["recent_ops"]


def pin_file(path: str):
    d = _get_mru()
    d["pinned_files"] = _push(d["pinned_files"], path)
    _save("mru.json", d)


def pin_folder(path: str):
    d = _get_mru()
    d["pinned_folders"] = _push(d["pinned_folders"], path)
    _save("mru.json", d)


def unpin(path: str):
    d = _get_mru()
    d["pinned_files"] = [item for item in d["pinned_files"] if item != path]
    d["pinned_folders"] = [item for item in d["pinned_folders"] if item != path]
    _save("mru.json", d)


def get_pinned_files() -> list:
    return _get_mru()["pinned_files"]


def get_pinned_folders() -> list:
    return _get_mru()["pinned_folders"]


def clear_mru():
    _save("mru.json", {"recent_files": [], "recent_folders": [], "pinned_files": [], "pinned_folders": [], "recent_ops": []})


# ── Settings ─────────────────────────────────────────────────────────────────

def load_settings() -> dict:
    d = _load("settings.json")
    d.setdefault("rdc2_root", "")
    # Keep the original key for older panels, while Files uses this ordered list.
    d.setdefault("root_folders", [d["rdc2_root"]] if d["rdc2_root"] else [])
    d.setdefault("theme", "dark")
    d.setdefault("api_keys", {"anthropic": "", "openai": "", "google": ""})
    d.setdefault("window", {"x": 100, "y": 100, "w": 1200, "h": 800})
    return d


def save_settings(settings: dict):
    _save("settings.json", settings)
