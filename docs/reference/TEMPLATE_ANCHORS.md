# Current-frame template anchor

G006 defines one read-only landmark: `WORLD_MAP_BUTTON`, the round map control
labelled `Space`. Its local reference crop excludes chat, player/resource text,
notification badges, and other personal or changing data.

Calibration records the template byte SHA-256, source frame id/hash, audit-only
source crop, exact 1366x768/DPI layout profile, calibration id, and the SHA-256
of `config/ui_landmarks.json`. Resolution reloads that policy and rejects a
changed algorithm, threshold, margin, anchor id or label. The template path must
resolve below `workspace/runs`, including after symlink resolution.

The matcher applies the locked `grayscale_laplacian_abs_v1` representation to
both the stored crop and the current full frame, then uses OpenCV
`TM_CCOEFF_NORMED`. It makes the fixed control outline less sensitive to the
observed day/night luminance change; it is not a learned model and it does not
turn correlation into a probability. `match_score` is normalized correlation,
not a calibrated probability. A target requires score >= 0.90 and
a >= 0.12 margin over the strongest result outside a one-template-size NMS
region. The resolved bbox comes only from the current full-frame search. The
reference bbox is never replayed. `VisualTarget.confidence` remains `0.0` so
existing action gates cannot treat the correlation score as probability.

```powershell
workspace/runs/g005-venv/Scripts/python scripts/ground_rok_landmark.py calibrate `
  --reference-run workspace/runs/g006-reference `
  --output-dir workspace/runs/g006-calibration-world-map `
  --bbox 1280,690,82,74

workspace/runs/g005-venv/Scripts/python scripts/ground_rok_landmark.py observe `
  --calibration workspace/runs/g006-calibration-world-map/calibration.json `
  --run-dir workspace/runs/g006-holdout
```

The first distinct daylight holdout resolved the current map control with score
0.998265 and runner-up margin 0.619815. A later nighttime frame scored 0.880735
and correctly returned `NEEDS_DECISION` under the unchanged 0.90 policy. This is
same-layout, same-control evidence only; lighting robustness and action safety
remain separate gates.

G007 freezes `grayscale_laplacian_abs_v1` in `config/ui_landmarks.json` before
its first fresh observation. Its calibration crop is still only the G006
training frame. The fresh, HWND-bound 1366x768 night frame
`g007-final/rok-client.png` resolved at 0.947898 with a 0.632034 distinct
runner-up margin; `annotated.png`, `capture.json`, and `candidates.json` retain
the image hash and evidence. This is one positive day/night pilot, not the
20-frame / five-state release gate, and `VisualTarget.confidence` remains 0.0
until a separately calibrated confidence policy exists.
