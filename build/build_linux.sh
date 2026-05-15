#!/usr/bin/env bash
# ============================================================
#  RDC Explorer — Linux Build
#  Produces: dist/RDC_Explorer          (standalone binary)
#            dist/RDC_Explorer.tar.gz   (distributable archive)
#  Run on Linux with Python 3.11+
# ============================================================
set -e
echo ""
echo "============================================================"
echo "  RDC Explorer  —  Linux Build"
echo "  Produces: dist/RDC_Explorer  +  dist/RDC_Explorer.tar.gz"
echo "============================================================"
echo ""

PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
echo "[OK] Project: $PROJECT"

# ── Python check ─────────────────────────────────────────────
PY=$(command -v python3 || true)
[ -z "$PY" ] && { echo "[ERROR] python3 not found."; exit 1; }
PY_VER=$("$PY" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "[OK] Python $PY_VER found."

# ── System deps check (optional Qt xcb for headful systems) ──
if command -v apt-get &>/dev/null; then
    echo "[..] Checking system Qt/xcb libraries (headless builds skip this)..."
    apt-get install -y -q \
        libglib2.0-0 \
        libdbus-1-3 \
        libxcb-cursor0 \
        libxcb-icccm4 \
        libxcb-image0 \
        libxcb-keysyms1 \
        libxcb-randr0 \
        libxcb-render-util0 \
        libxcb-shape0 \
        libxcb-xinerama0 \
        libxcb-xkb1 \
        libxkbcommon-x11-0 2>/dev/null || true
    echo "[OK] System libs checked."
fi

# ── Build venv ───────────────────────────────────────────────
VENV="$PROJECT/build_venv"
if [ ! -f "$VENV/bin/activate" ]; then
    echo "[..] Creating build venv..."
    "$PY" -m venv "$VENV"
fi
source "$VENV/bin/activate"
echo "[OK] Venv active: $VENV"

# ── Dependencies ─────────────────────────────────────────────
echo "[..] Installing build deps..."
pip install --upgrade pip -q
pip install -r "$PROJECT/requirements.txt" -q
pip install pyinstaller pillow -q
echo "[OK] Deps installed."

# ── Icon ─────────────────────────────────────────────────────
echo "[..] Generating icons..."
python "$PROJECT/assets/create_icon.py"
echo "[OK] Icons generated."

# ── PyInstaller ──────────────────────────────────────────────
echo "[..] Running PyInstaller (2-3 min)..."
cd "$PROJECT"
pyinstaller --clean --noconfirm build/rdc_dashboard.spec
echo "[OK] Built: dist/RDC_Explorer"

# ── Verify binary ────────────────────────────────────────────
BINARY="$PROJECT/dist/RDC_Explorer"
if [ ! -f "$BINARY" ]; then
    # PyInstaller on Linux sometimes produces a directory bundle
    BINARY_DIR="$PROJECT/dist/RDC_Explorer"
    if [ -d "$BINARY_DIR" ]; then
        echo "[OK] One-folder bundle found at: $BINARY_DIR"
        BINARY="$BINARY_DIR/RDC_Explorer"
    fi
fi
[ -f "$BINARY" ] || { echo "[ERROR] Binary not found. Check PyInstaller output."; exit 1; }
echo "[OK] Binary: $BINARY"

# ── Make executable ──────────────────────────────────────────
chmod +x "$BINARY"

# ── Write launcher shell script ──────────────────────────────
LAUNCHER_DIR="$PROJECT/launchers"
mkdir -p "$LAUNCHER_DIR"
cat > "$LAUNCHER_DIR/launch_explorer.sh" <<'LAUNCHER'
#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BINARY="$SCRIPT_DIR/../dist/RDC_Explorer"
if [ ! -f "$BINARY" ]; then
    echo "[ERROR] RDC Explorer binary not found at: $BINARY"
    echo "Please run build/build_linux.sh first."
    exit 1
fi
exec "$BINARY" "$@"
LAUNCHER
chmod +x "$LAUNCHER_DIR/launch_explorer.sh"
echo "[OK] Launcher: $LAUNCHER_DIR/launch_explorer.sh"

# ── Write .desktop entry ─────────────────────────────────────
DESKTOP_FILE="$PROJECT/launchers/RDC_Explorer.desktop"
ICON_PATH="$PROJECT/assets/icon.png"
cat > "$DESKTOP_FILE" <<DESKTOP
[Desktop Entry]
Version=1.0
Type=Application
Name=RDC Explorer
Comment=RDC Explorer — file management and AI tools
Exec=$BINARY
Icon=$ICON_PATH
Terminal=false
Categories=Utility;FileManager;
StartupNotify=true
DESKTOP
chmod +x "$DESKTOP_FILE"
echo "[OK] .desktop file: $DESKTOP_FILE"

# ── Install .desktop to system (optional) ─────────────────────
if command -v xdg-desktop-menu &>/dev/null && [ -n "$DISPLAY" ]; then
    xdg-desktop-menu install "$DESKTOP_FILE" 2>/dev/null || true
    echo "[OK] .desktop installed to XDG menu."
fi

# ── Create distributable tarball ─────────────────────────────
echo "[..] Creating distributable archive..."
DIST_NAME="RDC_Explorer_Linux_v2.0.0"
STAGING="$PROJECT/dist/${DIST_NAME}"
rm -rf "$STAGING"
mkdir -p "$STAGING"

# Copy binary (or one-folder bundle)
if [ -d "$PROJECT/dist/RDC_Explorer" ] && [ "$(ls -A "$PROJECT/dist/RDC_Explorer" 2>/dev/null | wc -l)" -gt 1 ]; then
    cp -R "$PROJECT/dist/RDC_Explorer" "$STAGING/"
else
    cp "$BINARY" "$STAGING/"
fi

# Copy icon and launcher
cp "$ICON_PATH" "$STAGING/" 2>/dev/null || true
cp "$DESKTOP_FILE" "$STAGING/"

# Write a quick-start README
cat > "$STAGING/README.txt" <<'README'
RDC Explorer — Linux
====================

Quick Start:
  1. Copy this folder anywhere (e.g. ~/Applications/RDC_Explorer/)
  2. Run:  ./RDC_Explorer
     Or double-click RDC_Explorer.desktop in your file manager.

To add to your application menu:
  xdg-desktop-menu install RDC_Explorer.desktop

Requirements:
  - 64-bit Linux (Ubuntu 20.04+ / Debian 11+ / Fedora 36+)
  - X11 or Wayland display server
  - No Python installation required (self-contained)

Support:  dave@regendevcorp.com
README

# Create the tarball
TAR="$PROJECT/dist/${DIST_NAME}.tar.gz"
tar -czf "$TAR" -C "$PROJECT/dist" "$DIST_NAME"
rm -rf "$STAGING"
echo "[OK] Archive: $TAR"

# ── Smoke test (headless) ────────────────────────────────────
echo "[..] Running headless smoke test (import check)..."
cd "$PROJECT/src"
python3 -c "
import sys
sys.path.insert(0, '.')
ok = True
for mod in ['mru_manager', 'rdc_archive', 'rdc_training_sync', 'rdc_scaffold']:
    try:
        __import__(mod)
        print(f'  ✓ {mod}')
    except Exception as e:
        print(f'  ✗ {mod}: {e}')
        ok = False

try:
    from PyQt6.QtWidgets import QApplication
    print('  ✓ PyQt6 import OK')
except Exception as e:
    print(f'  ✗ PyQt6: {e}')
    # Not fatal on headless — binary is already built
print()
if ok:
    print('All non-UI modules OK.')
else:
    print('Some modules failed — check output above.')
"
echo "[OK] Smoke tests complete."

echo ""
echo "============================================================"
echo "  Build complete!"
echo ""
echo "  Standalone binary: dist/RDC_Explorer"
echo "  Distributable:     dist/${DIST_NAME}.tar.gz"
echo ""
echo "  To run:            ./dist/RDC_Explorer"
echo "  To install menu:   xdg-desktop-menu install launchers/RDC_Explorer.desktop"
echo "============================================================"
echo ""
