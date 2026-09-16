from pathlib import Path

from desktop import build


def test_packaged_executables_are_adjacent_on_windows_and_linux(monkeypatch):
    artifact = Path("/package/Serum2Vital")

    monkeypatch.setattr(build.sys, "platform", "win32")
    assert build._executables(artifact) == (
        artifact / "Serum2Vital.exe",
        artifact / "serum2vital-worker.exe",
    )

    monkeypatch.setattr(build.sys, "platform", "linux")
    assert build._executables(artifact) == (
        artifact / "Serum2Vital",
        artifact / "serum2vital-worker",
    )


def test_packaged_executables_are_adjacent_inside_macos_app(monkeypatch):
    artifact = Path("/package/Serum2Vital.app")
    executable_dir = artifact / "Contents" / "MacOS"
    monkeypatch.setattr(build.sys, "platform", "darwin")

    assert build._executables(artifact) == (
        executable_dir / "Serum2Vital",
        executable_dir / "serum2vital-worker",
    )


def test_architecture_names_are_normalized():
    assert build._architecture_tag("AMD64") == "x86_64"
    assert build._architecture_tag("aarch64") == "arm64"
