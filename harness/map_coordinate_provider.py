"""Attach the coordinate readout to an observation, when it is really there.

This is the second route to WORLD_MAP_VIEW. It reads one calibrated corner of
the frame and, only on a confident read, adds a single piece of evidence
saying what it saw. It never adds the visual detector's HUD phrases: it did
not look at the HUD.

Foreground suppression is repeated here rather than inherited. The coordinate
widget is already hidden behind every open panel, so in practice the two
agree - but STA-004 says a foreground surface suppresses background state,
and a sensor that relies on the client happening to hide its own widget is
relying on the client, not on a rule.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from harness.contracts import Evidence
from harness.cpu_roi import CpuRoiError, CpuRoiProfile, load_default_cpu_roi_profile
from harness.map_coordinate import (
    COORDINATE_EVIDENCE,
    ROI_ID,
    CoordinateStatus,
    MapCoordinateReader,
    reader_from_profile,
)
from harness.mission_runtime import MissionContext
from harness.mission_tool import ObservationBundle, ObservationProvider

#: Same markers main_view_detector suppresses on. Kept in one list there and
#: imported here so the two cannot drift.
from harness.main_view_detector import _FOREGROUND_MARKERS, _visible_markers  # noqa: E402


class MapCoordinateObservationProvider:
    """Decorate an observation with the world-map coordinate reading."""

    def __init__(
        self,
        inner: ObservationProvider,
        *,
        roi_profile: CpuRoiProfile | None = None,
        reader: MapCoordinateReader | None = None,
    ) -> None:
        self.inner = inner
        self.roi_profile = roi_profile or load_default_cpu_roi_profile()
        self._reader = reader
        self.last_status: str | None = None
        self.last_reason: str = ""

    def _reader_for(self, window_size: tuple[int, int]) -> MapCoordinateReader:
        if self._reader is not None:
            return self._reader
        return reader_from_profile(self.roi_profile, window_size)

    def observe(self, context: MissionContext) -> ObservationBundle:
        bundle = self.inner.observe(context)

        foreground = sorted(_FOREGROUND_MARKERS & _visible_markers(bundle))
        if foreground:
            return self._note(
                bundle, "suppressed", f"foreground surface visible: {foreground}"
            )

        image_path = bundle.scene.facts.get("image_path")
        if not isinstance(image_path, str) or not image_path:
            return self._note(bundle, "unavailable", "observation carried no image path")

        try:
            reader = self._reader_for(tuple(bundle.observation.window_size))
        except (CpuRoiError, ValueError) as exc:
            return self._note(bundle, "unresolved", f"{ROI_ID} unavailable: {exc}")

        reading = reader.read(Path(image_path))
        self.last_status = reading.status.value
        self.last_reason = reading.reason

        facts = dict(bundle.scene.facts)
        facts["map_coordinate_readout"] = {
            "status": reading.status.value,
            "text_columns": reading.text_columns,
            "reason": reading.reason,
            "source": "calibrated_roi_local_contrast",
            "processing_device": "cpu",
        }
        scene = replace(bundle.scene, facts=facts)

        if not reading.on_bare_world_map:
            # ABSENT, UNCERTAIN and UNREADABLE all add no evidence. Only the
            # first means "not the world map"; the other two mean "ask
            # again", and neither may stand in for a positive.
            return ObservationBundle(bundle.observation, scene)

        evidence = Evidence(
            "map_coordinate_readout",
            COORDINATE_EVIDENCE,
            1.0,
            value=COORDINATE_EVIDENCE,
            metadata={
                "frame_id": bundle.observation.frame_id,
                "acquisition": "map_coordinate_region",
                "roi": list(reader.roi),
                "text_columns": reading.text_columns,
            },
        )
        return ObservationBundle(
            replace(
                bundle.observation,
                evidence=tuple(bundle.observation.evidence) + (evidence,),
            ),
            scene,
        )

    def _note(self, bundle: ObservationBundle, status: str, reason: str) -> ObservationBundle:
        self.last_status = status
        self.last_reason = reason
        facts = dict(bundle.scene.facts)
        facts["map_coordinate_readout"] = {"status": status, "reason": reason}
        return ObservationBundle(bundle.observation, replace(bundle.scene, facts=facts))


__all__ = ["MapCoordinateObservationProvider"]
