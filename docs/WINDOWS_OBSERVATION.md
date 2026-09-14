# Windows 10 passive ROK observation

`harness/windows_capture_backend.py` captures one frame from the uniquely
rediscovered `Rise of Kingdoms` / `MASS.exe` HWND. It never selects a monitor,
desktop, window-name substring, or DXGI duplication fallback. All optional
Windows Graphics Capture settings remain `None`, meaning OS default; in
particular `draw_border=None` does not claim borderless capture and avoids
calling the unsupported `IsBorderRequired` setter on this Windows 10 host.

The callback copies the native zero-copy frame before returning, stops after
one frame, maps it to verified physical client pixels, rejects blank output,
then atomically persists the PNG. Target identity, window/client geometry, and
DPI must match before and after capture. Metadata hashes the persisted PNG and
records the frame callback UTC time, HWND/PID/executable, source-frame crop,
backend version, quality, and non-interference settings.

`scripts/windows_ocr.ps1` verifies the same PNG hash and dimensions before
Windows.Media.Ocr. It emits raw text plus client-pixel bboxes with confidence
`null`, engine version and language. `scripts/observe_rok_live.py` feeds those
records directly into the accepted G004 bridge. Without explicit candidate
definitions, OCR evidence is useful but no semantic `VisualTarget` is invented.

Install into an isolated environment and run:

```powershell
python -m venv workspace/runs/g005-venv
workspace/runs/g005-venv/Scripts/python -m pip install -r config/observation-requirements.txt
workspace/runs/g005-venv/Scripts/python scripts/observe_rok_live.py `
  --run-dir workspace/runs/g005-live
```

The run directory contains `rok-client.png`, `capture.json`, `ocr.json`,
`scene.json`, and `run.json`. Exit `0` is a valid projection, `3` is
`NEEDS_DECISION`, and `2` is a failed stage with exact error evidence.

Primary sources:

- https://pypi.org/project/windows-capture/2.0.1/
- https://github.com/NiiightmareXD/windows-capture/blob/main/windows-capture-python/windows_capture/__init__.py
- https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-getclientrect
- https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-clienttoscreen
