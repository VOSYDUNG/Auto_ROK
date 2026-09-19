# CPU OCR backend experiment

Status: `experiment_only` (2026-09-19, Asia/Ho_Chi_Minh).  The production
Windows OCR bridge is unchanged.

## Why this exists

The fixed Rise of Kingdoms resource-panel coordinates are known.  A full-screen
text detector is unnecessary and can fragment the small stylized labels, so we
screened recognizer-only OCR on those bounded ROIs.  The scripts read persisted
frames, force CPU execution, and emit no keyboard or mouse input.

## Installed backends

- Tesseract OCR 5.4.0 (`C:\Program Files\Tesseract-OCR\tesseract.exe`) was
  installed with WinGet.  It is retained as a baseline and reached 18/100
  exact label/config samples on the first persisted frame.
- `rapidocr_onnxruntime==1.4.4` and its CPU ONNX Runtime dependencies are
  declared in `config/cpu-ocr-requirements.txt` and installed with
  `python -m pip install -r config/cpu-ocr-requirements.txt`.  The experiment
  explicitly disables CUDA and DirectML and records `CPUExecutionProvider`.

## Current result

`workspace/evidence/corpus/rapidocr-corpus-experiment-20260919-03.json` covers
12 persisted `RESOURCE_SEARCH_PANEL` frames and five fixed labels per frame.
RapidOCR recognizer-only mode scores 116/120 exact (0.967); both raw and gray
variants score 58/60.  The only failures are `Logging Cam` on two frames.
All 120 records are bound to the persisted capture hash/frame id and the
central `rok-client-1366x768-cpu-v1` ROI profile.  Median recognition latency
is 15.9 ms per label (p95 18.7 ms) on this CPU run.  The derived corpus now
meets the R1a precision/recall thresholds after independent review; the
backend itself remains experiment-only until a fresh live runtime measurement
is accepted.

## Reproduce

```powershell
python scripts/experiment_rapidocr_corpus.py `
  workspace/evidence/corpus/cpu-observation-corpus-20260918-13.json `
  --output workspace/evidence/corpus/rapidocr-corpus-experiment-20260919-03.json
```

For one capture-bound adapter run:

```powershell
python scripts/run_rapidocr_fixed_roi.py `
  workspace/runs/b002_current_live/rok-client.png `
  --capture workspace/runs/b002_current_live/capture.json `
  --output workspace/evidence/corpus/rapidocr-fixed-roi-current-20260919-03.json
```

The current persisted frame produced five exact category labels with
`capture_binding_verified=true`; see
`workspace/evidence/corpus/rapidocr-fixed-roi-current-20260919-03.json`.

The derived overlay was also run through the existing R1a evaluator after an
independent visual review of all 12 frame-bound PNGs.  It records 58/60 fields
with layout (0.9667 recall) and 56/60 OCR-only (0.9333 recall), with 1.0
precision in both modes; the remaining `Logging Camp` misses are retained
rather than normalized away.  See
`workspace/evidence/corpus/ocr-quality-rapidocr-overlay-20260919-independent.json`
and the review result
`workspace/evidence/corpus/ocr-independent-review-result-20260919.json`.
The same derived files pass the existing observation bridge with 30/30
projections and 30/30 exact state classifications (search holdout 5/5), with
zero input; see
`workspace/evidence/corpus/cpu-observation-corpus-rapidocr-overlay-20260919.json`.

The independent-review packet is
`workspace/evidence/corpus/ocr-independent-review-packet-20260919.json`;
the completed result is
`workspace/evidence/corpus/ocr-independent-review-result-20260919.json`.
The label-lock manifest records the second dated reviewer and all 12 entries
as `independently_locked`.

The live provider now has an explicit opt-in
`ocr_backend=rapidocr_fixed_roi_experiment` (also exposed by
`scripts/run_gather_tick.py --ocr-backend ...`).  The default remains
`windows`; the opt-in keeps Windows OCR as the base payload, overlays only the
fixed category row, and fails closed if the CPU backend or frame hash check
fails.  It is not eligible for armed live use until the promotion gates pass.

Promotion requires an independently locked corpus, a frame-disjoint holdout,
explicit current-frame provenance, the existing precision/recall thresholds,
and a focused runtime replay.  Until those gates pass, this backend remains a
read-only comparator and does not alter `scripts/windows_ocr.ps1`.

The R1a corpus gate is now satisfied by the independently locked derived
report. Runtime promotion is still separate: the current machine has no visible
`MASS.exe` window, so no live RapidOCR observation was started and the default
Windows OCR path remains authoritative.
