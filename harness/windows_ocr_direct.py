"""Call Windows.Media.Ocr from this process instead of through PowerShell.

The old path spawned ``powershell.exe``, loaded WinRT with ``Add-Type``, read a
PNG back off disk, hashed it, and decoded it. Profiled on a real game frame,
73 ms of that 1,036 ms was the actual OCR - seven percent. The rest was the
process boundary and redoing work this process had already done:
``windows_capture_backend`` holds the pixels as a numpy array and has already
computed the sha256 before the PNG is even written.

This module removes the boundary. Same engine, same results - measured at
93 ms against 1,036 ms, with 75 elements matching on text, bbox, line index
and word index.

It also removes an encoding layer that was silently corrupting output.
PowerShell writes stdout in CP437, where byte 0x91 is ``æ``; read back as the
locale default it became a left quote. Nothing here encodes or decodes text at
all - the WinRT string arrives as a Python ``str``.

The emitted structure is byte-compatible with ``scripts/windows_ocr.ps1`` so
consumers do not change.
"""
from __future__ import annotations

import asyncio
import hashlib
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = 1
BACKEND_NAME = "Windows.Media.Ocr"

#: Control characters the PowerShell path stripped from every word, kept so
#: the two paths cannot diverge on a stray glyph.
_CONTROL = frozenset(
    list(range(0x00, 0x09)) + [0x0B, 0x0C] + list(range(0x0E, 0x20))
)


class WindowsOcrError(RuntimeError):
    """Raised when OCR cannot be performed, rather than returning a guess."""


def _require_winrt():
    """Import the WinRT bindings, or explain exactly what is missing."""
    try:
        from winrt.windows.graphics.imaging import (  # noqa: PLC0415
            BitmapPixelFormat,
            SoftwareBitmap,
        )
        from winrt.windows.media.ocr import OcrEngine  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise WindowsOcrError(
            "the winrt bindings are not installed; "
            "pip install '.[observation]' brings in winrt-Windows.Media.Ocr "
            f"and its namespaces ({exc})"
        ) from exc
    return OcrEngine, SoftwareBitmap, BitmapPixelFormat


def _clean(text: str) -> str:
    return "".join(ch for ch in text if ord(ch) not in _CONTROL)


def _os_version() -> str:
    info = sys.getwindowsversion()  # type: ignore[attr-defined]
    return f"{info.major}.{info.minor}.{info.build}.0"


class WindowsOcr:
    """One OCR engine, reused across frames.

    Creating the engine costs about 7 ms and there is no reason to pay it per
    frame; the PowerShell path had no choice because the process died each
    time.
    """

    def __init__(self) -> None:
        engine_cls, bitmap_cls, pixel_format = _require_winrt()
        self._SoftwareBitmap = bitmap_cls
        self._BitmapPixelFormat = pixel_format
        self._engine = engine_cls.try_create_from_user_profile_languages()
        if self._engine is None:
            raise WindowsOcrError(
                "Windows.Media.Ocr has no engine for any user-profile language"
            )

    @property
    def language(self) -> str:
        return self._engine.recognizer_language.language_tag

    def recognize(self, bgra: Any, width: int, height: int) -> list[dict[str, Any]]:
        """Recognize one BGRA8 frame and return elements in client pixels."""
        if width <= 0 or height <= 0:
            raise WindowsOcrError("frame dimensions must be positive")
        buffer = bytes(bgra)
        expected = width * height * 4
        if len(buffer) != expected:
            raise WindowsOcrError(
                f"expected {expected} bytes of BGRA8 for {width}x{height}, got {len(buffer)}"
            )

        async def _run():
            bitmap = self._SoftwareBitmap.create_copy_from_buffer(
                buffer, self._BitmapPixelFormat.BGRA8, width, height
            )
            return await self._engine.recognize_async(bitmap)

        result = asyncio.run(_run())

        elements: list[dict[str, Any]] = []
        for line_index, line in enumerate(result.lines):
            for word_index, word in enumerate(line.words):
                text = _clean(word.text)
                if not text:
                    continue
                box = word.bounding_rect
                elements.append(
                    {
                        "bbox": [
                            int(box.x),
                            int(box.y),
                            int(box.width),
                            int(box.height),
                        ],
                        "word_index": word_index,
                        # Windows.Media.Ocr exposes no per-word confidence.
                        # The PowerShell path emitted null here and consumers
                        # rely on that shape.
                        "confidence": None,
                        "text": text,
                        "line_index": line_index,
                    }
                )
        return elements


