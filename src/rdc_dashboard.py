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
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QPushButton, QLabel, QLineEdit, QTextEdit,
    QFileDialog, QCheckBox, QProgressBar, QListWidget, QListWidgetItem,
    QTreeView, QSplitter, QTabWidget, QComboBox, QAbstractItemView,
    QSystemTrayIcon, QMenu, QSizePolicy, QFrame, QSpinBox, QMessageBox,
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
QListWidget, QTreeView        { background: #252525; border: 1px solid #444; alternate-background-color: #2a2a2a; }
QListWidget::item:selected, QTreeView::item:selected { background: #2a6496; }
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


# ── Worker signals ───────────────────────────────────────────────────────────
class WorkerSignals(QObject):
    log    = pyqtSignal(str)
    done   = pyqtSignal()
    result = pyqtSignal(object)


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
        self.signals.result.connect(self._add_result)
        self.signals.log.connect(self._set_status)
        self.signals.done.connect(self._finish_search)
        self.match_count = 0
        self.matched_paths = set()

        tabs = QTabWidget(self)
        outer = QVBoxLayout(self)
        outer.addWidget(tabs)

        search_page = QWidget()
        layout = QVBoxLayout(search_page)
        title = QLabel("Portable Source Search"); title.setObjectName("section_title")
        layout.addWidget(title)

        query_row = QHBoxLayout()
        self.query = QLineEdit(); self.query.setPlaceholderText("Find text or regular expression…")
        self.query.returnPressed.connect(self.submit_search)
        query_row.addWidget(self.query)
        self.search_button = QPushButton("▶ Search")
        self.search_button.clicked.connect(self.submit_search)
        query_row.addWidget(self.search_button)
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
        tuning.addStretch()
        layout.addLayout(tuning)

        self.scope = QLabel(); self.scope.setWordWrap(True); self.scope.setStyleSheet("color:#b7c2d0; padding: 4px 0;")
        layout.addWidget(self.scope)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        results_pane = QWidget(); results_layout = QVBoxLayout(results_pane); results_layout.setContentsMargins(0, 0, 0, 0)
        results_layout.addWidget(QLabel("Matching lines"))
        self.results = QListWidget(); self.results.itemSelectionChanged.connect(self._show_context)
        self.results.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        results_layout.addWidget(self.results)
        context_pane = QWidget(); context_layout = QVBoxLayout(context_pane); context_layout.setContentsMargins(0, 0, 0, 0)
        context_layout.addWidget(QLabel("Selected match context (±3 lines)"))
        self.context = QTextEdit(); self.context.setReadOnly(True); self.context.setFont(QFont("Cascadia Mono", 10))
        context_layout.addWidget(self.context)
        splitter.addWidget(results_pane); splitter.addWidget(context_pane); splitter.setSizes([550, 650])
        layout.addWidget(splitter, 1)
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
            "max_matches_per_file": self.max_matches,
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

    def set_pinned(self, pinned):
        profile = self._profile()
        if not profile:
            return False
        profile["pinned"] = bool(pinned)
        mru.save_search_config(self.config)
        self._reload_config()
        return True

    def select_result(self, index):
        if not 0 <= index < self.results.count():
            return False
        self.results.setCurrentRow(index)
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
        for widget, key in ((self.max_depth, "max_depth"), (self.threads, "threads"), (self.max_matches, "max_matches_per_file")):
            widget.blockSignals(True); widget.setValue(int(options.get(key, 0 if key != "max_matches_per_file" else 100))); widget.blockSignals(False)
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
                              "max_matches_per_file": self.max_matches.value(),
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
        self.results.clear(); self.context.clear(); self.match_count = 0; self.matched_paths = set(); self.search_button.setEnabled(False)
        self._set_status("Searching selected roots…")
        threading.Thread(target=self._search_worker, args=(query, profile.copy(), self.config.copy()), daemon=True).start()

    def _search_worker(self, query, profile, config):
        try:
            for match in rg_search.search(query, profile, config):
                self.signals.result.emit(match)
        except Exception as exc:
            self.signals.log.emit(f"Search failed: {exc}")
        finally:
            self.signals.done.emit()

    def _add_result(self, match):
        self.match_count += 1
        self.matched_paths.add(match["path"])
        item = QListWidgetItem(f"{match['path']}:{match['line']}:{match['column']}  {match['text']}")
        item.setData(Qt.ItemDataRole.UserRole, match)
        self.results.addItem(item)

    def _show_context(self):
        selected = self.results.selectedItems()
        if not selected:
            return
        match = selected[0].data(Qt.ItemDataRole.UserRole)
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

    def _finish_search(self):
        self.search_button.setEnabled(True)
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
        self._switch(0)

    def _switch(self, idx: int):
        self.stack.setCurrentIndex(idx)
        for i, btn in enumerate(self.nav_buttons):
            btn.setChecked(i == idx)

    def _on_settings_changed(self, new_settings: dict):
        self.settings.update(new_settings)

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
    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setApplicationName("RDC Dashboard")
    app.setStyleSheet(DARK_QSS)
    app.setQuitOnLastWindowClosed(False)

    settings = mru.load_settings()
    window = MainWindow(settings)

    if not args.tray:
        window.show()

    exit_code = app.exec()
    window.save_geometry()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
