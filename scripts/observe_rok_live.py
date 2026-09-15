"""Capture the live ROK client, run Windows OCR, then build a G004 scene."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harness.observation_bridge import CandidateSpec, ObservationBridgeError, project_observation  # noqa: E402
from harness.windows_capture_backend import WindowsCaptureError, capture_rok_client  # noqa: E402


def _run_dir(value: str) -> Path:
    path = Path(value).resolve()
    root = (ROOT / "workspace" / "runs").resolve()
    if path == root or not path.is_relative_to(root):
        raise WindowsCaptureError("run-dir must be below workspace/runs")
    return path


def _candidate_specs(path: str | None) -> tuple[CandidateSpec, ...]:
    if path is None:
        return ()
    candidate_path = Path(path).resolve()
    if not candidate_path.is_relative_to(ROOT):
        raise ObservationBridgeError("candidates must be inside this repository")
    value = json.loads(candidate_path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ObservationBridgeError("candidates must contain a JSON list")
    try:
        return tuple(CandidateSpec(item["target_id"], tuple(item["labels"]), item.get("min_confidence", 0.0))
                     for item in value)
    except (KeyError, TypeError) as exc:
        raise ObservationBridgeError("candidate entries require target_id and labels") from exc


def _write_json(path: Path, value: object) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--candidates")
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--max-age-seconds", type=float, default=30.0)
    args = parser.parse_args(argv)
    run_dir: Path | None = None
    stage = "validate_output"
    try:
        run_dir = _run_dir(args.run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        image = run_dir / "rok-client.png"
        capture_path = run_dir / "capture.json"
        ocr_path = run_dir / "ocr.json"
        scene_path = run_dir / "scene.json"

        stage = "capture"
        capture = capture_rok_client(image, timeout_seconds=args.timeout_seconds)
        _write_json(capture_path, capture)
        stage = "ocr"
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
             str(ROOT / "scripts" / "windows_ocr.ps1"), "-Image", str(image),
             "-CaptureMeta", str(capture_path)],
            capture_output=True, text=True, timeout=30, check=False,
        )
        if completed.returncode != 0:
            raise WindowsCaptureError(completed.stderr.strip() or f"Windows OCR exited {completed.returncode}")
        ocr = json.loads(completed.stdout, strict=False)
        _write_json(ocr_path, ocr)
        stage = "projection"
        projected = project_observation(capture, ocr, image, _candidate_specs(args.candidates),
                                        now=datetime.now(timezone.utc), max_age_seconds=args.max_age_seconds)
        _write_json(scene_path, asdict(projected))
        _write_json(run_dir / "run.json", {"schema_version": 1, "status": projected.status,
                    "stage": "complete", "frame_id": capture["frame"]["id"],
                    "image_sha256": capture["frame"]["image_sha256"],
                    "artifacts": {"image": str(image), "capture": str(capture_path),
                                  "ocr": str(ocr_path), "scene": str(scene_path)}, "cost": None})
        print(json.dumps({"status": projected.status, "frame_id": capture["frame"]["id"],
                          "ocr_elements": len(ocr["elements"]), "run_dir": str(run_dir)}))
        return 0 if projected.status == "READY" else 3
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError,
            WindowsCaptureError, ObservationBridgeError, ValueError) as exc:
        if run_dir is not None:
            _write_json(run_dir / "run.json", {"schema_version": 1, "status": "failed", "stage": stage,
                        "error": {"type": type(exc).__name__, "message": str(exc)}, "cost": None})
        print(f"observe-rok-live [{stage}]: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
