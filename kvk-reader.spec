# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for KVK/eGK Reader.

Build on Windows with:
    pyinstaller kvk-reader.spec

For debugging startup issues, temporarily set CONSOLE = True below.
This shows a console window with error messages.
"""

import sys
from pathlib import Path

# ---- Toggle this for debugging startup crashes ----
CONSOLE = False
# ---------------------------------------------------

block_cipher = None

a = Analysis(
    ['kvk_reader/main.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('assets/fonts', 'assets/fonts'),
        ('assets/icons', 'assets/icons'),
    ],
    hiddenimports=[
        # PyQt5
        'PyQt5',
        'PyQt5.QtCore',
        'PyQt5.QtGui',
        'PyQt5.QtWidgets',
        'PyQt5.QtNetwork',
        'PyQt5.sip',
        # pyscard (smartcard)
        'smartcard',
        'smartcard.System',
        'smartcard.Exceptions',
        'smartcard.CardMonitoring',
        'smartcard.scard',
        # Brother QL printer
        'brother_ql',
        'brother_ql.raster',
        'brother_ql.conversion',
        'brother_ql.backends',
        'brother_ql.backends.helpers',
        'brother_ql.backends.pyusb',
        'brother_ql.models',
        'brother_ql.labels',
        # USB
        'usb',
        'usb.core',
        'usb.backend',
        'usb.backend.libusb1',
        # Flask API
        'flask',
        'flask.json',
        'flask.sansio',
        # XML parsing
        'lxml',
        'lxml.etree',
        # Pillow (imaging)
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'PIL.ImageFont',
        'PIL.ImageWin',
        # Windows printing (pywin32)
        'win32print',
        'win32ui',
        'win32con',
        # Standard library (sometimes missed)
        'sqlite3',
        'ctypes',
        'dataclasses',
        'logging.handlers',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'numpy',
        'scipy',
        'pandas',
        'tkinter',
        '_tkinter',
        'test',
        'unittest',
    ],
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
    name='KVK-Reader',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=CONSOLE,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icons/app_icon.ico' if Path('assets/icons/app_icon.ico').exists() else None,
)
