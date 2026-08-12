"""
rdc_dashboard.py — RDC AI Dashboard
PyQt6 desktop app. Single codebase for Windows and Mac.

Usage:
    python rdc_dashboard.py          # Open window
    python rdc_dashboard.py --tray   # Start minimised to tray
"""
import sys
import os
import threading
import json
import argparse
import traceback
import faulthandler
import copy
import re
from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QPushButton, QLabel, QLineEdit, QTextEdit,
    QFileDialog, QCheckBox, QProgressBar, QListWidget, QListWidgetItem,
    QTreeView, QSplitter, QTabWidget, QComboBox, QAbstractItemView,
    QSystemTrayIcon, QMenu, QSizePolicy, QFrame, QSpinBox, QMessageBox, QTreeWidget, QTreeWidgetItem,
)
from PyQt6.QtCore import (
    Qt, QDir, QModelIndex, pyqtSignal, QObject, QThread,
)
from PyQt6.QtGui import (
    QFileSystemModel, QAction, QIcon, QPixmap, QPainter, QColor, QFont,
)

import mru_manager as mru
from rdc_archive import run_archive
from rdc_training_sync import run_sync
from rdc_scaffold import build as run_scaffold
import rg_search

FAULT_LOG_HANDLE = None


def write_crash_log(origin, exc_type, exc_value, exc_traceback):
    """Append a readable exception record without ever masking the original failure."""
    try:
        stamp = datetime.now().astimezone().isoformat(timespec="seconds")
        detail = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        with mru.crash_log_path().open("a", encoding="utf-8") as handle:
            handle.write(f"\n{'=' * 88}\n{stamp}  origin={origin}\n{detail}")
    except Exception:
        pass


class SafeApplication(QApplication):
    """Keeps a bad UI callback from silently killing the desktop process."""
    def notify(self, receiver, event):
        try:
            return super().notify(receiver, event)
        except Exception:
            write_crash_log("qt-event", *sys.exc_info())
            return False

# ── Dark stylesheet ──────────────────────────────────────────────────────────
DARK_QSS = """
QMainWindow, QWidget          { background: #1e1e1e; color: #d4d4d4; font-family: Segoe UI, Arial; font-size: 13px; }
QPushButton                   { background: #3a3a3a; color: #d4d4d4; border: 1px solid #555; border-radius: 4px; padding: 5px 12px; }
QPushButton:hover             { background: #4a4a4a; }
QPushButton:pressed           { background: #2a6496; }
QPushButton#nav_btn           { text-align: left; padding: 10px 16px; border: none; border-radius: 0; font-size: 13px; }
QPushButton#nav_btn:checked   { background: #2a6496; color: #fff; border-left: 3px solid #5bc0de; }
QPushButton#nav_btn:hover     { background: #333; }
QLineEdit, QTextEdit          { background: #2d2d2d; border: 1px solid #555; border-radius: 4px; padding: 4px; color: #d4d4d4; }
QListWidget, QTreeView, QTreeWidget { background: #252525; border: 1px solid #444; alternate-background-color: #2a2a2a; }
QListWidget::item:selected, QTreeView::item:selected, QTreeWidget::item:selected { background: #2a6496; }
QTabWidget::pane              { border: 1px solid #444; }
QTabBar::tab                  { background: #2d2d2d; color: #aaa; padding: 6px 14px; border: 1px solid #444; }
QTabBar::tab:selected         { background: #1e1e1e; color: #d4d4d4; border-bottom: none; }
QProgressBar                  { background: #2d2d2d; border: 1px solid #555; border-radius: 4px; text-align: center; }
QProgressBar::chunk           { background: #2a6496; border-radius: 4px; }
QComboBox                     { background: #2d2d2d; border: 1px solid #555; border-radius: 4px; padding: 4px; }
QComboBox::drop-down          { border: none; }
QScrollBar:vertical           { background: #1e1e1e; width: 10px; }
QScrollBar::handle:vertical   { background: #555; border-radius: 4px; min-height: 20px; }
QLabel#section_title          { font-size: 15px; font-weight: bold; color: #5bc0de; padding: 8px 0 4px 0; }
QFrame#divider                { color: #444; }
"""

LIGHT_QSS = """
QMainWindow, QWidget          { background: #f7f9fc; color: #18212f; font-family: Segoe UI, Arial; font-size: 13px; }
QPushButton                   { background: #ffffff; color: #18212f; border: 1px solid #b9c4d1; border-radius: 4px; padding: 5px 12px; }
QPushButton:hover             { background: #e9f2fb; }
QPushButton:pressed           { background: #b9dcf7; }
QPushButton#nav_btn           { text-align: left; padding: 10px 16px; border: none; border-radius: 0; font-size: 13px; }
QPushButton#nav_btn:checked   { background: #d8ecfc; color: #123a58; border-left: 3px solid #1774b7; }
QLineEdit, QTextEdit          { background: #ffffff; border: 1px solid #aebdcb; border-radius: 4px; padding: 4px; color: #18212f; }
QListWidget, QTreeView, QTreeWidget { background: #ffffff; border: 1px solid #b9c4d1; alternate-background-color: #f1f5f9; }
QListWidget::item:selected, QTreeView::item:selected, QTreeWidget::item:selected { background: #cfe8fb; color: #12243a; }
QTabWidget::pane              { border: 1px solid #b9c4d1; }
QTabBar::tab                  { background: #e8edf3; color: #425466; padding: 6px 14px; border: 1px solid #b9c4d1; }
QTabBar::tab:selected         { background: #ffffff; color: #18212f; border-bottom: none; }
QComboBox                     { background: #ffffff; border: 1px solid #aebdcb; border-radius: 4px; padding: 4px; }
QScrollBar:vertical           { background: #edf2f7; width: 10px; }
QScrollBar::handle:vertical   { background: #8da2b8; border-radius: 4px; min-height: 20px; }
QLabel#section_title          { font-size: 15px; font-weight: bold; color: #1769aa; padding: 8px 0 4px 0; }
"""


