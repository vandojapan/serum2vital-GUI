from pathlib import Path

import pytest

from serum2vital.gui import (
    LAYOUT_FLATTEN,
    LAYOUT_ORGANIZE,
    ProgressLine,
    build_cli_arguments,
    parse_progress_line,
    worker_python_executable,
)


def test_build_cli_arguments_maps_every_gui_option():
    arguments = build_cli_arguments(
        [Path("/presets/one.fxp"), "/presets/two.SerumPreset"],
        Path("/vital/out"),
        serum_root=Path("/serum/data"),
        layout=LAYOUT_ORGANIZE,
        include_wavetables=False,
        include_samples=False,
        overwrite=True,
        max_frames=16,
    )

    assert arguments[:3] == ["-u", "-m", "serum2vital"]
    assert arguments[3:5] == ["/presets/one.fxp", "/presets/two.SerumPreset"]
    assert arguments[-1] == "-v"
    assert arguments[arguments.index("--out") + 1] == "/vital/out"
    assert arguments[arguments.index("--serum-root") + 1] == "/serum/data"
    assert arguments[arguments.index("--max-frames") + 1] == "16"
    assert "--organize" in arguments
    assert "--no-wavetables" in arguments
    assert "--no-samples" in arguments
    assert "--overwrite" in arguments


def test_build_cli_arguments_uses_only_one_layout_flag():
    flattened = build_cli_arguments(["/presets"], "/out", layout=LAYOUT_FLATTEN)
    preserved = build_cli_arguments(["/presets"], "/out")

    assert "--flatten" in flattened
    assert "--organize" not in flattened
    assert "--flatten" not in preserved
    assert "--organize" not in preserved


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"inputs": [], "output": "/out"}, "input"),
        ({"inputs": ["/presets"], "output": ""}, "output"),
        ({"inputs": ["/presets"], "output": "/out", "layout": "other"}, "layout"),
        ({"inputs": ["/presets"], "output": "/out", "max_frames": 0}, "max_frames"),
    ],
)
def test_build_cli_arguments_rejects_invalid_values(kwargs, message):
    with pytest.raises(ValueError, match=message):
        build_cli_arguments(**kwargs)


def test_parse_progress_line():
    assert parse_progress_line("[12/84] skipped Bass.fxp output exists") == ProgressLine(
        current=12,
        total=84,
        status="skipped",
        detail="Bass.fxp output exists",
    )
    assert parse_progress_line("84 converted, 0 skipped, 0 failed (of 84)") is None


def test_worker_uses_console_python_for_windows_gui_launcher(tmp_path):
    pythonw = tmp_path / "pythonw.exe"
    python = tmp_path / "python.exe"
    pythonw.touch()
    python.touch()

    assert worker_python_executable(pythonw, platform="win32") == str(python)
    assert worker_python_executable(pythonw, platform="darwin") == str(pythonw)
