# CPU-only ROK visual regions

`config/cpu_rois.yaml` is the single processing-region profile for the current
1366×768 ROK client.  Its rectangles are client-relative windows used to reduce
OCR/vision work; they are never action targets and never authorize input.

The `signature_canvas` ROI excludes the resource bar, quest/chat text and bottom
controls.  `harness/cpu_roi.py` scales it only when the current client keeps the
trained aspect ratio, records the resolved client-pixel rectangle, and rejects
an implausible resize instead of silently distorting the evidence.

Feature extraction uses OpenCV's grayscale/edge routines with OpenCL disabled
and no CUDA path.  The game capture API and Windows OCR remain acquisition
adapters; this contract covers the project-owned image processing, not a claim
about undocumented implementation details inside the operating system.

## Current calibration

The original HSV signature was sensitive to the darkened live city frame and
selected `WORLD_MAP_VIEW`.  The current profile uses normalized grayscale
intensity plus Canny edge density over `signature_canvas`, trained on the
operator-labelled city/world frames already in `workspace/evidence/main_view`.
The acceptance radius was widened only to cover the observed lighting shift;
foreground panels and unknown crops still fail closed.

For the fixed search panel, Windows OCR may miss the stylized `SEARCH`
button and small bottom category labels. `scripts/windows_ocr.ps1` therefore
requires the in-panel `Barbarians` + `Level:` anchor before running bounded
panel/category-row crops. Malformed crop tokens remain in the audit stream but
are marked `semantic_excluded`; only missing labels receive explicitly marked
`compiled_ui_layout` fallback anchors. These are layout-derived grounding aids,
not raw OCR accuracy claims.

## Boundary to the local LLM

The local model receives the resulting symbolic state, visible facts, candidate
IDs and frame/provenance metadata.  It does not receive the ROI as a free-form
coordinate plan, hidden game state or an instruction to run a tool.  A model
choice must still match one existing candidate and pass the mission/policy
guard.

## Vision benchmark

Run the read-only benchmark against a captured frame:

```powershell
python scripts/benchmark_cpu_vision.py workspace/runs/<run>/current.png
```

The report separates CPU signature time from capture/OCR/LLM time and records
that no input was emitted.  A C/C++ implementation is justified only if this
measured signature step is the bottleneck; the current OpenCV operations are
already native code called from the Python orchestration layer.

Critical-field OCR screening is reproducible with:

```powershell
python scripts/evaluate_ocr_quality.py --report-id ocr-quality-<run-id>
```

Its CER/WER scope is the declared SEARCH/category fields only; it is not a
claim about the full-frame OCR transcript.  The bound labels are now locked by
an independent visual review; the remaining promotion edge is a fresh live
runtime remeasurement of the optional backend.

The diagnostic `scripts/experiment_ocr_preprocess.ps1` tried per-label CPU
grayscale/threshold crops against a real search-panel frame. It remains
`experiment_only`: the variants did not reach the exact OCR threshold and
must not be promoted into runtime grounding or the R1a report.

The optional `harness/rapidocr_fixed_roi.py` adapter now consumes the same
fixed category ROIs with RapidOCR recognizer-only mode and
`CPUExecutionProvider`; it does not run full-screen detection or emit input.
Its derived overlay reaches 56/60 OCR-only fields (0.933 recall, 1.0
precision) on the current 12-frame screen. Labels are independently locked;
the adapter remains experiment-only until the runtime provenance path is
accepted.

For the live march counter, the logical profile remains the compact
`[1240,110,125,50]` indicator. Windows OCR acquires an enlarged bounded crop
`[1200,90,166,100]` to survive small-digit loss; the optional Tesseract CPU
fallback reads only `[1275,120,91,30]` and accepts a bounded exact `Queue N/M`.
Both crops remain observation-only and preserve `ocr_march_queue_region`
provenance; neither is an input target.

The latest unarmed live timing sample (`workspace/runs/live-timing-20260918-01`)
measured capture 438 ms, Windows OCR 1,084 ms, projection 9.6 ms and 1,537 ms
total.  These timings are observational only; they do not assert how the
Windows OCR implementation allocates work internally.  The local-LLM canary
remains much slower than the CPU ROI step.