# ── Worker signals ───────────────────────────────────────────────────────────
class WorkerSignals(QObject):
    log    = pyqtSignal(str)
    failed = pyqtSignal(str)
    done   = pyqtSignal()
    result = pyqtSignal(object)
    search_finished = pyqtSignal(int)


class ZoomableContext(QTextEdit):
    """Terminal-like context viewer: Ctrl+wheel changes text size without losing position."""
    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoomIn(1 if event.angleDelta().y() > 0 else -1)
            event.accept()
            return
        super().wheelEvent(event)


# ── Drag-drop file list ──────────────────────────────────────────────────────
class DropFileList(QListWidget):
    files_dropped = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls()]
        self.files_dropped.emit(paths)
        for p in paths:
            self.addItem(p)
            mru.add_file(p)


# ── File Panel ───────────────────────────────────────────────────────────────
class FilePanel(QWidget):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        layout = QHBoxLayout(self)

        # Left: folder tree
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0,0,0,0)
        lbl = QLabel("Folder Tree"); lbl.setObjectName("section_title")
        lv.addWidget(lbl)
        self.model = QFileSystemModel()
        self.model.setRootPath(QDir.rootPath())
        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setDragEnabled(True)
        self.tree.hideColumn(1); self.tree.hideColumn(2); self.tree.hideColumn(3)
        root = settings.get("rdc2_root", "")
        if root and os.path.isdir(root):
            idx = self.model.index(root)
            self.tree.setRootIndex(idx)
        self.tree.doubleClicked.connect(self._open_file)
        lv.addWidget(self.tree)

        btn_open = QPushButton("📂  Open in Explorer")
        btn_open.clicked.connect(self._open_explorer)
        lv.addWidget(btn_open)

        # Right: drop zone + MRU
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0,0,0,0)

        lbl2 = QLabel("Drop Files Here"); lbl2.setObjectName("section_title")
        rv.addWidget(lbl2)
        self.drop_list = DropFileList()
        self.drop_list.setMinimumHeight(120)
        rv.addWidget(self.drop_list)

        lbl3 = QLabel("Recent Files"); lbl3.setObjectName("section_title")
        rv.addWidget(lbl3)
        self.recent_files = QListWidget()
        self._refresh_mru()
        self.recent_files.itemDoubleClicked.connect(self._open_recent)
        rv.addWidget(self.recent_files)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([600, 400])
        layout.addWidget(splitter)

    def _open_file(self, idx: QModelIndex):
        path = self.model.filePath(idx)
        if os.path.isfile(path):
            mru.add_file(path)
            self._refresh_mru()
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                os.system(f'open "{path}"')
            else:
                os.system(f'xdg-open "{path}"')

    def _open_explorer(self):
        root = self.settings.get("rdc2_root", "")
        if root:
            mru.add_folder(root)
            if sys.platform == "win32":
                os.startfile(root)
            elif sys.platform == "darwin":
                os.system(f'open "{root}"')

    def _open_recent(self, item: QListWidgetItem):
        path = item.text()
        if os.path.exists(path):
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                os.system(f'open "{path}"')

    def _refresh_mru(self):
        self.recent_files.clear()
        for f in mru.get_recent_files():
            self.recent_files.addItem(f)


