"""Off-screen UI harness for the portable ripgrep search panel.

Run from the project root:
  set QT_QPA_PLATFORM=offscreen
  build_venv\\Scripts\\python tests\\search_ui_harness.py
"""
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

import mru_manager as mru
from rdc_dashboard import SearchPanel


def wait_until(predicate, timeout_seconds=12):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        QApplication.processEvents()
        QTest.qWait(50)
        if predicate():
            return
    raise AssertionError("Timed out waiting for UI search completion")


def main():
    rg_path = shutil.which("rg.exe") or shutil.which("rg")
    if not rg_path:
        raise AssertionError("rg is required for the UI harness")

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory(prefix="rdc-search-harness-") as temp:
        root = Path(temp)
        (root / "notes.md").write_text("Before\nNeedle appears here\nAfter\n", encoding="utf-8")
        (root / "script.py").write_text("needle = 'second result'\n", encoding="utf-8")
        skipped = root / "node_modules"
        skipped.mkdir()
        (skipped / "skip.md").write_text("Needle must not be searched\n", encoding="utf-8")
        config_path = root / "rg-search.json"
        config_path.write_text(json.dumps({
            "rg_path": rg_path,
            "active_profile": "Harness",
            "profiles": [{
                "name": "Harness", "pinned": True, "roots": [str(root)],
                "include": ["*.md", "*.py"], "exclude": ["**/node_modules/**"],
                "options": {"regex": False, "case_insensitive": True, "whole_word": False,
                            "hidden": False, "follow_symlinks": False, "no_ignore": False,
                            "max_depth": 0, "threads": 0, "max_matches_per_file": 100,
                            "max_file_size": "10M"}
            }]
        }), encoding="utf-8")

        original_path = mru.search_config_path
        mru.search_config_path = lambda: config_path
        try:
            panel = SearchPanel()
            panel.show()
            QTest.keyClicks(panel.query, "needle")
            QTest.mouseClick(panel.whole_word, Qt.MouseButton.LeftButton)
            QTest.mouseClick(panel.search_button, Qt.MouseButton.LeftButton)
            wait_until(lambda: panel.search_button.isEnabled())

            assert panel.results.count() == 2, [panel.results.item(i).text() for i in range(panel.results.count())]
            result_paths = "\n".join(panel.results.item(i).text() for i in range(panel.results.count()))
            assert "notes.md" in result_paths and "script.py" in result_paths
            assert "skip.md" not in result_paths

            panel.results.setCurrentRow(0)
            wait_until(lambda: "Needle appears here" in panel.context.toPlainText())
            assert "> Needle appears here" in panel.context.toPlainText()

            QTest.mouseClick(panel.pin_button, Qt.MouseButton.LeftButton)
            saved = json.loads(config_path.read_text(encoding="utf-8"))
            assert saved["profiles"][0]["pinned"] is False
            panel.close()
        finally:
            mru.search_config_path = original_path
    print("SEARCH_UI_HARNESS_OK")


if __name__ == "__main__":
    main()
