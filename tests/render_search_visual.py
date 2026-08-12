"""Render-only visual harness for the portable Search panel.

This deliberately does not send keyboard or mouse events.  Functional behavior
belongs in search_ui_harness.py; this script renders the real Qt widget and
writes a screenshot for layout review.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from rdc_dashboard import DARK_QSS, SearchPanel


def main():
    output = Path(__file__).resolve().parents[1] / "artifacts" / "search-panel-visual.png"
    output.parent.mkdir(exist_ok=True)
    app = QApplication([])
    app.setStyleSheet(DARK_QSS)
    panel = SearchPanel()
    panel.resize(1280, 820)
    panel.show()

    def capture():
        if not panel.grab().save(str(output), "PNG"):
            raise RuntimeError(f"Unable to write {output}")
        panel.close()
        app.quit()

    QTimer.singleShot(250, capture)
    app.exec()
    print(f"SEARCH_VISUAL_RENDER_OK {output}")


if __name__ == "__main__":
    main()
