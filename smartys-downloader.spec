# -*- mode: python ; coding: utf-8 -*-
# Build: pyinstaller smartys-downloader.spec
import sys
from pathlib import Path

block = Analysis(
    ['entry.py'],
    pathex=[str(Path('.').resolve())],
    binaries=[],
    datas=[('web', 'web')],          # Web-GUI mit einpacken
    hiddenimports=['smartdl.api'],
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'PIL', 'test', 'pytest'],
    noarchive=False,
)
pyz = PYZ(block.pure)

exe = EXE(
    pyz,
    block.scripts,
    [],
    exclude_binaries=True,
    name='SmartDownloader',
    debug=False,
    console=True,
    icon=None,                       # optional: icon.ico ergänzen
)
coll = COLLECT(
    exe,
    block.binaries,
    block.datas,
    strip=False,
    name='SmartDownloader',
)
