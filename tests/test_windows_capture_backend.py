from pathlib import Path

import pytest

from harness.windows_capture_backend import WindowsCaptureError, _capture_options, _same_binding
from scripts.observe_rok_live import _run_dir


def binding() -> dict:
    return {"hwnd": 101, "pid": 202, "title": "Rise of Kingdoms", "exe": "MASS.exe",
            "process_path": r"C:\Games\MASS.exe", "window_rect": [0, 0, 1366, 768],
            "client_screen_rect": [0, 0, 1366, 768], "client_size": [1366, 768],
            "dpi": 96, "dpi_scale": 1.0}


def test_capture_options_are_hwnd_only_with_os_defaults() -> None:
    assert _capture_options(101) == {
        "cursor_capture": None,
        "draw_border": None,
        "secondary_window": None,
        "minimum_update_interval": None,
        "dirty_region": None,
        "window_hwnd": 101,
    }
    assert "window_name" not in _capture_options(101)
    assert "monitor_index" not in _capture_options(101)
    with pytest.raises(WindowsCaptureError, match="positive integer"):
        _capture_options(0)


def test_pre_post_binding_rejects_geometry_or_identity_change() -> None:
    before = binding()
    assert _same_binding(before, dict(before))
    changed = dict(before)
    changed["client_size"] = [1280, 720]
    assert not _same_binding(before, changed)
    changed = dict(before)
    changed["pid"] = 999
    assert not _same_binding(before, changed)


def test_live_cli_output_is_confined_to_workspace_runs() -> None:
    root = Path(__file__).resolve().parents[1]
    accepted = _run_dir(str(root / "workspace" / "runs" / "g005-test"))
    assert accepted.is_relative_to((root / "workspace" / "runs").resolve())
    with pytest.raises(WindowsCaptureError, match="workspace/runs"):
        _run_dir(str(root / "harness"))
