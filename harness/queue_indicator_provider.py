"""Supply the march-queue fact from the template reader instead of OCR.

This replaces a block in ``scripts/windows_ocr.ps1`` that ran on every frame,
unconditionally, and tried to read the same indicator by cropping it, scaling
it six times, running a per-pixel luminance loop in PowerShell, and then
shelling out to Tesseract.

Measured on 2026-09-20 against a real world-map frame:

    with that block      4,021 ms
    without it             990 ms
    the block cost       3,031 ms - 75% of the whole OCR pass

and the emitted elements were byte-identical either way, because the block
never succeeded. Three seconds a frame for nothing.

``harness/queue_indicator.py`` reads the same indicator in 0.207 ms and either
returns the value or refuses. This provider puts that reading back into the
observation under the acquisition tag ``ocr_march_queue_region``, which is the
tag ``gather_facts.extract_march_queue`` already requires - so the downstream
contract does not change, only the sensor behind it.

It attaches nothing when the reader refuses. A missing queue fact is a state
the harness already handles; a wrong one is not.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from harness.contracts import Evidence
from harness.mission_runtime import MissionContext
from harness.mission_tool import ObservationBundle, ObservationProvider
from harness.queue_indicator import (
    QueueIndicatorError,
    QueueIndicatorProfile,
    QueueIndicatorReader,
    QueueReadStatus,
)

#: Acquisition tag the downstream fact extractor already gates on.
QUEUE_ACQUISITION = "ocr_march_queue_region"


class QueueIndicatorObservationProvider:
    """Decorate an observation with the march-queue reading."""

    def __init__(
        self,
        inner: ObservationProvider,
        profile: QueueIndicatorProfile | str | Path,
        *,
        frame_loader: Any | None = None,
    ) -> None:
        self.inner = inner
        self.profile = (
            profile
            if isinstance(profile, QueueIndicatorProfile)
            else QueueIndicatorProfile.load(profile)
        )
        self.reader = QueueIndicatorReader(self.profile)
        self._load_frame = frame_loader or _load_grayscale
        self.last_status: str | None = None
        self.last_reason: str = ""

    def observe(self, context: MissionContext) -> ObservationBundle:
        bundle = self.inner.observe(context)
        image = _frame_path(bundle)
        if image is None:
            self.last_status = "NO_FRAME"
            self.last_reason = "observation carried no image path"
            return bundle

        try:
            gray = self._load_frame(image)
        except Exception as exc:  # noqa: BLE001 - a sensor that cannot read says so
            self.last_status = "UNREADABLE"
            self.last_reason = f"{type(exc).__name__}: {exc}"
            return bundle

        try:
            reading = self.reader.read(gray)
        except QueueIndicatorError as exc:
            self.last_status = "CONTRACT"
            self.last_reason = str(exc)
            return bundle

        self.last_status = reading.status.value
        self.last_reason = reading.reason
        if reading.status is not QueueReadStatus.READ:
            # Refusing is the designed outcome, not a failure to paper over.
            return bundle

        evidence = Evidence(
            source="queue_indicator_template",
            label=f"{reading.used}/{reading.capacity}",
            confidence=1.0,
            value=f"{reading.used}/{reading.capacity}",
            metadata={
                "acquisition": QUEUE_ACQUISITION,
                "reader": "template",
                "roi": list(self.profile.roi),
                "frame_id": bundle.observation.frame_id,
            },
        )
        return ObservationBundle(
            replace(
                bundle.observation,
                evidence=tuple(bundle.observation.evidence) + (evidence,),
            ),
            bundle.scene,
        )


def _frame_path(bundle: ObservationBundle) -> Path | None:
    for key in ("image_path", "png", "frame_path"):
        value = bundle.scene.facts.get(key)
        if isinstance(value, str) and value:
            candidate = Path(value)
            if candidate.exists():
                return candidate
    return None


def _load_grayscale(path: Path):
    """Read one frame as single-channel grey.

    Imported lazily so the module stays importable, and testable, on a machine
    without OpenCV.
    """
    import cv2

    image = cv2.imread(str(path))
    if image is None:
        raise QueueIndicatorError(f"could not read frame at {path}")
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


__all__ = ["QUEUE_ACQUISITION", "QueueIndicatorObservationProvider"]
