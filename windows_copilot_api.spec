# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all, collect_submodules


curl_datas, curl_binaries, curl_hidden = collect_all("curl_cffi")

datas = curl_datas + [
    ("LICENSE", "."),
    ("README.md", "."),
]
binaries = curl_binaries
hiddenimports = sorted(set(
    curl_hidden
    + collect_submodules("uvicorn")
    + collect_submodules("fastapi")
    + collect_submodules("pydantic")
))

a = Analysis(
    ["release_entry.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    [],
    exclude_binaries=True,
    name="windows-copilot-api",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="windows-copilot-api",
)
