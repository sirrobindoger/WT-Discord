# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules


numpy_binaries = collect_dynamic_libs("numpy")
numpy_hiddenimports = collect_submodules(
    "numpy._core",
    filter=lambda name: ".tests" not in name,
)

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=numpy_binaries,
    datas=[],
    hiddenimports=numpy_hiddenimports + [
        "win32timezone",
        "PIL",
        "pypresence",
        "requests",
        "win32serviceutil",
        "win32service",
        "win32event",
        "servicemanager",
        "psutil",
        "imagehash",
        "simplejson",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="WarThunderRPC_Setup",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[],
)
