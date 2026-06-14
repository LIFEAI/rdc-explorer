"""
rdc_dashboard.py — RDC Explorer
PyQt6 desktop app. Single codebase for Windows and Mac.

Usage:
    python rdc_dashboard.py          # Open window
    python rdc_dashboard.py --tray   # Start minimised to tray
"""
import sys
import os
import threading
import argparse
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QPushButton, QLabel, QLineEdit, QTextEdit,
    QFileDialog, QCheckBox, QProgressBar, QListWidget, QListWidgetItem,
    QTreeView, QSplitter, QTabWidget, QComboBox, QAbstractItemView,
    QSystemTrayIcon, QMenu, QSizePolicy, QFrame,
)
from PyQt6.QtCore import (
    Qt, QDir, QModelIndex, pyqtSignal, QObject, QThread,
)
from PyQt6.QtGui import (
    QFileSystemModel,  # Moved from QtWidgets to QtGui in PyQt6
    QAction, QIcon, QPixmap, QPainter, QColor, QFont,
)

import mru_manager as mru
from rdc_archive import run_archive
from rdc_training_sync import run_sync
from rdc_scaffold import build as run_scaffold

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
def paths_from_mime_data(mime_data) -> list[str]:
    paths: list[str] = []
    if mime_data.hasUrls():
        paths.extend(u.toLocalFile() for u in mime_data.urls() if u.toLocalFile())

    model_data = "application/x-qabstractitemmodeldatalist"
    if mime_data.hasFormat(model_data):
        text = mime_data.text()
        if text:
            paths.extend(line.strip() for line in text.splitlines() if line.strip())

    deduped: list[str] = []
    seen: set[str] = set()
    for path in paths:
        path = os.path.normpath(path)
        normalized = os.path.normcase(os.path.abspath(path))
        if normalized not in seen and os.path.exists(path):
            seen.add(normalized)
            deduped.append(path)
    return deduped


class DropFileList(QListWidget):
    files_dropped = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)

    def dragEnterEvent(self, e):
        if paths_from_mime_data(e.mimeData()):
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if paths_from_mime_data(e.mimeData()):
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        paths = paths_from_mime_data(e.mimeData())
        if not paths:
            super().dropEvent(e)
            return
        self.files_dropped.emit(paths)
        for p in paths:
            self.addItem(p)
            if os.path.isdir(p):
                mru.add_folder(p)
            else:
                mru.add_file(p)
        e.acceptProposedAction()


def file_type_label(path: str) -> str:
    ext = Path(path).suffix.lower().lstrip(".")
    if not ext:
        return "Other"
    if ext in {"doc", "docx", "odt", "rtf", "txt", "pdf"}:
        return "Docs"
    if ext in {"ppt", "pptx", "odp", "key"}:
        return "Slides"
    if ext in {"md", "markdown", "mdx"}:
        return "Markdown"
    if ext in {"xls", "xlsx", "csv", "tsv"}:
        return "Sheets"
    if ext in {"png", "jpg", "jpeg", "gif", "webp", "svg"}:
        return "Images"
    return ext.upper()


def grouped_files_by_type(paths: list[str]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for path in paths:
        grouped.setdefault(file_type_label(path), []).append(path)
    return {
        label: sorted(items, key=lambda p: os.path.basename(p).lower())
        for label, items in sorted(grouped.items(), key=lambda item: item[0].lower())
    }


def find_first_path(root: str, query: str, max_entries: int = 5000) -> str | None:
    """Return the first file/folder under root whose name contains query."""
    needle = query.strip().lower()
    if not needle or not root or not os.path.isdir(root):
        return None

    root_name = os.path.basename(os.path.normpath(root)).lower()
    if needle in root_name:
        return root

    visited = 0
    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda _err: None):
        visited += len(dirnames) + len(filenames)
        if visited > max_entries:
            return None
        dirnames[:] = sorted(
            [d for d in dirnames if d not in {"$RECYCLE.BIN", "System Volume Information"}],
            key=str.lower,
        )
        for name in dirnames + sorted(filenames, key=str.lower):
            if needle in name.lower():
                return os.path.join(dirpath, name)
    return None


class SearchLineEdit(QLineEdit):
    dismissed = pyqtSignal()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.clear()
            self.hide()
            self.dismissed.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class SearchableTreeView(QTreeView):
    search_typed = pyqtSignal(str)

    def keyPressEvent(self, event):
        text = event.text()
        if text and text.isprintable() and not event.modifiers() & (
            Qt.KeyboardModifier.ControlModifier
            | Qt.KeyboardModifier.AltModifier
            | Qt.KeyboardModifier.MetaModifier
        ):
            self.search_typed.emit(text)
            event.accept()
            return
        super().keyPressEvent(event)


