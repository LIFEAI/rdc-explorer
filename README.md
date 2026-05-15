# RDC Explorer

Desktop application for managing RDC company files, versioning, AI training sync, and multi-model AI tools. Built with PyQt6 — runs on Windows, macOS, and Linux.

> **Note:** The GitHub repo is still named `rdc-ai-dashboard` — a rename to `rdc-explorer` is recommended.

---

## What It Does

| Panel | Function |
|---|---|
| **Files** | Browse the RDC2 folder tree, drag files into recent lists, quick-open |
| **Archive** | Scan any folder, keep the highest version of each file, move older versions to `_archive/` |
| **Training Sync** | Find all `_TRAIN_`-tagged files, copy latest versions to `00 - _AI-Training/` |
| **AI Tools** | Chat with Claude, OpenAI, or Gemini — switch models on the fly |
| **Settings** | Set RDC2 root, API keys, scaffold new folder trees |

---

## Building

Each script creates a **standalone executable** — no Python required on the target machine.

### Windows
```bat
cd build
build_windows.bat
```
Outputs:
- `dist\RDC_Explorer.exe` — standalone binary
- `dist\RDC_Explorer_Setup_v2.0.0.exe` — Inno Setup wizard installer (if Inno Setup 6 is installed)

Requires: Python 3.11+, [Inno Setup 6](https://jrsoftware.org/isinfo.php) (optional, for the wizard installer)

---

### macOS
```bash
cd build
bash build_mac.sh
```
Outputs:
- `dist/RDC_Explorer_v2.0.0.dmg` — drag-to-Applications disk image

Requires: Python 3.11+, Xcode CLI tools (`xcode-select --install`)

---

### Linux
```bash
cd build
bash build_linux.sh
```
Outputs:
- `dist/RDC_Explorer` — standalone ELF binary
- `dist/RDC_Explorer_Linux_v2.0.0.tar.gz` — distributable archive

Requires: Python 3.10+, X11 or Wayland display server

---

## Project Structure

```
rdc-ai-dashboard/
├── src/
│   ├── rdc_dashboard.py       # Main PyQt6 app (entry point)
│   ├── rdc_archive.py         # Version archiver
│   ├── rdc_training_sync.py   # _TRAIN_ file sync
│   ├── rdc_scaffold.py        # RDC2 folder tree builder
│   └── mru_manager.py         # MRU lists + settings (JSON)
├── build/
│   ├── build_windows.bat      # Windows build script
│   ├── build_mac.sh           # macOS build script
│   ├── build_linux.sh         # Linux build script
│   ├── rdc_dashboard.spec     # PyInstaller spec (shared)
│   └── installer_windows.iss  # Inno Setup 6 script
├── assets/
│   ├── create_icon.py         # Generates ICO / ICNS / PNG with Pillow
│   ├── icon.ico               # Windows icon
│   └── icon.png               # Linux / shared icon
└── requirements.txt
```

---

## File Naming Convention

All RDC files follow: `CompanyCode_Purpose_Type_VX.XX.ext`

**Company codes:** RDC · TPF · FP · LBS · LifeAI · RC · D6 · DEM · SPIG · REG

**Types:** Deck · Exec_Sum · One_Pager · Overview · BizPlan · NDA · PPM

**Example:** `RDC_Investor_Deck_V1.03.pptx`

Third-party reference docs use the `REF_` prefix: `REF_ANSI_IP_Standard_V3.00.pdf`

---

## Dev Setup (no build)

```bash
pip install -r requirements.txt
python src/rdc_dashboard.py
```

---

## Contact

Dave Ladouceur · dave@regendevcorp.com · Life before Profits.
