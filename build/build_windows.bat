@echo off
setlocal EnableDelayedExpansion
title RDC Explorer — Windows Build
echo.
echo ============================================================
echo   RDC Explorer  —  Windows 11 Build
echo   Produces: dist\RDC_Explorer_Setup_v2.0.0.exe
echo ============================================================
echo.

set SCRIPT_DIR=%~dp0
pushd "%SCRIPT_DIR%.."
set PROJECT=%CD%
popd

:: ── Python check ─────────────────────────────────────────────
python --version >nul 2>&1 || (
    echo [ERROR] Python not found. Install from https://python.org
    pause & exit /b 1
)

:: ── Build venv ───────────────────────────────────────────────
set VENV=%PROJECT%\build_venv
if not exist "%VENV%\Scripts\activate.bat" (
    echo [..] Creating build virtual environment...
    python -m venv "%VENV%"
)
call "%VENV%\Scripts\activate.bat"

:: ── Install build deps ───────────────────────────────────────
echo [..] Installing build dependencies...
pip install --upgrade pip -q
pip install -r "%PROJECT%\requirements.txt" -q
pip install pyinstaller pillow -q
echo [OK] Dependencies ready.

:: ── Generate icon ────────────────────────────────────────────
echo [..] Generating icon...
python "%PROJECT%\assets\create_icon.py"

:: ── PyInstaller build ─────────────────────────────────────────
echo [..] Building with PyInstaller (this takes ~2-3 minutes)...
cd "%PROJECT%"
pyinstaller --clean --noconfirm build\rdc_dashboard.spec
if errorlevel 1 (
    echo [ERROR] PyInstaller build failed.
    pause & exit /b 1
)
echo [OK] PyInstaller complete: dist\RDC_Explorer.exe

:: ── Inno Setup ───────────────────────────────────────────────
echo [..] Looking for Inno Setup...
set ISCC=""
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set ISCC="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if exist "C:\Program Files\Inno Setup 6\ISCC.exe"       set ISCC="C:\Program Files\Inno Setup 6\ISCC.exe"

if %ISCC%=="" (
    echo [WARN] Inno Setup not found. Skipping installer packaging.
    echo        Standalone exe is at: dist\RDC_Explorer.exe
    echo        Download Inno Setup from https://jrsoftware.org/isinfo.php
    echo        Then re-run this script to produce the full Setup.exe
) else (
    echo [..] Building installer with Inno Setup...
    %ISCC% "%PROJECT%\build\installer_windows.iss"
    if errorlevel 1 (
        echo [ERROR] Inno Setup failed.
    ) else (
        echo [OK] Installer: dist\RDC_Explorer_Setup_v2.0.0.exe
    )
)

echo.
echo ============================================================
echo   Build complete.
echo   Standalone exe : dist\RDC_Explorer.exe
echo   Full installer : dist\RDC_Explorer_Setup_v2.0.0.exe
echo ============================================================
echo.
pause
