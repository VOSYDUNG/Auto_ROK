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
CONTROL_MODE = "horizontal_discrete_slider"


class ResourceLevelProfileError(ValueError):
    pass


#: Horizontal centre of each search-category icon, in client pixels at the
#: trained 1366x768 size.  Measured 2026-09-20 off a live category bar; the
#: icons sit exactly 142px apart.
CATEGORY_CENTRE_X: Mapping[str, int] = {
    "BARBARIANS": 396,
    "FOOD": 538,
    "WOOD": 680,
    "STONE": 822,
    "GOLD": 964,
}

#: The category that was selected when the slider profile was trained. The
#: search panel is centred under the SELECTED category, so the trained track
#: is only in the right place for this one.
TRAINED_CATEGORY = "FOOD"


def category_offset(resource_type: str | None, width: int) -> int:
    """How far the panel has moved from where the profile was trained.

    The search panel is not at a fixed position - it is centred under the
    selected category icon. Measured live on 2026-09-20: with Cropland
    selected the panel centred on x=538, with Logging Camp on x=680.

    The profile was trained with Cropland selected, so on a WOOD run every
    trained coordinate was 142px to the LEFT of the real control. The level-6
    click, which lands at the right-hand end of the track, came down on the
    NEXT panel's minus button and walked the level DOWN from 6 to 4 - away
    from the value it was asked for.

    That is the failure this function removes. Returning 0 for an unknown
    resource type keeps the old behaviour rather than guessing an offset.
    """
    if resource_type is None:
        return 0
    key = str(resource_type).strip().upper()
    if key not in CATEGORY_CENTRE_X:
        return 0
    delta = CATEGORY_CENTRE_X[key] - CATEGORY_CENTRE_X[TRAINED_CATEGORY]
    # Scale with the client, because the trained centres are in the trained
    # client's pixels.
    return round(delta * width / 1366)


@dataclass(frozen=True)
class ResourceLevelProfile:
    trained: bool
    min_level: int | None = None
    max_level: int | None = None
    track_normalized: tuple[float, float, float, float] | None = None
    confidence: float = 0.0
    required_anchors: tuple[str, ...] = ("SEARCH",)
    control_mode: str | None = None

    @classmethod
    def load(cls, path: str | Path) -> "ResourceLevelProfile":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, Mapping) or raw.get("schema_version") != 1:
            raise ResourceLevelProfileError("resource-level profile must use schema_version=1")
        if raw.get("status") != "trained":
            return cls(False)
        if raw.get("control_mode") != CONTROL_MODE:
            raise ResourceLevelProfileError(
                f"trained resource-level profile must declare control_mode={CONTROL_MODE!r}"
            )
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
        return cls(
            True,
            min_level,
            max_level,
            (x1, y1, x2, y2),
            float(confidence),
            tuple(anchors),
            CONTROL_MODE,
        )

    def bbox(
        self, width: int, height: int, *, resource_type: str | None = None
    ) -> BoundingBox:
        """The slider track, shifted to the panel the run actually opened."""
        if not self.trained or self.control_mode != CONTROL_MODE or self.track_normalized is None:
            raise ResourceLevelProfileError("resource-level control profile is not trained")
        x1, y1, x2, y2 = self.track_normalized
        shift = category_offset(resource_type, width)
        left = round(x1 * width) + shift
        right = round(x2 * width) + shift
        if left < 0 or right > width:
            raise ResourceLevelProfileError(
                f"the {resource_type} search panel would put the level track at "
                f"{left}..{right}, outside the {width}px client; refusing rather "
                "than clamping onto whatever control sits at the edge"
            )
        top = max(0, min(height - 1, round(y1 * height)))
        bottom = max(top + 1, min(height, round(y2 * height)))
        return BoundingBox(left, top, max(left + 1, right), bottom)


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

    def __init__(
        self,
        inner: ObservationProvider,
        profile: ResourceLevelProfile,
        *,
        resource_type: str | None = None,
    ) -> None:
        self.inner = inner
        self.profile = profile
        #: Which category's panel this run opened. Without it the trained
        #: geometry is only correct for FOOD.
        self.resource_type = resource_type

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
        try:
            bbox = self.profile.bbox(width, height, resource_type=self.resource_type)
        except ResourceLevelProfileError as exc:
            facts["resource_level_control"] = {
                "status": "not_grounded",
                "reason": str(exc),
            }
            return ObservationBundle(bundle.observation, replace(bundle.scene, facts=facts))
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
                "control_mode": CONTROL_MODE,
                "required_anchors": self.profile.required_anchors,
            },
        )
        targets = tuple(t for t in bundle.scene.targets if t.target_id != TARGET_ID) + (target,)
        facts["resource_level_control"] = {
            "status": "grounded",
            "control_mode": CONTROL_MODE,
            "min_level": self.profile.min_level,
            "max_level": self.profile.max_level,
            "track_bbox_client": [bbox.x1, bbox.y1, bbox.x2, bbox.y2],
            "panel_category": self.resource_type,
            "panel_offset_px": category_offset(self.resource_type, width),
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
        if (
            type(level) is not int
            or not isinstance(facts, Mapping)
            or facts.get("status") != "grounded"
            or facts.get("control_mode") != CONTROL_MODE
        ):
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