def build_payload(
    elements: Sequence[Mapping[str, Any]],
    capture: Mapping[str, Any],
    *,
    image_sha256: str,
    width: int,
    height: int,
    language: str,
    crop: tuple[int, int, int, int] | None = None,
    scale: float = 1.0,
) -> dict[str, Any]:
    """Assemble the record in the shape scripts/windows_ocr.ps1 emitted.

    ``crop`` is in client pixels and ``scale`` is what the crop was magnified
    by before OCR; element boxes stay in scaled-crop pixels, which is what
    ``coordinate_space`` has always declared and what
    ``observation_bridge`` divides back out. Reporting either of them wrongly
    puts every grounded target in the wrong place, so they are computed here
    rather than assumed.
    """
    frame = capture.get("frame") or {}
    box = crop if crop is not None else (0, 0, int(width), int(height))
    return {
        "schema_version": SCHEMA_VERSION,
        "frame_id": frame.get("id"),
        "image_sha256": image_sha256,
        "coordinate_space": "ocr_crop_pixels",
        "output_coordinate_space": "client_pixels",
        "client_bounds": list(frame.get("client_bounds") or [0, 0, width, height]),
        "dpi_scale": frame.get("dpi_scale"),
        "backend": {
            "name": BACKEND_NAME,
            "version": _os_version(),
            "language": language,
        },
        "crop": [int(value) for value in box],
        "scale_x": float(scale),
        "scale_y": float(scale),
        "text": " ".join(str(item["text"]) for item in elements),
        "elements": list(elements),
    }


def recognize_frame(
    bgr: Any,
    capture: Mapping[str, Any],
    *,
    engine: WindowsOcr | None = None,
    png_bytes: bytes | None = None,
    roi: tuple[int, int, int, int] | None = None,
    scale: float = 1.0,
) -> dict[str, Any]:
    """OCR a frame the caller already holds in memory.

    ``bgr`` is the three-channel array the capture backend produces.
    ``png_bytes`` is optional: pass the encoded frame only if the caller wants
    the hash recomputed here, otherwise the hash already in ``capture`` is
    trusted - it was computed from the same pixels moments earlier.

    ``roi`` and ``scale`` exist because whole-frame OCR is not reliable, and
    the way it fails is silent. Measured on 2026-09-20, two 1366x768 frames
    from the same client, same engine, same session:

        world map, whole frame      75 elements
        city view, whole frame       3 elements

    The quest panel is byte-identical in both. Inside the world frame it
    contributes 32 elements; inside the city frame, 0. Cropped out on its own
    it reads 33 in EITHER case. So the busy city background does not obscure
    the text - it makes Windows.Media.Ocr abandon text it reads perfectly
    well when that text is handed over by itself.

    That makes ROI-only reading a correctness requirement rather than the
    performance preference it looks like. docs/DESIGN_BRIEF.md D1b already
    said never to sweep the frame; this is the number behind it.

    Scale is a second, separate effect, and it bites on small regions:

        header strip, scale 1    0 elements     31 ms
        header strip, scale 4    4 elements     16 ms   exact
        whole frame, scale 1.5  63 elements    198 ms   but "1,000" -> "l,cm"
        whole frame, scale 2    64 elements    407 ms   over the OCR-003 budget

    Upscaling a calibrated ROI is both cheaper AND more accurate than
    upscaling the frame, so there is no trade-off to balance. The old
    PowerShell path magnified each region by 3, 4 or 8 for this reason; the
    in-process rewrite kept ``scale_x: 1`` and had no way to express a crop at
    all, which is what this signature adds back.
    """
    import cv2  # noqa: PLC0415 - optional, only needed for the colour convert
    import numpy as np  # noqa: PLC0415

    array = np.ascontiguousarray(bgr)
    if array.ndim != 3 or array.shape[2] not in (3, 4):
        raise WindowsOcrError("expected an HxWx3 or HxWx4 frame")
    height, width = array.shape[:2]

    frame = capture.get("frame") or {}
    declared = (frame.get("width"), frame.get("height"))
    if declared != (None, None) and declared != (width, height):
        raise WindowsOcrError(
            f"frame is {width}x{height} but capture metadata declares {declared}"
        )

    digest = (
        hashlib.sha256(png_bytes).hexdigest()
        if png_bytes is not None
        else str(frame.get("image_sha256") or "")
    )
    if png_bytes is not None and frame.get("image_sha256") not in (None, digest):
        raise WindowsOcrError("image hash does not match capture metadata")

    box = _checked_roi(roi, width, height)
    if not 1.0 <= scale <= 8.0:
        raise WindowsOcrError("scale must be within 1..8")

    crop_x, crop_y, crop_w, crop_h = box
    region = array[crop_y : crop_y + crop_h, crop_x : crop_x + crop_w]
    if scale != 1.0:
        region = cv2.resize(
            region,
            (max(1, round(crop_w * scale)), max(1, round(crop_h * scale))),
            interpolation=cv2.INTER_CUBIC,
        )

    bgra = region if region.shape[2] == 4 else cv2.cvtColor(region, cv2.COLOR_BGR2BGRA)
    bgra = np.ascontiguousarray(bgra)
    ocr = engine or WindowsOcr()
    elements = ocr.recognize(bgra.tobytes(), bgra.shape[1], bgra.shape[0])
    return build_payload(
        elements,
        capture,
        image_sha256=digest,
        width=width,
        height=height,
        language=ocr.language,
        crop=box,
        scale=scale,
    )


