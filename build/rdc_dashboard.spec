# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — shared across Windows, Mac, Linux
import sys, os

block_cipher = None
SRC = os.path.join(os.path.dirname(SPECPATH), 'src')
ASSETS = os.path.join(os.path.dirname(SPECPATH), 'assets')

a = Analysis(
    [os.path.join(SRC, 'rdc_dashboard.py')],
    pathex=[SRC],
    binaries=[],
    datas=[
        (os.path.join(ASSETS, 'icon.png'), 'assets'),
        (os.path.join(os.path.dirname(SPECPATH), 'rg-search.default.json'), '.'),
    ],
    hiddenimports=[
        'mru_manager',
        'rdc_archive',
        'rdc_training_sync',
        'rdc_scaffold',
        'anthropic',
        'openai',
        'google.generativeai',
        'PyQt6.QtWidgets',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtNetwork',
        'PyQt6.sip',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'pandas'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='RDC_Dashboard',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # No terminal window on Windows/Mac
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ASSETS, 'icon.ico') if sys.platform == 'win32'
         else os.path.join(ASSETS, 'icon.icns'),
)

# Mac .app bundle only
if sys.platform == 'darwin':
    app = BUNDLE(
        exe,
        name='RDC Dashboard.app',
        icon=os.path.join(ASSETS, 'icon.icns'),
        bundle_identifier='com.regendevcorp.rdc-dashboard',
        info_plist={
            'CFBundleName':              'RDC Dashboard',
            'CFBundleDisplayName':       'RDC Dashboard',
            'CFBundleVersion':           '1.0.0',
            'CFBundleShortVersionString': '1.0.0',
            'NSPrincipalClass':          'NSApplication',
            'NSHighResolutionCapable':   True,
            'NSAppleScriptEnabled':      False,
            'LSMinimumSystemVersion':    '13.0',
        },
    )