# ── Portable ripgrep search ──────────────────────────────────────────────────
class SearchPanel(QWidget):
    """On-demand local search. The portable JSON file is the source of truth."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = mru.load_search_config()
        self.signals = WorkerSignals()
        self.signals.result.connect(self._add_results)
        self.signals.log.connect(self._set_status)
        self.signals.failed.connect(self._search_failed)
        self.signals.search_finished.connect(self._finish_search)
        self.match_count = 0
        self.matched_paths = set()
        self.result_items = []
        self.result_matches = []
        self.directory_items = {}
        self.file_items = {}
        self.cancel_event = None
        self.search_generation = 0

        tabs = QTabWidget(self)
        outer = QVBoxLayout(self)
        outer.addWidget(tabs)

        search_page = QWidget()
        layout = QVBoxLayout(search_page)
        title = QLabel("Source Search"); title.setObjectName("section_title")
        layout.addWidget(title)

        query_row = QHBoxLayout()
        self.query = QLineEdit(); self.query.setPlaceholderText('"exact phrase" and symbol or not deprecated')
        self.query.returnPressed.connect(self.submit_search)
        query_row.addWidget(self.query)
        self.search_button = QPushButton("▶ Search")
        self.search_button.clicked.connect(self.submit_search)
        query_row.addWidget(self.search_button)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_search)
        query_row.addWidget(self.cancel_button)
        layout.addLayout(query_row)

        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("Pinned search:"))
        self.profile_combo = QComboBox()
        self.profile_combo.currentIndexChanged.connect(self._apply_profile)
        profile_row.addWidget(self.profile_combo, 1)
        self.pin_button = QPushButton("Pin / Unpin")
        self.pin_button.clicked.connect(self._toggle_pin)
        profile_row.addWidget(self.pin_button)
        layout.addLayout(profile_row)

        options = QHBoxLayout()
        self.regex = QCheckBox("Regex")
        self.case_insensitive = QCheckBox("Ignore case")
        self.whole_word = QCheckBox("Whole word")
        self.hidden = QCheckBox("Include hidden")
        self.follow = QCheckBox("Follow links")
        self.no_ignore = QCheckBox("Ignore .gitignore")
        for box in (self.regex, self.case_insensitive, self.whole_word, self.hidden, self.follow, self.no_ignore):
            box.stateChanged.connect(self._save_visible_options)
            options.addWidget(box)
        options.addStretch()
        layout.addLayout(options)

        source_scope = QHBoxLayout()
        source_scope.addWidget(QLabel("IN"))
        self.search_scope = QLineEdit()
        self.search_scope.setPlaceholderText("code, docs, *.md, frontmatter, or cf  (space/comma separated; blank = profile defaults)")
        self.search_scope.returnPressed.connect(self.submit_search)
        source_scope.addWidget(self.search_scope, 1)
        scope_help = QLabel("Groups: code  docs  fm/frontmatter  cf (CodeFlow)")
        scope_help.setStyleSheet("color:#b7c2d0;")
        source_scope.addWidget(scope_help)
        layout.addLayout(source_scope)

        tuning = QHBoxLayout()
        tuning.addWidget(QLabel("Max depth (0 = unlimited):"))
        self.max_depth = QSpinBox(); self.max_depth.setRange(0, 999); self.max_depth.valueChanged.connect(self._save_visible_options)
        tuning.addWidget(self.max_depth)
        tuning.addWidget(QLabel("Threads (0 = rg default):"))
        self.threads = QSpinBox(); self.threads.setRange(0, 64); self.threads.valueChanged.connect(self._save_visible_options)
        tuning.addWidget(self.threads)
        tuning.addWidget(QLabel("Max matches/file:"))
        self.max_matches = QSpinBox(); self.max_matches.setRange(1, 100000); self.max_matches.valueChanged.connect(self._save_visible_options)
        tuning.addWidget(self.max_matches)
        tuning.addWidget(QLabel("Max total results:"))
        self.max_total_results = QSpinBox(); self.max_total_results.setRange(1, 100000); self.max_total_results.setSingleStep(500); self.max_total_results.valueChanged.connect(self._save_visible_options)
        tuning.addWidget(self.max_total_results)
        tuning.addStretch()
        layout.addLayout(tuning)

        self.scope = QLabel(); self.scope.setWordWrap(True); self.scope.setStyleSheet("color:#b7c2d0; padding: 4px 0;")
        layout.addWidget(self.scope)
        splitter = QSplitter(Qt.Orientation.Vertical)
        results_pane = QWidget(); results_layout = QVBoxLayout(results_pane); results_layout.setContentsMargins(0, 0, 0, 0)
        results_layout.addWidget(QLabel("Matching directories — expand a directory, then a file, to inspect hits"))
        self.results = QTreeWidget()
        self.results.setHeaderLabels(["File", "Where", "Match preview"])
        self.results.setRootIsDecorated(True)
        self.results.setAlternatingRowColors(True)
        self.results.setColumnWidth(0, 260)
        self.results.setColumnWidth(1, 95)
        self.results.itemSelectionChanged.connect(self._show_context)
        self.results.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        results_layout.addWidget(self.results)
        context_pane = QWidget(); context_layout = QVBoxLayout(context_pane); context_layout.setContentsMargins(0, 0, 0, 0)
        context_layout.addWidget(QLabel("Selected match context (±3 lines)"))
        context_controls = QHBoxLayout()
        zoom_out = QPushButton("A−"); zoom_out.clicked.connect(lambda: self.set_context_zoom(-1))
        zoom_in = QPushButton("A+"); zoom_in.clicked.connect(lambda: self.set_context_zoom(1))
        zoom_reset = QPushButton("Reset zoom"); zoom_reset.clicked.connect(self.reset_context_zoom)
        context_controls.addWidget(zoom_out); context_controls.addWidget(zoom_in); context_controls.addWidget(zoom_reset); context_controls.addStretch()
        context_layout.addLayout(context_controls)
        self.context = ZoomableContext(); self.context.setReadOnly(True); self.context.setFont(QFont("Cascadia Mono", 10)); self.context_zoom = 0
        context_layout.addWidget(self.context)
        splitter.addWidget(results_pane); splitter.addWidget(context_pane); splitter.setSizes([520, 360])
        layout.addWidget(splitter, 1)
        result_actions = QHBoxLayout()
        open_selected = QPushButton("Open selected")
        open_selected.clicked.connect(self.open_selected_result)
        copy_path = QPushButton("Copy selected path")
        copy_path.clicked.connect(self.copy_selected_path)
        result_actions.addWidget(open_selected); result_actions.addWidget(copy_path); result_actions.addStretch()
        layout.addLayout(result_actions)
        self.status = QLabel("Ready. Searches are on demand; no Windows index is used.")
        layout.addWidget(self.status)
        tabs.addTab(search_page, "Search")

        config_page = QWidget()
        config_layout = QVBoxLayout(config_page)
        config_layout.addWidget(QLabel("Portable settings: " + str(mru.search_config_path())))
        self.config_editor = QTextEdit(); self.config_editor.setFont(QFont("Cascadia Mono", 10))
        config_layout.addWidget(self.config_editor)
        config_buttons = QHBoxLayout()
        reload_button = QPushButton("Reload from file"); reload_button.clicked.connect(self.reload_settings)
        save_button = QPushButton("Save settings"); save_button.clicked.connect(self.save_settings)
        config_buttons.addWidget(reload_button); config_buttons.addWidget(save_button); config_buttons.addStretch()
        config_layout.addLayout(config_buttons)
        tabs.addTab(config_page, "Profiles & Settings")
        self._reload_config()

    def _profiles(self):
        return self.config.get("profiles", [])

    def _profile(self):
        index = self.profile_combo.currentIndex()
        return self._profiles()[index] if 0 <= index < len(self._profiles()) else None

    # Public controller seam: buttons and the functional harness use these same methods.
    def select_profile(self, name):
        for index, profile in enumerate(self._profiles()):
            if profile.get("name") == name:
                self.profile_combo.setCurrentIndex(index)
                return True
        return False

    def set_search_options(self, **options):
        controls = {
            "regex": self.regex, "case_insensitive": self.case_insensitive,
            "whole_word": self.whole_word, "hidden": self.hidden,
            "follow_symlinks": self.follow, "no_ignore": self.no_ignore,
            "max_depth": self.max_depth, "threads": self.threads,
            "max_matches_per_file": self.max_matches, "max_total_results": self.max_total_results,
        }
        for key, value in options.items():
            control = controls.get(key)
            if control is None:
                raise ValueError(f"Unknown search option: {key}")
            control.blockSignals(True)
            if isinstance(control, QCheckBox):
                control.setChecked(bool(value))
            else:
                control.setValue(int(value))
            control.blockSignals(False)
        self._save_visible_options()

    def set_search_scope(self, scope):
        """Public controller seam for `IN code/docs/*.ext/frontmatter/cf`."""
        self.search_scope.setText(str(scope))
        return self.search_scope.text()

    def _scoped_profile(self, profile):
        scoped = copy.deepcopy(profile)
        raw = self.search_scope.text().strip()
        if not raw:
            return scoped, "disk"
        scopes = [part.casefold() for part in re.split(r"[\s,]+", raw) if part]
        if "cf" in scopes:
            if len(scopes) != 1:
                raise ValueError("Use IN cf by itself; CodeFlow does not search disk extensions.")
            return scoped, "codeflow"
        patterns, frontmatter = [], False
        for scope in scopes:
            if scope == "code":
                patterns.extend(rg_search.CODE_PATTERNS)
            elif scope == "docs":
                patterns.extend(rg_search.DOC_PATTERNS)
            elif scope in {"fm", "frontmatter"}:
                patterns.extend(("*.md", "*.mdx")); frontmatter = True
            else:
                normalized = scope if scope.startswith("*.") else f"*.{scope.lstrip('.')}"
                patterns.append(normalized)
        scoped["include"] = list(dict.fromkeys(patterns))
        scoped["frontmatter_only"] = frontmatter
        return scoped, "disk"

    def set_pinned(self, pinned):
        profile = self._profile()
        if not profile:
            return False
        profile["pinned"] = bool(pinned)
        mru.save_search_config(self.config)
        self._reload_config()
        return True

    def select_result(self, index):
        if not 0 <= index < len(self.result_items):
            return False
        item = self.result_items[index]
        item.parent().setExpanded(True)
        if item.parent().parent():
            item.parent().parent().setExpanded(True)
        self.results.setCurrentItem(item)
        return True

    def _selected_match(self):
        selected = self.results.selectedItems()
        return selected[0].data(0, Qt.ItemDataRole.UserRole) if selected else None

    def copy_selected_path(self):
        match = self._selected_match()
        selected = self.results.selectedItems()
        path = match["path"] if match else (selected[0].data(0, Qt.ItemDataRole.UserRole + 1) if selected else None)
        if not path:
            return False
        QApplication.clipboard().setText(path)
        self._set_status("Copied selected path.")
        return True

    def open_selected_result(self):
        match = self._selected_match()
        selected = self.results.selectedItems()
        path = match["path"] if match else (selected[0].data(0, Qt.ItemDataRole.UserRole + 1) if selected else None)
        if not path or not Path(path).exists():
            return False
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            os.system(f'open "{path}"')
        else:
            os.system(f'xdg-open "{path}"')
        return True

    def submit_search(self, query=None):
        if query is not None:
            self.query.setText(query)
        self._run_search()

    def _reload_config(self):
        self.config = mru.load_search_config()
        self.config_editor.setPlainText(json.dumps(self.config, indent=2, ensure_ascii=False))
        self.profile_combo.blockSignals(True); self.profile_combo.clear()
        for profile in self._profiles():
            prefix = "📌 " if profile.get("pinned") else "   "
            self.profile_combo.addItem(prefix + profile.get("name", "Unnamed"))
        active = self.config.get("active_profile", "")
        for i, profile in enumerate(self._profiles()):
            if profile.get("name") == active:
                self.profile_combo.setCurrentIndex(i)
                break
        self.profile_combo.blockSignals(False)
        self._apply_profile()

    def reload_settings(self):
        self._reload_config()

    def save_settings(self, serialized=None):
        if serialized is not None:
            self.config_editor.setPlainText(serialized)
        try:
            config = json.loads(self.config_editor.toPlainText())
            if not isinstance(config.get("profiles"), list) or not config["profiles"]:
                raise ValueError("profiles must be a non-empty list")
            mru.save_search_config(config)
            self._reload_config()
            self._set_status("Saved portable profile settings.")
            return True
        except Exception as exc:
            QMessageBox.warning(self, "Invalid settings", str(exc))
            return False

    def _apply_profile(self):
        profile = self._profile()
        if not profile:
            return
        self.config["active_profile"] = profile.get("name", "")
        options = profile.setdefault("options", {})
        widgets = ((self.regex, "regex"), (self.case_insensitive, "case_insensitive"),
                   (self.whole_word, "whole_word"), (self.hidden, "hidden"),
                   (self.follow, "follow_symlinks"), (self.no_ignore, "no_ignore"))
        for widget, key in widgets:
            widget.blockSignals(True); widget.setChecked(bool(options.get(key, False))); widget.blockSignals(False)
        for widget, key in ((self.max_depth, "max_depth"), (self.threads, "threads"), (self.max_matches, "max_matches_per_file"), (self.max_total_results, "max_total_results")):
            default = 5000 if key == "max_total_results" else (100 if key == "max_matches_per_file" else 0)
            widget.blockSignals(True); widget.setValue(int(options.get(key, default))); widget.blockSignals(False)
        roots = profile.get("roots", [])
        includes = profile.get("include", [])
        excludes = profile.get("exclude", [])
        max_size = options.get("max_file_size", "10M")
        self.scope.setText(
            f"Scope: {len(roots)} roots ({'; '.join(roots)})  •  {len(includes)} file types  •  "
            f"{len(excludes)} exclusions  •  {max_size} max/file"
        )
        self.scope.setToolTip(
            "Included types:\n" + "\n".join(includes) + "\n\nExcluded paths:\n" + "\n".join(excludes)
        )

    def _save_visible_options(self):
        profile = self._profile()
        if not profile:
            return
        profile["options"] = {"regex": self.regex.isChecked(), "case_insensitive": self.case_insensitive.isChecked(),
                              "whole_word": self.whole_word.isChecked(), "hidden": self.hidden.isChecked(),
                              "follow_symlinks": self.follow.isChecked(), "no_ignore": self.no_ignore.isChecked(),
                              "max_depth": self.max_depth.value(), "threads": self.threads.value(),
                              "max_matches_per_file": self.max_matches.value(), "max_total_results": self.max_total_results.value(),
                              "max_file_size": profile.get("options", {}).get("max_file_size", "10M")}
        mru.save_search_config(self.config)
        self.config_editor.setPlainText(json.dumps(self.config, indent=2, ensure_ascii=False))

    def _toggle_pin(self):
        profile = self._profile()
        if profile:
            self.set_pinned(not profile.get("pinned", False))

    def _run_search(self):
        query = self.query.text().strip()
        profile = self._profile()
        if not query or not profile:
            self._set_status("Enter search text and select a profile.")
            return
        self._save_visible_options()
        try:
            profile, source = self._scoped_profile(profile)
            rg_search.query_terms(query)
        except ValueError as exc:
            self._set_status(f"Search syntax: {exc}")
            return
        if self.cancel_event:
            self.cancel_event.set()
        self.search_generation += 1
        generation = self.search_generation
        self.results.clear(); self.context.clear(); self.match_count = 0; self.matched_paths = set(); self.search_error = ""; self.search_button.setEnabled(False); self.cancel_button.setEnabled(True)
        self.result_items = []
        self.result_matches = []
        self.directory_items = {}
        self.file_items = {}
        self.cancel_event = threading.Event()
        self._set_status("Searching CodeFlow symbols…" if source == "codeflow" else "Searching selected roots…")
        threading.Thread(target=self._search_worker, args=(generation, query, profile, self.config.copy(), self.cancel_event, source), daemon=True).start()

    def cancel_search(self):
        if self.cancel_event:
            self.cancel_event.set()
            self.cancel_button.setEnabled(False)
            self._set_status("Cancelling search…")

    def _search_worker(self, generation, query, profile, config, cancel_event, source="disk"):
        try:
            batch = []
            iterator = rg_search.search_codeflow(query, config, cancel_event) if source == "codeflow" else rg_search.search(query, profile, config, cancel_event)
            for match in iterator:
                batch.append(match)
                if len(batch) >= 100:
                    self.signals.result.emit((generation, batch))
                    batch = []
            if batch:
                self.signals.result.emit((generation, batch))
        except Exception as exc:
            self.signals.failed.emit((generation, str(exc)))
        finally:
            self.signals.search_finished.emit(generation)

    def _add_results(self, payload):
        generation, matches = payload if isinstance(payload, tuple) else (self.search_generation, payload)
        if generation != self.search_generation:
            return
        for match in (matches if isinstance(matches, list) else [matches]):
            self._add_result(match)

    @staticmethod
    def compact_path(path, start_chars=15, end_chars=25):
        value = str(path)
        if len(value) <= start_chars + end_chars + 5:
            return value
        return f"{value[:start_chars]} … {value[-end_chars:]}"

    def _add_result(self, match):
        self.match_count += 1
        self.matched_paths.add(match["path"])
        path = Path(match["path"])
        directory_key = str(path.parent)
        directory = self.directory_items.get(directory_key)
        if directory is None:
            directory = QTreeWidgetItem([self.compact_path(directory_key), "directory", ""])
            directory.setData(0, Qt.ItemDataRole.UserRole + 1, directory_key)
            directory.setToolTip(0, directory_key)
            self.results.addTopLevelItem(directory)
            self.directory_items[directory_key] = directory
        parent = self.file_items.get(match["path"])
        if parent is None:
            parent = QTreeWidgetItem([path.name, "", ""])
            parent.setData(0, Qt.ItemDataRole.UserRole + 1, match["path"])
            parent.setToolTip(0, match["path"])
            directory.addChild(parent)
            self.file_items[match["path"]] = parent
        location = match.get("location") or f"line {match['line']}"
        preview = match["text"].strip().replace("\t", " ")
        item = QTreeWidgetItem(["", location, preview])
        item.setData(0, Qt.ItemDataRole.UserRole, match)
        item.setToolTip(2, preview)
        parent.addChild(item)
        self.result_items.append(item)
        self.result_matches.append(match)
        parent.setText(1, f"{parent.childCount()} hit{'s' if parent.childCount() != 1 else ''}")

    def _show_context(self):
        match = self._selected_match()
        if not match:
            selected = self.results.selectedItems()
            if selected:
                path = selected[0].data(0, Qt.ItemDataRole.UserRole + 1)
                if path:
                    self.context.setPlainText(f"{path}\n\nExpand this directory or file to choose a matching line.")
            return
        if match.get("preview"):
            location = match.get("location", "document")
            self.context.setPlainText(f"{match['path']} — {location}\n\n{match['preview']}")
            return
        path = Path(match["path"])
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            start, end = max(0, match["line"] - 4), min(len(lines), match["line"] + 3)
            rendered = [f"{n + 1:>6}  {'>' if n + 1 == match['line'] else ' '} {lines[n]}" for n in range(start, end)]
            self.context.setPlainText(f"{path}\n\n" + "\n".join(rendered))
        except Exception as exc:
            self.context.setPlainText(f"{path}\n\nContext preview unavailable: {exc}")

    def _set_status(self, message):
        self.status.setText(message)

    def set_context_zoom(self, amount):
        self.context.zoomIn(int(amount))
        self.context_zoom += int(amount)

    def reset_context_zoom(self):
        if self.context_zoom:
            self.context.zoomIn(-self.context_zoom)
            self.context_zoom = 0

    def _search_failed(self, payload):
        generation, message = payload if isinstance(payload, tuple) else (self.search_generation, payload)
        if generation != self.search_generation:
            return
        self.search_error = message
        self._set_status(f"Search failed: {message}")

    def _finish_search(self, generation=None):
        if generation is not None and generation != self.search_generation:
            return
        self.search_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        if not self.search_error:
            if self.cancel_event and self.cancel_event.is_set():
                self._set_status(f"Cancelled after {self.match_count:,} matching lines in {len(self.matched_paths):,} files.")
            elif self.match_count >= self.max_total_results.value():
                self._set_status(f"Showing first {self.match_count:,} matching lines in {len(self.matched_paths):,} files (limit reached).")
            else:
                self._set_status(f"Complete: {self.match_count:,} matching lines in {len(self.matched_paths):,} files.")


# ── Archive Panel ─────────────────────────────────────────────────────────────
class ArchivePanel(QWidget):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        layout = QVBoxLayout(self)

        lbl = QLabel("Version Archiver"); lbl.setObjectName("section_title")
        layout.addWidget(lbl)

        row = QHBoxLayout()
        self.folder_edit = QLineEdit(settings.get("rdc2_root", ""))
        row.addWidget(self.folder_edit)
        btn_browse = QPushButton("Browse…")
        btn_browse.clicked.connect(self._browse)
        row.addWidget(btn_browse)
        layout.addLayout(row)

        self.dry_run_cb = QCheckBox("Dry run (preview only)")
        layout.addWidget(self.dry_run_cb)

        self.run_btn = QPushButton("▶  Run Archive")
        self.run_btn.clicked.connect(self._run)
        layout.addWidget(self.run_btn)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(QFont("Courier New", 10))
        layout.addWidget(self.log_view)

        lbl2 = QLabel("Recent Operations"); lbl2.setObjectName("section_title")
        layout.addWidget(lbl2)
        self.ops_list = QListWidget()
        self.ops_list.setMaximumHeight(100)
        for op in mru.get_recent_ops():
            self.ops_list.addItem(op)
        layout.addWidget(self.ops_list)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Select Folder", self.folder_edit.text())
        if d:
            self.folder_edit.setText(d)

    def _run(self):
        folder = self.folder_edit.text()
        if not folder or not os.path.isdir(folder):
            self.log_view.append("⚠ Invalid folder.")
            return
        self.run_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.log_view.clear()
        dry = self.dry_run_cb.isChecked()

        signals = WorkerSignals()
        signals.log.connect(self.log_view.append)
        signals.done.connect(self._on_done)

        def worker():
            run_archive(folder, dry_run=dry, log_callback=signals.log.emit)
            desc = f"Archive {'(dry)' if dry else ''}: {folder}"
            mru.add_operation(desc)
            signals.done.emit()

        threading.Thread(target=worker, daemon=True).start()

    def _on_done(self):
        self.run_btn.setEnabled(True)
        self.progress.setVisible(False)
        self.ops_list.insertItem(0, mru.get_recent_ops()[0] if mru.get_recent_ops() else "Done")


# ── Training Panel ────────────────────────────────────────────────────────────
class TrainingPanel(QWidget):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._manifest = []
        layout = QVBoxLayout(self)

        lbl = QLabel("AI Training Set Sync"); lbl.setObjectName("section_title")
        layout.addWidget(lbl)

        row = QHBoxLayout()
        self.folder_edit = QLineEdit(settings.get("rdc2_root", ""))
        row.addWidget(self.folder_edit)
        btn_b = QPushButton("Browse…")
        btn_b.clicked.connect(self._browse)
        row.addWidget(btn_b)
        layout.addLayout(row)

        self.dry_cb = QCheckBox("Dry run")
        layout.addWidget(self.dry_cb)

        self.sync_btn = QPushButton("🔄  Sync Training Files")
        self.sync_btn.clicked.connect(self._run)
        layout.addWidget(self.sync_btn)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        tabs = QTabWidget()
        self.log_view = QTextEdit(); self.log_view.setReadOnly(True)
        self.log_view.setFont(QFont("Courier New", 10))
        self.manifest_view = QTextEdit(); self.manifest_view.setReadOnly(True)
        tabs.addTab(self.log_view, "Sync Log")
        tabs.addTab(self.manifest_view, "Manifest")
        layout.addWidget(tabs)

        btn_copy = QPushButton("📋  Copy Manifest to Clipboard")
        btn_copy.clicked.connect(self._copy_manifest)
        layout.addWidget(btn_copy)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Select RDC2 Root", self.folder_edit.text())
        if d:
            self.folder_edit.setText(d)

    def _run(self):
        folder = self.folder_edit.text()
        if not folder or not os.path.isdir(folder):
            self.log_view.append("⚠ Invalid folder.")
            return
        self.sync_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.log_view.clear()
        dry = self.dry_cb.isChecked()
        signals = WorkerSignals()
        signals.log.connect(self.log_view.append)
        signals.result.connect(self._on_result)
        signals.done.connect(self._on_done)

        def worker():
            added, removed, manifest = run_sync(folder, dry_run=dry,
                                                log_callback=signals.log.emit)
            signals.result.emit(manifest)
            mru.add_operation(f"TrainingSync {'(dry)' if dry else ''}: +{added} -{removed}")
            signals.done.emit()

        threading.Thread(target=worker, daemon=True).start()

    def _on_result(self, manifest):
        self._manifest = manifest
        self.manifest_view.setPlainText("\n".join(manifest))

    def _on_done(self):
        self.sync_btn.setEnabled(True)
        self.progress.setVisible(False)

    def _copy_manifest(self):
        QApplication.clipboard().setText("\n".join(self._manifest))


# ── AI Tools Panel ────────────────────────────────────────────────────────────
class AIToolsPanel(QWidget):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        layout = QVBoxLayout(self)

        lbl = QLabel("AI Tools"); lbl.setObjectName("section_title")
        layout.addWidget(lbl)

        row = QHBoxLayout()
        row.addWidget(QLabel("Model:"))
        self.model_combo = QComboBox()
        self.model_combo.addItems([
            "claude-opus-4-5-20251101",
            "claude-sonnet-4-5-20250929",
            "claude-haiku-4-5-20251001",
            "gpt-4o",
            "gpt-4o-mini",
            "gemini-1.5-pro",
            "gemini-1.5-flash",
        ])
        row.addWidget(self.model_combo)
        layout.addLayout(row)

        layout.addWidget(QLabel("System Prompt:"))
        self.system_edit = QLineEdit("You are an expert regenerative development advisor.")
        layout.addWidget(self.system_edit)

        layout.addWidget(QLabel("Message:"))
        self.msg_edit = QTextEdit()
        self.msg_edit.setMaximumHeight(100)
        layout.addWidget(self.msg_edit)

        self.send_btn = QPushButton("🤖  Send")
        self.send_btn.clicked.connect(self._send)
        layout.addWidget(self.send_btn)

        layout.addWidget(QLabel("Response:"))
        self.response_view = QTextEdit()
        self.response_view.setReadOnly(True)
        layout.addWidget(self.response_view)

    def _send(self):
        model = self.model_combo.currentText()
        system = self.system_edit.text()
        msg = self.msg_edit.toPlainText().strip()
        if not msg:
            return
        self.send_btn.setEnabled(False)
        self.response_view.setPlainText("⏳ Calling API…")
        api_keys = self.settings.get("api_keys", {})
        signals = WorkerSignals()
        signals.result.connect(self._on_result)
        signals.done.connect(lambda: self.send_btn.setEnabled(True))

        def worker():
            try:
                response = self._call_api(model, system, msg, api_keys)
            except Exception as e:
                response = f"❌ Error: {e}"
            signals.result.emit(response)
            signals.done.emit()

        threading.Thread(target=worker, daemon=True).start()

    def _call_api(self, model: str, system: str, msg: str, keys: dict) -> str:
        if model.startswith("claude"):
            import anthropic
            client = anthropic.Anthropic(api_key=keys.get("anthropic", ""))
            r = client.messages.create(
                model=model, max_tokens=2048,
                system=system,
                messages=[{"role": "user", "content": msg}]
            )
            return r.content[0].text
        elif model.startswith("gpt"):
            from openai import OpenAI
            client = OpenAI(api_key=keys.get("openai", ""))
            r = client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system},
                           {"role": "user", "content": msg}]
            )
            return r.choices[0].message.content
        elif model.startswith("gemini"):
            import google.generativeai as genai
            genai.configure(api_key=keys.get("google", ""))
            m = genai.GenerativeModel(model, system_instruction=system)
            return m.generate_content(msg).text
        return "Unknown model."

    def _on_result(self, text: str):
        self.response_view.setPlainText(text)


# ── Settings Panel ────────────────────────────────────────────────────────────
class SettingsPanel(QWidget):
    settings_changed = pyqtSignal(dict)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        layout = QVBoxLayout(self)

        lbl = QLabel("Settings"); lbl.setObjectName("section_title")
        layout.addWidget(lbl)

        # RDC2 Root
        layout.addWidget(QLabel("RDC2 Root Folder:"))
        row = QHBoxLayout()
        self.root_edit = QLineEdit(settings.get("rdc2_root", ""))
        row.addWidget(self.root_edit)
        btn_b = QPushButton("Browse…")
        btn_b.clicked.connect(self._browse_root)
        row.addWidget(btn_b)
        layout.addLayout(row)

        # API Keys
        lbl2 = QLabel("API Keys"); lbl2.setObjectName("section_title")
        layout.addWidget(lbl2)
        keys = settings.get("api_keys", {})

        layout.addWidget(QLabel("Anthropic:"))
        self.anthropic_key = QLineEdit(keys.get("anthropic", ""))
        self.anthropic_key.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.anthropic_key)

        layout.addWidget(QLabel("OpenAI:"))
        self.openai_key = QLineEdit(keys.get("openai", ""))
        self.openai_key.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.openai_key)

        layout.addWidget(QLabel("Google AI:"))
        self.google_key = QLineEdit(keys.get("google", ""))
        self.google_key.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.google_key)

        btn_save = QPushButton("💾  Save Settings")
        btn_save.clicked.connect(self._save)
        layout.addWidget(btn_save)

        lbl3 = QLabel("Tools"); lbl3.setObjectName("section_title")
        layout.addWidget(lbl3)

        btn_scaffold = QPushButton("🏗  Build / Rebuild RDC2 Folder Structure")
        btn_scaffold.clicked.connect(self._scaffold)
        layout.addWidget(btn_scaffold)

        btn_clear_mru = QPushButton("🗑  Clear MRU History")
        btn_clear_mru.clicked.connect(self._clear_mru)
        layout.addWidget(btn_clear_mru)

        self.status = QLabel("")
        layout.addWidget(self.status)
        layout.addStretch()

    def _browse_root(self):
        d = QFileDialog.getExistingDirectory(self, "Select RDC2 Root", self.root_edit.text())
        if d:
            self.root_edit.setText(d)

    def _save(self):
        self.settings["rdc2_root"] = self.root_edit.text()
        self.settings["api_keys"] = {
            "anthropic": self.anthropic_key.text(),
            "openai":    self.openai_key.text(),
            "google":    self.google_key.text(),
        }
        mru.save_settings(self.settings)
        self.settings_changed.emit(self.settings)
        self.status.setText("✅ Settings saved.")

    def _scaffold(self):
        root = self.root_edit.text()
        if not root:
            self.status.setText("⚠ Set RDC2 root first.")
            return
        self.status.setText("⏳ Building scaffold…")
        QApplication.processEvents()
        n = run_scaffold(root)
        self.status.setText(f"✅ Scaffold built: {n} folders.")

    def _clear_mru(self):
        mru.clear_mru()
        self.status.setText("✅ MRU cleared.")


# ── Main Window ───────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self, settings: dict):
        super().__init__()
        self.settings = settings
        self.setWindowTitle("RDC AI Dashboard")
        self.resize(settings["window"]["w"], settings["window"]["h"])
        self.move(settings["window"]["x"], settings["window"]["y"])

        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Sidebar
        sidebar = QWidget()
        sidebar.setFixedWidth(180)
        sidebar.setObjectName("sidebar")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)

        logo = QLabel("  🏗 RDC Dashboard")
        logo.setStyleSheet("font-size:14px; font-weight:bold; color:#5bc0de; padding:16px 8px;")
        sidebar_layout.addWidget(logo)
        self.theme_button = QPushButton()
        self.theme_button.clicked.connect(self.toggle_theme)
        sidebar_layout.addWidget(self.theme_button)

        self.stack = QStackedWidget()
        self.panels = [
            ("📁  Files",     FilePanel(settings)),
            ("⌕  Search",    SearchPanel()),
            ("🗄  Archive",   ArchivePanel(settings)),
            ("🧠  Training",  TrainingPanel(settings)),
            ("🤖  AI Tools",  AIToolsPanel(settings)),
            ("⚙  Settings",  SettingsPanel(settings)),
        ]
        self.nav_buttons = []
        for i, (label, panel) in enumerate(self.panels):
            self.stack.addWidget(panel)
            btn = QPushButton(label)
            btn.setObjectName("nav_btn")
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, idx=i: self._switch(idx))
            sidebar_layout.addWidget(btn)
            self.nav_buttons.append(btn)

        sidebar_layout.addStretch()
        root_layout.addWidget(sidebar)
        root_layout.addWidget(self.stack)

        # Wire settings changes
        settings_panel = next(panel for label, panel in self.panels if label.endswith("Settings"))
        settings_panel.settings_changed.connect(self._on_settings_changed)

        # Tray
        self._setup_tray()
        self.set_theme(settings.get("theme", "dark"), persist=False)
        self._switch(0)

    def _switch(self, idx: int):
        self.stack.setCurrentIndex(idx)
        for i, btn in enumerate(self.nav_buttons):
            btn.setChecked(i == idx)

    def select_panel(self, page):
        """Public navigation seam shared by startup, UI actions, and tests."""
        requested = page.casefold()
        for index, (label, _) in enumerate(self.panels):
            if requested in label.casefold():
                self._switch(index)
                return True
        return False

    def _on_settings_changed(self, new_settings: dict):
        self.settings.update(new_settings)

    def set_theme(self, theme, persist=True):
        """Public theme seam used by the toggle and functional tests."""
        normalized = "light" if str(theme).casefold() == "light" else "dark"
        QApplication.instance().setStyleSheet(LIGHT_QSS if normalized == "light" else DARK_QSS)
        self.settings["theme"] = normalized
        self.theme_button.setText("☾ Dark theme" if normalized == "light" else "☀ Light theme")
        if persist:
            mru.save_settings(self.settings)
        return normalized

    def toggle_theme(self):
        return self.set_theme("light" if self.settings.get("theme") == "dark" else "dark")

    def _setup_tray(self):
        px = QPixmap(32, 32)
        px.fill(Qt.GlobalColor.transparent)
        p = QPainter(px)
        p.setBrush(QColor("#2a6496"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(0, 0, 32, 32, 6, 6)
        p.setPen(QColor("#fff"))
        p.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        p.drawText(px.rect(), Qt.AlignmentFlag.AlignCenter, "R")
        p.end()

        self.tray = QSystemTrayIcon(QIcon(px), self)
        menu = QMenu()
        for i, (label, _) in enumerate(self.panels):
            a = QAction(label, self)
            a.triggered.connect(lambda checked, idx=i: self._show_panel(idx))
            menu.addAction(a)
        menu.addSeparator()
        menu.addAction(QAction("Quit", self, triggered=QApplication.quit))
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda r: self.show() if r == QSystemTrayIcon.ActivationReason.Trigger else None
        )
        self.tray.show()

    def _show_panel(self, idx: int):
        self.show()
        self.raise_()
        self._switch(idx)

    def closeEvent(self, event):
        event.ignore()
        self.hide()
        self.tray.showMessage("RDC Dashboard", "Running in tray. Right-click to open.",
                              QSystemTrayIcon.MessageIcon.Information, 2000)

    def save_geometry(self):
        g = self.geometry()
        self.settings["window"] = {"x": g.x(), "y": g.y(), "w": g.width(), "h": g.height()}
        mru.save_settings(self.settings)


# ── Entry Point ───────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tray", action="store_true", help="Start minimised to tray")
    parser.add_argument("--page", choices=("files", "search", "archive", "training", "ai", "settings"),
                        help="Open a named dashboard page at startup")
    parser.add_argument("--self-test", action="store_true", help="Verify bundled Search runtime dependencies and exit")
    args = parser.parse_args()

    if args.self_test:
        rg_search.runtime_self_test()
        return

    global FAULT_LOG_HANDLE
    try:
        FAULT_LOG_HANDLE = mru.crash_log_path().open("a", encoding="utf-8", buffering=1)
        FAULT_LOG_HANDLE.write(f"\n{'=' * 88}\n{datetime.now().astimezone().isoformat(timespec='seconds')}  startup\n")
        faulthandler.enable(file=FAULT_LOG_HANDLE, all_threads=True)
    except Exception:
        FAULT_LOG_HANDLE = None
    sys.excepthook = lambda exc_type, exc_value, exc_traceback: write_crash_log(
        "main-thread", exc_type, exc_value, exc_traceback
    )
    threading.excepthook = lambda args: write_crash_log(
        f"thread:{args.thread.name}", args.exc_type, args.exc_value, args.exc_traceback
    )
    app = SafeApplication(sys.argv)
    app.setApplicationName("RDC Dashboard")
    app.setQuitOnLastWindowClosed(False)

    settings = mru.load_settings()
    window = MainWindow(settings)
    if args.page:
        window.select_panel(args.page)

    if not args.tray:
        window.show()

    exit_code = app.exec()
    window.save_geometry()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
