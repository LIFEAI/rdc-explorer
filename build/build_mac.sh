#!/usr/bin/env bash
# ============================================================
#  RDC Explorer — macOS Build
#  Produces: dist/RDC_Explorer.dmg
#  Run on a Mac with Python 3.11+
# ============================================================
set -e
echo ""
echo "============================================================"
echo "  RDC Explorer  —  macOS Build"
echo "  Produces: dist/RDC_Explorer.dmg"
echo "============================================================"
echo ""

PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
echo "[OK] Project: $PROJECT"

# ── Python check ─────────────────────────────────────────────
PY=$(command -v python3 || true)
[ -z "$PY" ] && { echo "[ERROR] python3 not found."; exit 1; }
echo "[OK] $($PY --version)"

# ── Build venv ───────────────────────────────────────────────
VENV="$PROJECT/build_venv"
[ -f "$VENV/bin/activate" ] || "$PY" -m venv "$VENV"
source "$VENV/bin/activate"

# ── Dependencies ─────────────────────────────────────────────
echo "[..] Installing build deps..."
pip install --upgrade pip -q
pip install -r "$PROJECT/requirements.txt" -q
pip install pyinstaller pillow -q
echo "[OK] Deps installed."

# ── Icon ─────────────────────────────────────────────────────
echo "[..] Generating icons..."
python "$PROJECT/assets/create_icon.py"

# ── PyInstaller ──────────────────────────────────────────────
echo "[..] Running PyInstaller (2-3 min)..."
cd "$PROJECT"
pyinstaller --clean --noconfirm build/rdc_dashboard.spec
echo "[OK] Built: dist/RDC Explorer.app"

# ── Verify .app ──────────────────────────────────────────────
APP="$PROJECT/dist/RDC Explorer.app"
[ -d "$APP" ] || { echo "[ERROR] .app not found at: $APP"; exit 1; }

# ── Create DMG ───────────────────────────────────────────────
DMG="$PROJECT/dist/RDC_Explorer_v2.0.0.dmg"
STAGING="$PROJECT/dist/_dmg_staging"
rm -rf "$STAGING" "$DMG"
mkdir "$STAGING"

# Copy app into staging
cp -R "$APP" "$STAGING/"

# Symlink to /Applications for drag-install
ln -s /Applications "$STAGING/Applications"

echo "[..] Creating DMG..."
hdiutil create \
    -volname "RDC Explorer" \
    -srcfolder "$STAGING" \
    -ov \
    -format UDZO \
    -imagekey zlib-level=9 \
    "$DMG"

rm -rf "$STAGING"

# ── Set DMG window layout (cosmetic, via AppleScript) ────────
osascript <<APPLESCRIPT 2>/dev/null || true
tell application "Finder"
    tell disk "RDC Explorer"
        open
        set current view of container window to icon view
        set toolbar visible of container window to false
        set statusbar visible of container window to false
        set bounds of container window to {400, 100, 900, 400}
        set icon size of the icon view options of container window to 100
        set position of item "RDC Explorer.app" of container window to {130, 150}
        set position of item "Applications" of container window to {370, 150}
        close
        eject
    end tell
end tell
APPLESCRIPT

echo ""
echo "============================================================"
echo "  Build complete!"
echo "  DMG: dist/RDC_Explorer_v2.0.0.dmg"
echo ""
echo "  To install: open the DMG, drag RDC Explorer to Applications"
echo "============================================================"
echo ""
