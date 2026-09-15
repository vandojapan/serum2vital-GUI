import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_windows_launcher_has_resolved_labels_and_required_probes():
    launcher = (ROOT / "Serum2Vital.cmd").read_text(encoding="ascii")
    labels = {
        match.group(1).lower()
        for match in re.finditer(r"^:([A-Za-z0-9_]+)\s*$", launcher, re.MULTILINE)
    }
    targets = {
        match.group(1).lower()
        for match in re.finditer(r"\bgoto\s+:?([A-Za-z0-9_]+)", launcher, re.IGNORECASE)
    }

    assert targets <= labels
    assert "EnableExtensions DisableDelayedExpansion" in launcher
    assert ".venv\\Scripts\\python.exe" in launcher
    assert "import PySide6, serum2vital.gui" in launcher
    assert "pythonw.exe" in launcher
    assert "pyw.exe" in launcher
    lines = [line.strip() for line in launcher.splitlines()]
    start_lines = [index for index, line in enumerate(lines) if line.startswith('start "" ')]
    assert len(start_lines) == 4
    assert all(lines[index - 1] == '"%ComSpec%" /d /c exit 0' for index in start_lines)


def test_windows_launcher_is_configured_for_crlf_checkouts():
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "*.cmd text eol=crlf" in attributes.splitlines()