# ── File Panel ───────────────────────────────────────────────────────────────
class FilePanel(QWidget):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        layout = QHBoxLayout(self)

        # Left: pinned file manager
        pins = QWidget()
        pv = QVBoxLayout(pins)
        pv.setContentsMargins(0,0,8,0)

        pin_title = QLabel("Pinned"); pin_title.setObjectName("section_title")
        pv.addWidget(pin_title)

        drop_label = QLabel("Drop Files or Folders to Pin"); drop_label.setObjectName("section_title")
        pv.addWidget(drop_label)
        self.drop_list = DropFileList()
        self.drop_list.setMinimumHeight(90)
        self.drop_list.files_dropped.connect(self._pin_paths)
        self.drop_list.itemDoubleClicked.connect(self._open_path_item)
        pv.addWidget(self.drop_list)

        folder_label = QLabel("Folders"); folder_label.setObjectName("section_title")
        pv.addWidget(folder_label)
        self.pinned_folders = QListWidget()
        self.pinned_folders.setMaximumHeight(140)
        self.pinned_folders.itemDoubleClicked.connect(self._open_path_item)
        pv.addWidget(self.pinned_folders)

        files_label = QLabel("Files by Type"); files_label.setObjectName("section_title")
        pv.addWidget(files_label)
        self.pinned_files = QListWidget()
        self.pinned_files.itemDoubleClicked.connect(self._open_path_item)
        pv.addWidget(self.pinned_files)

        # Right: folder tree
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0,0,0,0)
        lbl = QLabel("Folder Tree"); lbl.setObjectName("section_title")
        lv.addWidget(lbl)
        self.search_edit = SearchLineEdit()
        self.search_edit.setPlaceholderText("Search this tree...")
        self.search_edit.textChanged.connect(self._search_tree)
        self.search_edit.dismissed.connect(lambda: self.tree.setFocus())
        self.search_edit.hide()
        lv.addWidget(self.search_edit)
        self.model = QFileSystemModel()
        self.model.setRootPath(QDir.rootPath())
        self.tree = SearchableTreeView()
        self.tree.setModel(self.model)
        self.tree.setDragEnabled(True)
        self.tree.hideColumn(1); self.tree.hideColumn(2); self.tree.hideColumn(3)
        root = settings.get("rdc2_root", "")
        if root and os.path.isdir(root):
            idx = self.model.index(root)
            self.tree.setRootIndex(idx)
        self.tree.doubleClicked.connect(self._open_file)
        self.tree.search_typed.connect(self._append_tree_search)
        lv.addWidget(self.tree)

        btn_open = QPushButton("📂  Open in Explorer")
        btn_open.clicked.connect(self._open_explorer)
        lv.addWidget(btn_open)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(pins)
        splitter.addWidget(left)
        splitter.setSizes([330, 700])
        layout.addWidget(splitter)
        self._refresh_pins()

    def _open_file(self, idx: QModelIndex):
        path = self.model.filePath(idx)
        if os.path.isfile(path):
            mru.add_file(path)
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

    def _append_tree_search(self, text: str):
        if not self.search_edit.isVisible():
            self.search_edit.show()
        self.search_edit.setFocus()
        self.search_edit.setText(self.search_edit.text() + text)
        self.search_edit.setCursorPosition(len(self.search_edit.text()))

    def _tree_root_path(self) -> str:
        root_idx = self.tree.rootIndex()
        root = self.model.filePath(root_idx)
        if root and os.path.isdir(root):
            return root
        return self.settings.get("rdc2_root", "") or QDir.rootPath()

    def _search_tree(self, query: str):
        if not query.strip():
            return
        match = find_first_path(self._tree_root_path(), query)
        if not match:
            return
        idx = self.model.index(match)
        if not idx.isValid():
            return
        parent = idx.parent()
        while parent.isValid():
            self.tree.expand(parent)
            parent = parent.parent()
        self.tree.setCurrentIndex(idx)
        self.tree.scrollTo(idx, QAbstractItemView.ScrollHint.PositionAtCenter)

    def _pin_paths(self, paths: list[str]):
        for path in paths:
            if os.path.isdir(path):
                mru.pin_folder(path)
            elif os.path.isfile(path):
                mru.pin_file(path)
        self._refresh_pins()

    def _add_path_item(self, widget: QListWidget, path: str):
        item = QListWidgetItem(os.path.basename(path) or path)
        item.setToolTip(path)
        item.setData(Qt.ItemDataRole.UserRole, path)
        widget.addItem(item)

    def _add_group_header(self, widget: QListWidget, label: str):
        item = QListWidgetItem(label)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        widget.addItem(item)

    def _refresh_pins(self):
        self.pinned_folders.clear()
        for folder in mru.get_pinned_folders():
            if os.path.exists(folder):
                self._add_path_item(self.pinned_folders, folder)

        self.pinned_files.clear()
        for label, files in grouped_files_by_type(mru.get_pinned_files()).items():
            existing = [path for path in files if os.path.exists(path)]
            if not existing:
                continue
            self._add_group_header(self.pinned_files, label)
            for path in existing:
                self._add_path_item(self.pinned_files, path)

    def _open_path_item(self, item: QListWidgetItem):
        path = item.data(Qt.ItemDataRole.UserRole) or item.text()
        if os.path.exists(path):
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                os.system(f'open "{path}"')


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
            import google.genai as genai
            client = genai.Client(api_key=keys.get("google", ""))
            response = client.models.generate_content(
                model=model,
                contents=msg,
                config=genai.types.GenerateContentConfig(system_instruction=system),
            )
            return response.text
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
        self.setWindowTitle("RDC Explorer")
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

        logo = QLabel("  🏗 RDC Explorer")
        logo.setStyleSheet("font-size:14px; font-weight:bold; color:#5bc0de; padding:16px 8px;")
        sidebar_layout.addWidget(logo)

        self.stack = QStackedWidget()
        self.panels = [
            ("📁  Files",     FilePanel(settings)),
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
        self.panels[4][1].settings_changed.connect(self._on_settings_changed)

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
        self.tray.showMessage("RDC Explorer", "Running in tray. Right-click to open.",
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
    app.setApplicationName("RDC Explorer")
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
