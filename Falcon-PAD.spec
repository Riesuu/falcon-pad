# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Falcon-Pad — single-file distribution (--onefile).

Build:  pyinstaller Falcon-PAD.spec
Output: dist/Falcon-PAD(.exe on Windows, no extension on Linux)

Copyright (C) 2026  Riesu <contact@falcon-charts.com> — GNU GPL v3
"""

import sys
from PyInstaller.utils.hooks import collect_all

is_windows = sys.platform == 'win32'

# Bundle frontend assets and theater data inside the exe
datas = [
    ('frontend', 'frontend'),
    ('data',     'data'),
]
binaries = []
hiddenimports = [
    # uvicorn internals (dynamic imports via import_from_string)
    'uvicorn',
    'uvicorn.config',
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.loops.asyncio',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    'uvicorn.protocols',
    'uvicorn.protocols.utils',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.http.flow_control',
    'uvicorn.protocols.http.h11_impl',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.protocols.websockets.wsproto_impl',
    'uvicorn.server',
    # fastapi / starlette / pydantic
    'fastapi',
    'starlette.middleware.base',
    'starlette.responses',
    # app modules
    'app_info',
    'config',
    'core',
    'core.airports',
    'core.broadcast',
    'core.mission',
    'core.sharedmem',
    'core.stringdata',
    'core.theaters',
    'core.trtt',
    'server',
    'server.routes',
    'ui',
    'ui.ui_prefs',
    'ui.ui_theme',
]

# Pull in framework data files automatically
for pkg in ('uvicorn', 'fastapi', 'starlette', 'pydantic'):
    _d, _b, _h = collect_all(pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h


a = Analysis(
    ['falcon_pad.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'matplotlib', 'numpy', 'scipy', 'PIL',
        'pytest', '_pytest', 'httpx',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# --onefile: bundle everything into a single executable
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Falcon-PAD',
    debug=False,
    bootloader_ignore_signals=False,
    strip=not is_windows,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['frontend/images/FPLogo.ico'] if is_windows else [],
)
