"""Capture one passive HWND-bound Rise of Kingdoms client frame."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harness.windows_capture_backend import WindowsCaptureError, capture_rok_client  # noqa: E402


def _run_path(value: str, label: str) -> Path:
    path = Path(value).resolve()
    root = (ROOT / "workspace" / "runs").resolve()
    if path == root or not path.is_relative_to(root):
        raise WindowsCaptureError(f"{label} must be a file under workspace/runs")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--meta", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    args = parser.parse_args(argv)
    meta: Path | None = None
    try:
        output = _run_path(args.output, "output")
        meta = _run_path(args.meta, "meta")
        if output == meta:
            raise WindowsCaptureError("output and meta paths must differ")
        result = capture_rok_client(output, timeout_seconds=args.timeout_seconds)
        meta.parent.mkdir(parents=True, exist_ok=True)
        meta.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": "captured", "png": str(output), "meta": str(meta),
                          "frame_id": result["frame"]["id"]}))
        return 0
    except (OSError, WindowsCaptureError) as exc:
        if meta is not None:
            meta.parent.mkdir(parents=True, exist_ok=True)
            meta.write_text(json.dumps({"schema_version": 1, "status": "failed",
                                        "error": {"type": type(exc).__name__, "message": str(exc)},
                                        "png_created": False}, indent=2) + "\n", encoding="utf-8")
        print(f"capture-rok-observation: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
