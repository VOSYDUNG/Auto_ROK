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
) -> dict[str, Any]:
    """Assemble the record in the shape scripts/windows_ocr.ps1 emitted."""
    frame = capture.get("frame") or {}
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
        "crop": [0, 0, int(width), int(height)],
        "scale_x": 1.0,
        "scale_y": 1.0,
        "text": " ".join(str(item["text"]) for item in elements),
        "elements": list(elements),
    }


def recognize_frame(
    bgr: Any,
    capture: Mapping[str, Any],
    *,
    engine: WindowsOcr | None = None,
    png_bytes: bytes | None = None,
) -> dict[str, Any]:
    """OCR a frame the caller already holds in memory.

    ``bgr`` is the three-channel array the capture backend produces.
    ``png_bytes`` is optional: pass the encoded frame only if the caller wants
    the hash recomputed here, otherwise the hash already in ``capture`` is
    trusted - it was computed from the same pixels moments earlier.
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

    bgra = array if array.shape[2] == 4 else cv2.cvtColor(array, cv2.COLOR_BGR2BGRA)
    ocr = engine or WindowsOcr()
    elements = ocr.recognize(
        np.ascontiguousarray(bgra).tobytes(), width, height
    )
    return build_payload(
        elements,
        capture,
        image_sha256=digest,
        width=width,
        height=height,
        language=ocr.language,
    )


def recognize_path(
    image: str | Path,
    capture: Mapping[str, Any],
    *,
    engine: WindowsOcr | None = None,
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
    return recognize_frame(array, capture, engine=engine, png_bytes=data)


__all__ = [
    "BACKEND_NAME",
    "SCHEMA_VERSION",
    "WindowsOcr",
    "WindowsOcrError",
    "build_payload",
    "recognize_frame",
    "recognize_path",
]
