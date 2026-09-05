# -*- mode: python ; coding: utf-8 -*-
"""Canonical PyInstaller configuration for the Windows release."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all


spec_dir = Path(SPECPATH)

datas = []
binaries = []
hiddenimports = []

# These packages use dynamic imports and/or ship runtime data that PyInstaller's
# normal import analysis cannot discover. In particular, collecting all of
# Selenium includes every WebDriver submodule plus the Selenium Manager binary
# used to locate/download a compatible ChromeDriver.
for package_name in ("easyocr", "torch", "torchvision", "selenium"):
    package_datas, package_binaries, package_hiddenimports = collect_all(package_name)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports


a = Analysis(
    [str(spec_dir / "launcher.py")],
    pathex=[str(spec_dir)],
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
    a.binaries,
    a.datas,
    [],
    name="Aeyori",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(spec_dir / "icon.ico"),
)
