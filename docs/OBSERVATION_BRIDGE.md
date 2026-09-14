# Passive observation bridge

`harness/observation_bridge.py` converts persisted target-window capture evidence
and OCR output into the existing `Observation` and `SceneGraph` contracts. It does
not capture the desktop, activate the game, send input, call a model, or calibrate
anchors.

The capture record must identify exactly `Rise of Kingdoms` / `MASS.exe` with
`hwnd` and `pid`, backend name/version, UTC capture time, frame id, client-pixel
bounds, DPI scale, and SHA-256 of the persisted image. OCR must repeat the same
frame id/hash/bounds/DPI, declare bbox source space `ocr_crop_pixels` and output
space `client_pixels`, backend name/version, crop and scale mapping, raw text, and
per-element text/bbox/confidence (confidence may be `null` and remains explicitly
unknown in evidence metadata). The bridge rejects stale, future, unordered, missing-image, hash-mismatched,
cross-window, or out-of-bounds evidence.

Optional candidates are explicit semantic handles, for example:

```json
[{"target_id":"CLAIM_BUTTON","labels":["Claim"],"min_confidence":0.9}]
```

No candidate is inferred automatically. Missing, duplicate, or unknown-confidence
matches return `NEEDS_DECISION`; emitted `VisualTarget` objects cite the same frame
id/hash and detector provenance and remain marked `calibrated_anchor: false`.

```powershell
python scripts/observe_rok_window.py --capture workspace/runs/g004/capture.json `
  --ocr workspace/runs/g004/ocr.json --image workspace/runs/g004/frame.png `
  --candidates workspace/runs/g004/candidates.json `
  --output workspace/runs/g004/scene.json
```

The CLI only accepts repository-local inputs and output. Exit code `0` means a
ready projection, `3` means bounded uncertainty (`NEEDS_DECISION`), and `2` means
invalid evidence. Acquisition backends must generate the records above; the bridge
does not treat a synthetic fixture as live capture proof.