def _checked_roi(
    roi: tuple[int, int, int, int] | None, width: int, height: int
) -> tuple[int, int, int, int]:
    """Validate a region, or default to the whole frame.

    A region that runs off the edge is refused rather than clamped. Clamping
    would silently change which pixels were read, and every box that came back
    would map to the wrong place in client coordinates.
    """
    if roi is None:
        return (0, 0, int(width), int(height))
    if len(roi) != 4:
        raise WindowsOcrError("roi must be (x, y, width, height)")
    x, y, w, h = (int(value) for value in roi)
    if w <= 0 or h <= 0:
        raise WindowsOcrError("roi width and height must be positive")
    if x < 0 or y < 0 or x + w > width or y + h > height:
        raise WindowsOcrError(
            f"roi {(x, y, w, h)} does not fit inside the {width}x{height} frame"
        )
    return (x, y, w, h)


#: Regions read in addition to the whole frame on every live observation.
#:
#: A whole-frame sweep is not reliable on this client - it returned 3
#: elements on a city frame and 75 on a world frame, and it caught the
#: dispatch drawer on some ticks and not others. These regions are the ones
#: the state machine depends on, read through their own calibrated scales so
#: they are deterministic rather than lucky.
#:
#: Kept short on purpose. Each OCR call costs about 33 ms of fixed overhead
#: regardless of area, so this list is a latency budget as much as a
#: capability one: three regions plus the frame measures about 277 ms against
#: the 400 ms of OCR-003.
SEMANTIC_REGIONS: tuple[str, ...] = (
    "search_level_strip",
    "troop_drawer_queue",
    "troop_drawer_button",
    "troop_drawer_prompt",
)


