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

The main-view detector then processes only the validated client-relative
`signature_canvas` ROI from `config/cpu_rois.yaml`.  Its grayscale/edge
features run with OpenCL and CUDA disabled; the ROI is a processing boundary,
not a click coordinate.

## New Troop OCR holdout

On the real 1366×768 client, Windows.Media.Ocr can omit the small `Units` word
in the New Troop summary while still returning `New Troop`, `MARCH` and
`Total Power`. `scripts/windows_ocr.ps1` now enables a bounded CPU-only crop
`[600,450,435,185]` at scale 4 when the current frame has the New Troop/MARCH
anchors. Returned boxes are mapped back to client pixels, deduplicated against
the full-frame pass, and tagged `ocr_new_troop_summary_region`; no semantic
target or coordinate is compiled from the crop. This repaired the live
`gather-goal-20260919-04` occurrence without weakening the fail-closed state or
target rules.

For the bounded CPU OCR experiment, `run_gather_tick.py` accepts
`--ocr-backend rapidocr_fixed_roi_experiment`.  This keeps the Windows OCR
payload as the base, overlays only the fixed resource-category row, verifies
the same frame hash, and records `CPUExecutionProvider`; the default backend
remains `windows`, and the optional path is fail-closed and not an armed-live
promotion.

Primary sources:

- https://pypi.org/project/windows-capture/2.0.1/
- https://github.com/NiiightmareXD/windows-capture/blob/main/windows-capture-python/windows_capture/__init__.py
- https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-getclientrect
- https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-clienttoscreen
