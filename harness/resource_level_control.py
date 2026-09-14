"""Typed, trained resource-level control for GATHER_RESOURCE.

The old automation clicked a generic search-panel position. This module makes
resource-level selection an explicit bounded control: a trained profile grounds
one slider track only while current search-panel OCR anchors are visible, and
the requested level is converted to one discrete point on that track.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
from typing import Mapping

from harness.action_surface import ActionRequest, InputKind, ResolvedInput
from harness.contracts import BoundingBox
from harness.mission_runtime import MissionContext
from harness.mission_tool import ObservationBundle, ObservationProvider
from harness.scene_graph import SceneGraph, VisualTarget
from harness.screen_mapped_surface import ScreenMappedSemanticActionSurface


ACTION_ID = "SET_RESOURCE_LEVEL"
TARGET_ID = "SEARCH_LEVEL_CONTROL"


class ResourceLevelProfileError(ValueError):
    pass


@dataclass(frozen=True)
class ResourceLevelProfile:
    trained: bool
    min_level: int | None = None
    max_level: int | None = None
    track_normalized: tuple[float, float, float, float] | None = None
    confidence: float = 0.0
    required_anchors: tuple[str, ...] = ("SEARCH",)

    @classmethod
    def load(cls, path: str | Path) -> "ResourceLevelProfile":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, Mapping) or raw.get("schema_version") != 1:
            raise ResourceLevelProfileError("resource-level profile must use schema_version=1")
        if raw.get("status") != "trained":
            return cls(False)
        min_level, max_level = raw.get("min_level"), raw.get("max_level")
        bounds = raw.get("track_normalized")
        confidence = raw.get("confidence")
        anchors = raw.get("required_anchors", ["SEARCH"])
        if type(min_level) is not int or type(max_level) is not int or not (0 <= min_level < max_level <= 30):
            raise ResourceLevelProfileError("trained profile needs a valid min_level/max_level")
        if (
            not isinstance(bounds, list)
            or len(bounds) != 4
            or any(type(value) not in (int, float) for value in bounds)
        ):
            raise ResourceLevelProfileError("track_normalized must contain four numbers")
        x1, y1, x2, y2 = (float(value) for value in bounds)
        if not (0.0 <= x1 < x2 <= 1.0 and 0.0 <= y1 < y2 <= 1.0):
            raise ResourceLevelProfileError("track_normalized must be inside normalized client bounds")
        if type(confidence) not in (int, float) or not 0.0 < float(confidence) <= 1.0:
            raise ResourceLevelProfileError("confidence must be within (0, 1]")
        if not isinstance(anchors, list) or not anchors or any(not isinstance(v, str) or not v for v in anchors):
            raise ResourceLevelProfileError("required_anchors must be non-empty strings")
        return cls(True, min_level, max_level, (x1, y1, x2, y2), float(confidence), tuple(anchors))

    def bbox(self, width: int, height: int) -> BoundingBox:
        if not self.trained or self.track_normalized is None:
            raise ResourceLevelProfileError("resource-level control profile is not trained")
        x1, y1, x2, y2 = self.track_normalized
        left = max(0, min(width - 1, round(x1 * width)))
        top = max(0, min(height - 1, round(y1 * height)))
        right = max(left + 1, min(width, round(x2 * width)))
        bottom = max(top + 1, min(height, round(y2 * height)))
        return BoundingBox(left, top, right, bottom)


def _visible_texts(bundle: ObservationBundle) -> set[str]:
    values: set[str] = set()
    for item in bundle.observation.evidence:
        if isinstance(item.value, str) and item.value.strip():
            values.add(item.value.strip().casefold())
        if isinstance(item.label, str) and item.label.strip():
            values.add(item.label.strip().casefold())
    return values


class ResourceLevelControlObservationProvider:
    """Ground the trained slider only when its current search-panel anchors exist."""

    def __init__(self, inner: ObservationProvider, profile: ResourceLevelProfile) -> None:
        self.inner = inner
        self.profile = profile

    def observe(self, context: MissionContext) -> ObservationBundle:
        bundle = self.inner.observe(context)
        facts = dict(bundle.scene.facts)
        if not self.profile.trained:
            facts["resource_level_control"] = {"status": "untrained"}
            return ObservationBundle(bundle.observation, replace(bundle.scene, facts=facts))

        texts = _visible_texts(bundle)
        missing = [anchor for anchor in self.profile.required_anchors if anchor.casefold() not in texts]
        if missing:
            facts["resource_level_control"] = {"status": "not_grounded", "missing_anchors": missing}
            return ObservationBundle(bundle.observation, replace(bundle.scene, facts=facts))

        width, height = bundle.observation.window_size
        bbox = self.profile.bbox(width, height)
        target = VisualTarget(
            TARGET_ID,
            bundle.observation.frame_id,
            "trained resource level slider",
            bbox,
            self.profile.confidence,
            "trained_resource_level_profile",
            {
                "frame_id": bundle.observation.frame_id,
                "trained_geometry": True,
                "required_anchors": self.profile.required_anchors,
            },
        )
        targets = tuple(t for t in bundle.scene.targets if t.target_id != TARGET_ID) + (target,)
        facts["resource_level_control"] = {
            "status": "grounded",
            "min_level": self.profile.min_level,
            "max_level": self.profile.max_level,
            "track_bbox_client": [bbox.x1, bbox.y1, bbox.x2, bbox.y2],
            "source": "trained_resource_level_profile",
        }
        contracts = dict(facts.get("typed_action_contracts") or {})
        contracts[ACTION_ID] = {
            "verification_mode": "fact_equals_argument",
            "argument": "resource_level",
            "fact": "selected_search_level",
            "target_id": TARGET_ID,
            "source": "trained_resource_level_profile",
        }
        facts["typed_action_contracts"] = contracts
        return ObservationBundle(bundle.observation, replace(bundle.scene, targets=targets, facts=facts))


class GatherScreenMappedActionSurface(ScreenMappedSemanticActionSurface):
    """Screen-mapped action surface with typed resource-level resolution."""

    def resolve(self, request: ActionRequest, *, scene: SceneGraph | None = None) -> ResolvedInput:
        if request.action_id != ACTION_ID:
            return super().resolve(request, scene=scene)
        if request.target_id != TARGET_ID or scene is None:
            raise ResourceLevelProfileError("SET_RESOURCE_LEVEL requires the current SEARCH_LEVEL_CONTROL target")
        target = scene.require_target(TARGET_ID, min_confidence=self.min_target_confidence)
        if not scene.is_current(target):
            raise ResourceLevelProfileError("resource-level target is stale")
        level = request.arguments.get("resource_level")
        facts = scene.facts.get("resource_level_control")
        if type(level) is not int or not isinstance(facts, Mapping) or facts.get("status") != "grounded":
            raise ResourceLevelProfileError("resource level argument/control evidence is missing")
        min_level, max_level = facts.get("min_level"), facts.get("max_level")
        if type(min_level) is not int or type(max_level) is not int or not min_level <= level <= max_level:
            raise ResourceLevelProfileError("requested resource level is outside the trained control range")

        fraction = (level - min_level) / (max_level - min_level)
        client_x = round(target.bbox.x1 + fraction * (target.bbox.x2 - target.bbox.x1))
        client_y = (target.bbox.y1 + target.bbox.y2) // 2
        rect = scene.facts.get("client_screen_rect")
        if not (
            isinstance(rect, (list, tuple))
            and len(rect) == 4
            and all(type(value) is int for value in rect)
        ):
            raise ResourceLevelProfileError("client_screen_rect is missing from current capture facts")
        left, top, right, bottom = rect
        width, height = right - left, bottom - top
        if width <= 0 or height <= 0 or not (0 <= client_x < width and 0 <= client_y < height):
            raise ResourceLevelProfileError("trained resource-level point is outside current client bounds")
        return ResolvedInput(
            request.action_id,
            InputKind.CLICK_TARGET,
            frame_id=scene.frame_id,
            target_id=TARGET_ID,
            point=(left + client_x, top + client_y),
            source="trained_resource_level_profile+client_to_screen",
        )