def merge_region_elements(
    payload: dict[str, Any],
    region_payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Let a calibrated region replace the whole-frame read of its own area.

    The region's boxes arrive in scaled-crop pixels and are converted to
    client pixels, because downstream reads everything as client pixels and
    two coordinate spaces in one element list is a trap.

    Whole-frame elements inside the region are DROPPED, and every region
    element is appended - none are skipped as duplicates. That matters more
    than it looks. An earlier version deduplicated token by token, and on the
    search panel the whole-frame pass had already found the digit while the
    region supplied the label, so "6" was dropped as a duplicate and "Level:"
    landed at the end of the joined text with nothing after it. The fact
    extractor looks for "Level" followed by a number, so a correct reading of
    a correct panel produced no fact at all.

    Adjacency is part of the reading. Splitting a phrase across two passes
    destroys it, so the region wins its whole area or does not touch it.
    """
    crop = region_payload.get("crop") or [0, 0, 0, 0]
    scale_x = float(region_payload.get("scale_x") or 1.0)
    scale_y = float(region_payload.get("scale_y") or 1.0)
    crop_x, crop_y = int(crop[0]), int(crop[1])
    crop_w, crop_h = int(crop[2]), int(crop[3])

    region_elements = region_payload.get("elements") or []
    if not region_elements:
        # Nothing read here; leave the frame's own view of the area alone
        # rather than blanking it.
        return payload

    def _inside(item: Mapping[str, Any]) -> bool:
        box = item.get("bbox")
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            return False
        centre_x = box[0] + box[2] / 2
        centre_y = box[1] + box[3] / 2
        return (
            crop_x <= centre_x <= crop_x + crop_w
            and crop_y <= centre_y <= crop_y + crop_h
        )

    kept = [item for item in payload["elements"] if not _inside(item)]
    next_line = max((int(i.get("line_index", 0)) for i in kept), default=-1) + 1

    for item in region_elements:
        box = item.get("bbox")
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            continue
        kept.append(
            {
                "bbox": [
                    crop_x + round(box[0] / scale_x),
                    crop_y + round(box[1] / scale_y),
                    max(1, round(box[2] / scale_x)),
                    max(1, round(box[3] / scale_y)),
                ],
                "word_index": int(item.get("word_index", 0)),
                "confidence": None,
                "text": str(item.get("text")),
                "line_index": next_line + int(item.get("line_index", 0)),
            }
        )

    payload["elements"] = kept
    payload["text"] = " ".join(str(item["text"]) for item in kept)
    return payload


def recognize_with_regions(
    image: str | Path,
    capture: Mapping[str, Any],
    *,
    engine: "WindowsOcr | None" = None,
    roi_profile: Any = None,
    regions: Sequence[str] = SEMANTIC_REGIONS,
    window_size: tuple[int, int] | None = None,
) -> dict[str, Any]:
    """Whole-frame OCR plus the calibrated regions the state machine needs.

    The whole-frame pass is kept because it still supplies most text on most
    frames. The regions are added because it cannot be relied on for the few
    strings a decision turns on.

    A region that is not registered, or does not fit this client, is skipped
    rather than raised: a missing region means less evidence, and the
    downstream contract already treats missing evidence as a refusal.
    """
    ocr = engine or WindowsOcr()
    payload = recognize_path(image, capture, engine=ocr)
    if not regions:
        return payload

    if roi_profile is None:
        from harness.cpu_roi import load_default_cpu_roi_profile  # noqa: PLC0415

        roi_profile = load_default_cpu_roi_profile()
    size = window_size or (
        int(payload["crop"][2]),
        int(payload["crop"][3]),
    )
    for roi_id in regions:
        try:
            resolved = roi_profile.resolve(roi_id, size)
            region_payload = recognize_path(
                image,
                capture,
                engine=ocr,
                roi=tuple(resolved.rect.as_list()),
                scale=resolved.ocr_scale,
            )
        except Exception:  # noqa: BLE001 - a missing region is less evidence
            continue
        payload = merge_region_elements(payload, region_payload)
    return payload


def recognize_path(
    image: str | Path,
    capture: Mapping[str, Any],
    *,
    engine: WindowsOcr | None = None,
    roi: tuple[int, int, int, int] | None = None,
    scale: float = 1.0,
) -> dict[str, Any]:
    """OCR a frame already written to disk.

    Kept for replaying stored evidence. The live path should use
    ``recognize_frame`` and never touch the disk at all.
    """
    import cv2  # noqa: PLC0415

    path = Path(image)
    data = path.read_bytes()
    array = cv2.imread(str(path))
    if array is None:
        raise WindowsOcrError(f"could not decode {path}")
    return recognize_frame(
        array, capture, engine=engine, png_bytes=data, roi=roi, scale=scale
    )


__all__ = [
    "BACKEND_NAME",
    "SEMANTIC_REGIONS",
    "merge_region_elements",
    "recognize_with_regions",
    "SCHEMA_VERSION",
    "WindowsOcr",
    "WindowsOcrError",
    "build_payload",
    "recognize_frame",
    "recognize_path",
]
