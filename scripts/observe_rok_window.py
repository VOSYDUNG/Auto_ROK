"""Validate passive ROK capture/OCR evidence and emit a frame-scoped scene."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harness.observation_bridge import (  # noqa: E402
    CandidateSpec,
    ObservationBridgeError,
    project_observation,
)


def _inside_repo(value: str, label: str) -> Path:
    path = Path(value).resolve()
    if not path.is_relative_to(ROOT):
        raise ObservationBridgeError(f"{label} must be inside this repository")
    return path


def _output_path(value: str) -> Path:
    path = Path(value).resolve()
    output_root = (ROOT / "workspace" / "runs").resolve()
    if path == output_root or not path.is_relative_to(output_root):
        raise ObservationBridgeError("output must be a file under workspace/runs")
    return path


def _load(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _specs(value: object) -> tuple[CandidateSpec, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ObservationBridgeError("candidate file must contain a JSON list")
    try:
        return tuple(CandidateSpec(item["target_id"], tuple(item["labels"]), item.get("min_confidence", 0.0)) for item in value)
    except (KeyError, TypeError) as exc:
        raise ObservationBridgeError("candidate entries require target_id and labels") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", required=True, help="successful target-only capture metadata JSON")
    parser.add_argument("--ocr", required=True, help="OCR JSON bound to the capture frame")
    parser.add_argument("--image", required=True, help="persisted captured image")
    parser.add_argument("--candidates", help="optional semantic candidate definitions JSON")
    parser.add_argument("--output", required=True, help="scene result JSON (repository-local)")
    parser.add_argument("--max-age-seconds", type=float, default=10.0)
    parser.add_argument("--now", help="test/replay time; live use should omit")
    args = parser.parse_args(argv)
    output: Path | None = None
    try:
        capture_path = _inside_repo(args.capture, "capture")
        ocr_path = _inside_repo(args.ocr, "ocr")
        image_path = _inside_repo(args.image, "image")
        output = _output_path(args.output)
        candidates = _specs(_load(_inside_repo(args.candidates, "candidates"))) if args.candidates else ()
        now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else None
        result = project_observation(_load(capture_path), _load(ocr_path), image_path, candidates,
                                     now=now, max_age_seconds=args.max_age_seconds)
        payload = asdict(result)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps({"status": result.status, "output": str(output), "frame_id": result.scene.frame_id if result.scene else None}))
        return 0 if result.status == "READY" else 3
    except (OSError, json.JSONDecodeError, ObservationBridgeError, ValueError) as exc:
        payload = {"status": "INVALID_EVIDENCE", "error": {"type": type(exc).__name__, "message": str(exc)}}
        if output is not None:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"observe-rok: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
