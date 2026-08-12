"""Off-screen UI harness for the portable ripgrep search panel.

Run from the project root:
  set QT_QPA_PLATFORM=offscreen
  build_venv\\Scripts\\python tests\\search_ui_harness.py
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PyQt6.QtWidgets import QApplication

import mru_manager as mru
import rg_search
from rdc_dashboard import SearchPanel

APP = None


def wait_until(predicate, timeout_seconds=12):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.05)
        if predicate():
            return
    raise AssertionError("Timed out waiting for UI search completion")


def run_panel_search(root: Path, profile_path: Path, query: str, include: list[str], exclude: list[str], expected_count: int = 1):
    global APP
    rg_path = shutil.which("rg.exe") or shutil.which("rg")
    if not rg_path:
        raise AssertionError("rg is required for the UI harness")
    APP = QApplication.instance() or QApplication([])
    profile_path.write_text(json.dumps({
            "rg_path": rg_path,
            "active_profile": "Harness",
            "profiles": [{
                "name": "Harness", "pinned": True, "roots": [str(root)],
                "include": include, "exclude": exclude,
                "options": {"regex": False, "case_insensitive": True, "whole_word": False,
                            "hidden": False, "follow_symlinks": False, "no_ignore": False,
                            "max_depth": 0, "threads": 0, "max_matches_per_file": 100,
                            "max_file_size": "10M"}
            }]
        }), encoding="utf-8")

    mru.search_config_path = lambda: profile_path
    panel = SearchPanel()
    assert panel.select_profile("Harness")
    panel.set_search_options(
        regex=True, case_insensitive=False, whole_word=False, hidden=True,
        follow_symlinks=True, no_ignore=True, max_depth=3, threads=2,
        max_matches_per_file=7,
    )
    enabled_command = rg_search.build_command(query, panel._profile(), panel.config)
    assert "--fixed-strings" not in enabled_command
    assert "--ignore-case" not in enabled_command
    assert "--word-regexp" not in enabled_command
    assert all(flag in enabled_command for flag in ("--hidden", "--follow", "--no-ignore", "--max-depth", "--threads"))
    assert enabled_command[enabled_command.index("--max-depth") + 1] == "3"
    assert enabled_command[enabled_command.index("--threads") + 1] == "2"
    assert enabled_command[enabled_command.index("--max-count") + 1] == "7"
    panel.set_search_options(
        regex=False, case_insensitive=True, whole_word=True, hidden=False,
        follow_symlinks=False, no_ignore=False, max_depth=0, threads=0,
        max_matches_per_file=100,
    )
    expected_options = {
        "regex": False, "case_insensitive": True, "whole_word": True,
        "hidden": False, "follow_symlinks": False, "no_ignore": False,
        "max_depth": 0, "threads": 0, "max_matches_per_file": 100,
    }
    assert all(panel._profile()["options"][key] == value for key, value in expected_options.items())
    command = rg_search.build_command(query, panel._profile(), panel.config)
    assert "--fixed-strings" in command and "--ignore-case" in command and "--word-regexp" in command
    panel.submit_search(query)
    wait_until(lambda: panel.search_button.isEnabled(), timeout_seconds=30)
    assert panel.results.count() >= expected_count, panel.status.text()
    assert panel.select_result(0)
    wait_until(lambda: bool(panel.context.toPlainText()))
    return panel


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live-regen-root", action="store_true")
    args = parser.parse_args()
    if args.live_regen_root:
        root = Path(r"C:\Dev\regen-root")
        assert root.is_dir(), root
        with tempfile.TemporaryDirectory(prefix="rdc-live-ui-test-") as temp:
            panel = run_panel_search(root, Path(temp) / "rg-search.json", "surface", ["*.md"],
                                     ["**/.git/**", "**/node_modules/**", "**/.next/**", "**/dist/**", "**/build/**"], 1)
            print(f"LIVE_REGEN_ROOT_UI_OK {panel.status.text()}")
            for i in range(min(20, panel.results.count())):
                print(panel.results.item(i).text())
            print("SELECTED_CONTEXT")
            print(panel.context.toPlainText()[:1200])
            panel.close()
        return

    with tempfile.TemporaryDirectory(prefix="rdc-search-harness-") as temp:
        root = Path(temp)
        (root / "notes.md").write_text("Before\nNeedle appears here\nAfter\n", encoding="utf-8")
        (root / "script.py").write_text("needle = 'second result'\n", encoding="utf-8")
        skipped = root / "node_modules"
        skipped.mkdir()
        (skipped / "skip.md").write_text("Needle must not be searched\n", encoding="utf-8")
        panel = run_panel_search(root, root / "rg-search.json", "needle", ["*.md", "*.py"], ["**/node_modules/**"], 2)
        assert panel.results.count() == 2, [panel.results.item(i).text() for i in range(panel.results.count())]
        assert panel.status.text() == "Complete: 2 matching lines in 2 files.", panel.status.text()
        result_paths = "\n".join(panel.results.item(i).text() for i in range(panel.results.count()))
        assert "notes.md" in result_paths and "script.py" in result_paths
        assert "skip.md" not in result_paths
        assert "> needle" in panel.context.toPlainText().lower()
        assert panel.set_pinned(False)
        assert panel.save_settings()
        panel.reload_settings()
        saved = json.loads((root / "rg-search.json").read_text(encoding="utf-8"))
        assert saved["profiles"][0]["pinned"] is False
        panel.close()
    print("SEARCH_UI_HARNESS_OK")


if __name__ == "__main__":
    main()
