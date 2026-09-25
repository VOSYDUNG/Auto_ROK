"""Add operator-labelled queue glyphs from a native passive capture.json.

The capture must be produced by scripts/observe_rok_live.py, with a matching
PNG beside it. Training is offline and commits only after the candidate reader
returns the operator's stated queue value. Capture metadata binds the image;
the operator remains responsible for the visual label.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harness.queue_indicator import (  # noqa: E402
    QueueIndicatorProfile,
    QueueIndicatorReader,
    QueueReadStatus,
)

PROFILE = ROOT / "config" / "queue_indicator_profile.json"
VALUE_RE = re.compile(r"^[0-5]/5$")


def _verified_frame(
    manifest_path: Path, frame_path: Path, client_size: tuple[int, int]
) -> tuple[bytes, str]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest_path.name != "capture.json":
        raise ValueError("--manifest must be native capture.json")
    if manifest.get("schema_version") != 1 or manifest.get("status") != "captured":
        raise ValueError("capture.json must report a captured frame")
    frame = manifest.get("frame")
    if not isinstance(frame, dict):
        raise ValueError("capture.json needs a frame object")
    frame_id = frame.get("id")
    digest = frame.get("image_sha256")
    if not isinstance(frame_id, str) or not frame_id.strip():
        raise ValueError("capture frame needs a nonempty id")
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-fA-F]{64}", digest) is None:
        raise ValueError("capture frame needs image_sha256")
    captured_at = frame.get("captured_at")
    if not isinstance(captured_at, str):
        raise ValueError("capture frame needs captured_at")
    try:
        parsed_time = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("capture frame has invalid captured_at") from exc
    if parsed_time.tzinfo is None:
        raise ValueError("capture frame captured_at needs a timezone")
    if (frame.get("width"), frame.get("height")) != client_size:
        raise ValueError("capture frame dimensions differ from the profile")
    png = manifest.get("png")
    if not isinstance(png, str) or not png:
        raise ValueError("capture.json needs a PNG path")
    if Path(png).resolve() != frame_path.resolve() or frame_path.parent.resolve() != manifest_path.parent.resolve():
        raise ValueError("--frame does not match the native capture PNG")
    if frame_path.suffix.lower() != ".png":
        raise ValueError("queue training requires a PNG capture")
    target = manifest.get("target")
    before = manifest.get("pre_capture")
    after = manifest.get("post_capture")
    identity = ("hwnd", "pid", "title", "exe", "process_path")
    if not all(isinstance(item, dict) for item in (target, before, after)):
        raise ValueError("capture.json needs target and pre/post capture bindings")
    if not all(target.get(key) == before.get(key) == after.get(key) and target.get(key) is not None for key in identity):
        raise ValueError("capture target identity differs across pre/post snapshots")
    if before.get("client_size") != list(client_size) or after.get("client_size") != list(client_size):
        raise ValueError("capture client size differs across pre/post snapshots")
    non_interference = manifest.get("non_interference")
    flags = ("foreground_activation", "mouse_input", "keyboard_input", "desktop_fallback")
    if not isinstance(non_interference, dict) or any(non_interference.get(key) is not False for key in flags):
        raise ValueError("capture non_interference flags must all be false")
    frame_bytes = frame_path.read_bytes()
    if not frame_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("capture is not PNG data")
    if hashlib.sha256(frame_bytes).hexdigest() != digest.lower():
        raise ValueError("frame SHA-256 differs from the capture manifest")
    return frame_bytes, frame_id


def _atomic_profile_update(path: Path, original: bytes, candidate: bytes) -> None:
    """Replace only the profile that was read; never expose partial JSON."""
    temporary: Path | None = None
    lock_path = path.with_name(path.name + ".lock")
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f".{path.name}.",
            suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(candidate)
            stream.flush()
            os.fsync(stream.fileno())
        if path.read_bytes() != original:
            raise ValueError("profile changed during training; refusing to overwrite it")
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        os.close(lock_fd)
        lock_path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frame", required=True, help="captured 1366x768 PNG")
    parser.add_argument("--manifest", required=True, help="native capture.json binding the PNG")
    parser.add_argument("--value", required=True, help="operator-stated queue, e.g. 2/5")
    parser.add_argument("--replace", action="store_true", help="replace old samples for observed labels")
    parser.add_argument("--profile", default=str(PROFILE))
    args = parser.parse_args(argv)

    if VALUE_RE.fullmatch(args.value) is None:
        print("--value must be one of 0/5 through 5/5", file=sys.stderr)
        return 2
    labels = [args.value[0], "/", "5"]
    profile_path = Path(args.profile)
    try:
        original = profile_path.read_bytes()
        raw = json.loads(original)
        profile = QueueIndicatorProfile.from_mapping(raw)
        frame_path = Path(args.frame)
        frame_bytes, frame_id = _verified_frame(
            Path(args.manifest), frame_path, profile.client_size
        )

        import cv2
        import numpy as np

        image = cv2.imdecode(np.frombuffer(frame_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("could not decode captured PNG")
        height, width = image.shape[:2]
        if (width, height) != profile.client_size:
            raise ValueError(f"frame is {width}x{height}; expected {profile.client_size}")
        grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        x, y, roi_w, roi_h = profile.roi
        mask = (grey[y:y + roi_h, x:x + roi_w] >= profile.threshold).astype("uint8")
        boxes = QueueIndicatorReader(profile)._segment(mask, origin=(x, y))
        if len(boxes) != 3:
            raise ValueError(f"queue ROI segmented {len(boxes)} glyphs; expected three")

        glyphs = dict(raw.get("glyphs") or {})
        added: list[str] = []
        for label, box in zip(labels, boxes):
            pattern = list(box.pattern)
            known = glyphs.get(label)
            samples = (
                [] if known is None else
                (known if isinstance(known[0], list) else [known])
            )
            if args.replace:
                updated = [pattern]
            elif pattern in samples:
                updated = samples
            else:
                updated = samples + [pattern]
            if updated != samples:
                glyphs[label] = updated
                added.append(label)

        candidate = dict(raw)
        candidate["glyphs"] = glyphs
        reading = QueueIndicatorReader(QueueIndicatorProfile.from_mapping(candidate)).read(grey)
        if reading.status is not QueueReadStatus.READ or (
            reading.used, reading.capacity
        ) != (int(labels[0]), 5):
            raise ValueError(
                f"candidate reader refused {args.value}: "
                f"{reading.status.value} {reading.reason}"
            )
        if not added:
            print(f"{args.value} already reads correctly; nothing to add")
            return 0

        trained = dict(raw.get("trained_from") or {})
        trained[args.value] = frame_path.name
        candidate["trained_from"] = trained
        sources = dict(raw.get("training_sources") or {})
        sources[args.value] = {
            "frame_id": frame_id,
            "frame_path": str(frame_path.resolve()),
            "frame_sha256": hashlib.sha256(frame_bytes).hexdigest(),
            "manifest_path": str(Path(args.manifest).resolve()),
        }
        candidate["training_sources"] = sources
        _atomic_profile_update(
            profile_path, original,
            (json.dumps(candidate, indent=2) + "\n").encode("utf-8"),
        )
        print(f"added: {', '.join(added)}; frame {frame_id}; reads {args.value}")
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"training refused: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
