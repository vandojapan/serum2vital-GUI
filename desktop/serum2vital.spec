# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification for the GUI and its adjacent console worker."""

import os
import sys
from importlib.metadata import distribution
from pathlib import Path


ROOT = Path(SPEC).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from serum2vital import __version__ as VERSION


def distribution_licenses(name):
    """Collect license files from the exact wheel used for this build."""
    package = distribution(name)
    licenses = []
    for relative in package.files or []:
        relative_text = str(relative).replace("\\", "/").lower()
        if "/licenses/" not in relative_text:
            continue
        source = Path(package.locate_file(relative))
        if source.is_file():
            licenses.append((str(source), f"licenses/{name}"))
    if not licenses:
        raise RuntimeError(f"no bundled license file found for {name}")
    return licenses


python_license_candidates = [
    Path(sys.base_prefix) / "LICENSE.txt",
    Path(sys.base_prefix) / "LICENSE",
    Path(os.__file__).resolve().with_name("LICENSE.txt"),
]
python_license = next(
    (candidate for candidate in python_license_candidates if candidate.is_file()),
    None,
)
if python_license is None:
    raise RuntimeError("could not locate the Python runtime license")

license_data = [
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "THIRD_PARTY_NOTICES.md"), "."),
    (str(python_license), "licenses/Python"),
]
for distribution_name in ("cbor2", "zstandard", "pyinstaller"):
    license_data.extend(distribution_licenses(distribution_name))

COMMON = {
    "pathex": [str(ROOT)],
    "binaries": [],
    "datas": license_data,
    "hookspath": [],
    "hooksconfig": {},
    "runtime_hooks": [],
    "excludes": [],
    "noarchive": False,
    "optimize": 0,
}

gui_analysis = Analysis(
    [str(ROOT / "desktop" / "gui_entry.py")],
    hiddenimports=[],
    **COMMON,
)
worker_analysis = Analysis(
    [str(ROOT / "desktop" / "worker_entry.py")],
    hiddenimports=[
        "cbor2",
        "cbor2._cbor2",
        "zstandard",
        "zstandard.backend_c",
    ],
    **COMMON,
)

gui_pyz = PYZ(gui_analysis.pure)
worker_pyz = PYZ(worker_analysis.pure)

gui_exe = EXE(
    gui_pyz,
    gui_analysis.scripts,
    [],
    exclude_binaries=True,
    name="Serum2Vital",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=os.environ.get("SERUM2VITAL_CODESIGN_IDENTITY") or None,
    entitlements_file=None,
)
worker_exe = EXE(
    worker_pyz,
    worker_analysis.scripts,
    [("u", None, "OPTION")],
    exclude_binaries=True,
    name="serum2vital-worker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    hide_console="hide-early" if os.name == "nt" else None,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=os.environ.get("SERUM2VITAL_CODESIGN_IDENTITY") or None,
    entitlements_file=None,
)

collection = COLLECT(
    gui_exe,
    worker_exe,
    gui_analysis.binaries,
    gui_analysis.datas,
    worker_analysis.binaries,
    worker_analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Serum2Vital",
)

if os.name == "posix" and sys.platform == "darwin":
    app = BUNDLE(
        collection,
        name="Serum2Vital.app",
        icon=None,
        bundle_identifier="io.github.btesser.serum2vital",
        version=VERSION,
        info_plist={
            "CFBundleDisplayName": "serum2vital",
            "LSBackgroundOnly": False,
            "NSHighResolutionCapable": True,
            "NSPrincipalClass": "NSApplication",
        },
    )
