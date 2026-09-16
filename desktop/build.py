"""Build, smoke-test and archive a native Serum2Vital desktop package."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import plistlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "desktop" / "serum2vital.spec"
DIST_ROOT = ROOT / "dist" / "desktop"
BUILD_ROOT = ROOT / "build" / "desktop"
PACKAGE_ROOT = ROOT / "dist" / "packages"

sys.path.insert(0, str(ROOT))
from serum2vital import __version__ as VERSION


def _platform_tag() -> str:
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform.startswith("linux"):
        return "linux"
    raise RuntimeError(f"unsupported packaging platform: {sys.platform}")


def _architecture_tag(machine: str | None = None) -> str:
    value = (machine or platform.machine()).lower()
    if value in {"amd64", "x64", "x86_64"}:
        return "x86_64"
    if value in {"aarch64", "arm64"}:
        return "arm64"
    return value.replace(" ", "-")


def _artifact() -> Path:
    if sys.platform == "darwin":
        return DIST_ROOT / "Serum2Vital.app"
    return DIST_ROOT / "Serum2Vital"


def _executables(artifact: Path) -> tuple[Path, Path]:
    extension = ".exe" if sys.platform.startswith("win") else ""
    if sys.platform == "darwin":
        executable_dir = artifact / "Contents" / "MacOS"
    else:
        executable_dir = artifact
    return (
        executable_dir / f"Serum2Vital{extension}",
        executable_dir / f"serum2vital-worker{extension}",
    )


def _check_build_dependencies() -> None:
    required = ("PyInstaller", "PySide6", "zstandard", "cbor2")
    missing = [name for name in required if importlib.util.find_spec(name) is None]
    if missing:
        names = ", ".join(missing)
        raise RuntimeError(
            f"missing build dependencies: {names}. "
            'Run: python -m pip install -e ".[desktop,package]"'
        )


def _build() -> Path:
    _check_build_dependencies()
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath",
        str(DIST_ROOT),
        "--workpath",
        str(BUILD_ROOT),
        str(SPEC),
    ]
    print("Building the native desktop bundle…", flush=True)
    environment = os.environ.copy()
    # Keep PyInstaller's binary cache with the build output. This makes local
    # builds work in sandboxed CI environments whose user cache is read-only.
    environment["PYINSTALLER_CONFIG_DIR"] = str(BUILD_ROOT / ".pyinstaller")
    subprocess.run(command, cwd=ROOT, env=environment, check=True)
    artifact = _artifact()
    if not artifact.exists():
        raise RuntimeError(f"PyInstaller did not create {artifact}")
    gui, worker = _executables(artifact)
    for executable in (gui, worker):
        if not executable.is_file():
            raise RuntimeError(f"packaged executable is missing: {executable}")
    if sys.platform == "darwin":
        with (artifact / "Contents" / "Info.plist").open("rb") as source:
            app_info = plistlib.load(source)
        if app_info.get("LSBackgroundOnly"):
            raise RuntimeError("macOS GUI bundle was incorrectly marked background-only")
    return artifact


def _run_smoke_tests(artifact: Path) -> None:
    gui, worker = _executables(artifact)
    if sys.platform == "darwin":
        subprocess.run(
            ["codesign", "--verify", "--deep", "--strict", str(artifact)],
            check=True,
        )
    fixtures = [
        ROOT / "DebugPresets" / "serum1" / "00 init.fxp",
        ROOT / "DebugPresets" / "8.SerumPreset",
    ]
    print("Smoke-testing the bundled worker…", flush=True)
    with tempfile.TemporaryDirectory(prefix="serum2vital-smoke-") as temporary:
        temporary_path = Path(temporary)
        output = temporary_path / "output"
        report_path = temporary_path / "report.json"
        result = subprocess.run(
            [
                str(worker),
                *(str(path) for path in fixtures),
                "--out",
                str(output),
                "--no-wavetables",
                "--no-samples",
                "--max-frames",
                "1",
                "--overwrite",
                "--report",
                str(report_path),
                "-v",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "bundled worker smoke test failed\n"
                f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )
        report = json.loads(report_path.read_text(encoding="utf-8"))
        counts = (report["converted"], report["skipped"], report["failed"])
        if counts != (2, 0, 0):
            raise RuntimeError(f"unexpected worker smoke-test report: {report}")
        presets = sorted(output.rglob("*.vital"))
        if len(presets) != 2:
            raise RuntimeError(f"expected two .vital files, found {len(presets)}")
        for preset in presets:
            contents = json.loads(preset.read_text(encoding="utf-8"))
            if "settings" not in contents or "synth_version" not in contents:
                raise RuntimeError(f"invalid Vital preset from smoke test: {preset}")

    print("Smoke-testing the bundled GUI…", flush=True)
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    result = subprocess.run(
        [str(gui), "--smoke-test"],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=45,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "bundled GUI smoke test failed\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

    print("Smoke-testing GUI-to-worker conversion…", flush=True)
    with tempfile.TemporaryDirectory(prefix="serum2vital-gui-smoke-") as temporary:
        output = Path(temporary) / "output"
        result = subprocess.run(
            [str(gui), "--smoke-worker", str(fixtures[0]), str(output)],
            cwd=ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
        )
        presets = list(output.rglob("*.vital"))
        if result.returncode != 0 or len(presets) != 1:
            raise RuntimeError(
                "GUI-to-worker smoke test failed\n"
                f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}\n"
                f"generated presets: {presets}"
            )
        json.loads(presets[0].read_text(encoding="utf-8"))


def _archive(artifact: Path) -> Path:
    PACKAGE_ROOT.mkdir(parents=True, exist_ok=True)
    stem = f"Serum2Vital-{VERSION}-{_platform_tag()}-{_architecture_tag()}"
    if sys.platform == "darwin":
        archive = PACKAGE_ROOT / f"{stem}.zip"
        archive.unlink(missing_ok=True)
        subprocess.run(
            [
                "ditto",
                "-c",
                "-k",
                "--sequesterRsrc",
                "--keepParent",
                str(artifact),
                str(archive),
            ],
            check=True,
        )
    elif sys.platform.startswith("win"):
        archive = PACKAGE_ROOT / f"{stem}.zip"
        archive.unlink(missing_ok=True)
        shutil.make_archive(
            str(archive.with_suffix("")),
            "zip",
            root_dir=artifact.parent,
            base_dir=artifact.name,
        )
    else:
        archive = PACKAGE_ROOT / f"{stem}.tar.gz"
        archive.unlink(missing_ok=True)
        with tarfile.open(archive, "w:gz", format=tarfile.PAX_FORMAT) as output:
            output.add(artifact, arcname=artifact.name, recursive=True)
    return archive


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-smoke-tests",
        action="store_true",
        help="archive without launching the packaged worker and GUI",
    )
    args = parser.parse_args(argv)

    artifact = _build()
    if not args.skip_smoke_tests:
        _run_smoke_tests(artifact)
    archive = _archive(artifact)
    checksum = _sha256(archive)
    checksum_file = archive.with_name(f"{archive.name}.sha256")
    checksum_file.write_text(f"{checksum}  {archive.name}\n", encoding="ascii")
    print(f"Created {archive}")
    print(f"Created {checksum_file}")
    print(f"SHA-256 {checksum}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
