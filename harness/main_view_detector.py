"""Deterministic CITY_VIEW/WORLD_MAP_VIEW evidence from trained visual signatures.

The detector intentionally separates *runtime matching* from *training data*.
It never invents a city/world state when no trained profile is available or when
scores are too close.  Profiles are learned from operator-labelled screenshots
and stored as numeric prototypes; runtime only compares the current frame.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import json
import math
from pathlib import Path
from typing import Callable, Mapping, Sequence

from harness.contracts import Evidence, Observation
from harness.mission_runtime import MissionContext
from harness.mission_tool import ObservationBundle, ObservationProvider


CITY_VIEW = "CITY_VIEW"
WORLD_MAP_VIEW = "WORLD_MAP_VIEW"
_SUPPORTED = {CITY_VIEW, WORLD_MAP_VIEW}

_CITY_EVIDENCE = (
    "city buildings occupy central world canvas",
    "resource counters across top",
    "primary circular navigation/actions at bottom-right",
    "quest/task list at left",
)
_WORLD_EVIDENCE = (
    "map terrain and world objects occupy central canvas",
    "resource counters across top",
    "bottom-right primary navigation is visible",
)


class MainViewProfileError(ValueError):
    pass


@dataclass(frozen=True)
class MainViewPrototype:
    state_id: str
    vector: tuple[float, ...]
    max_distance: float


@dataclass(frozen=True)
class MainViewMatch:
    state_id: str | None
    best_distance: float | None
    second_distance: float | None
    reason: str


@dataclass(frozen=True)
class MainViewProfile:
    prototypes: tuple[MainViewPrototype, ...]
    min_margin: float = 0.08

    @classmethod
    def load(cls, path: str | Path) -> "MainViewProfile":
        source = Path(path)
        raw = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(raw, Mapping) or raw.get("schema_version") != 1:
            raise MainViewProfileError("main-view profile must use schema_version=1")
        min_margin = raw.get("min_margin", 0.08)
        if type(min_margin) not in (int, float) or not 0.0 <= float(min_margin) <= 2.0:
            raise MainViewProfileError("min_margin must be within [0, 2]")
        items = raw.get("prototypes", [])
        if not isinstance(items, list):
            raise MainViewProfileError("prototypes must be a list")
        prototypes: list[MainViewPrototype] = []
        lengths: set[int] = set()
        for item in items:
            if not isinstance(item, Mapping):
                raise MainViewProfileError("prototype entries must be objects")
            state_id = item.get("state_id")
            vector = item.get("vector")
            max_distance = item.get("max_distance")
            if state_id not in _SUPPORTED:
                raise MainViewProfileError(f"unsupported main-view state: {state_id!r}")
            if not isinstance(vector, list) or not vector or any(type(v) not in (int, float) for v in vector):
                raise MainViewProfileError(f"prototype {state_id} needs a numeric vector")
            if type(max_distance) not in (int, float) or not 0.0 < float(max_distance) <= 2.0:
                raise MainViewProfileError(f"prototype {state_id} max_distance is invalid")
            normalized = _unit(tuple(float(v) for v in vector))
            lengths.add(len(normalized))
            prototypes.append(MainViewPrototype(state_id, normalized, float(max_distance)))
        if len(lengths) > 1:
            raise MainViewProfileError("all prototype vectors must have the same length")
        return cls(tuple(prototypes), float(min_margin))


def _unit(vector: Sequence[float]) -> tuple[float, ...]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 1e-12:
        raise MainViewProfileError("visual signature vector cannot be all zero")
    return tuple(value / norm for value in vector)


def cosine_distance(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        raise MainViewProfileError("signature vector dimensions do not match")
    a, b = _unit(left), _unit(right)
    dot = max(-1.0, min(1.0, sum(x * y for x, y in zip(a, b))))
    return 1.0 - dot


def classify_signature(vector: Sequence[float], profile: MainViewProfile) -> MainViewMatch:
    if not profile.prototypes:
        return MainViewMatch(None, None, None, "profile_untrained")
    current = _unit(tuple(float(v) for v in vector))
    scored = sorted(
        ((cosine_distance(current, item.vector), item) for item in profile.prototypes),
        key=lambda pair: pair[0],
    )
    best_distance, best = scored[0]
    second_distance = scored[1][0] if len(scored) > 1 else None
    if best_distance > best.max_distance:
        return MainViewMatch(None, best_distance, second_distance, "best_match_outside_threshold")
    if second_distance is not None and second_distance - best_distance < profile.min_margin:
        return MainViewMatch(None, best_distance, second_distance, "match_margin_too_small")
    return MainViewMatch(best.state_id, best_distance, second_distance, "matched")


def extract_visual_signature(image_path: str | Path) -> tuple[float, ...]:
    """Extract a layout/color/edge signature from a client-area screenshot.

    OpenCV is imported lazily because non-Windows CI validates the runtime
    contracts without installing the live capture dependency set.
    """
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except ImportError as exc:  # pragma: no cover - live dependency
        raise RuntimeError("OpenCV/numpy are required for main-view visual signatures") from exc

    image = cv2.imread(str(Path(image_path)), cv2.IMREAD_COLOR)
    if image is None or image.ndim != 3:
        raise ValueError("main-view detector could not decode the current frame")
    image = cv2.resize(image, (160, 90), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV).astype("float32")
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 80, 160)

    features: list[float] = []
    rows, cols = 3, 4
    cell_h, cell_w = image.shape[0] // rows, image.shape[1] // cols
    for row in range(rows):
        for col in range(cols):
            y1, y2 = row * cell_h, (row + 1) * cell_h if row < rows - 1 else image.shape[0]
            x1, x2 = col * cell_w, (col + 1) * cell_w if col < cols - 1 else image.shape[1]
            cell = hsv[y1:y2, x1:x2]
            edge_cell = edges[y1:y2, x1:x2]
            # Hue/saturation/value means and spreads preserve coarse visual
            # composition while remaining insensitive to exact object positions.
            for channel, scale in ((0, 180.0), (1, 255.0), (2, 255.0)):
                values = cell[:, :, channel] / scale
                features.extend((float(values.mean()), float(values.std())))
            features.append(float(np.mean(edge_cell > 0)))
    return _unit(tuple(features))


class MainViewVisualObservationProvider:
    """Append main-view semantic evidence only when a trained profile matches."""

    def __init__(
        self,
        inner: ObservationProvider,
        profile: MainViewProfile,
        *,
        extractor: Callable[[str | Path], Sequence[float]] = extract_visual_signature,
    ) -> None:
        self.inner = inner
        self.profile = profile
        self.extractor = extractor

    def observe(self, context: MissionContext) -> ObservationBundle:
        bundle = self.inner.observe(context)
        image_path = bundle.scene.facts.get("image_path")
        facts = dict(bundle.scene.facts)
        if not isinstance(image_path, str) or not image_path:
            facts["main_view_detector"] = {"status": "unavailable", "reason": "image_path_missing"}
            return ObservationBundle(bundle.observation, replace(bundle.scene, facts=facts))

        match = classify_signature(self.extractor(image_path), self.profile)
        facts["main_view_detector"] = {
            "status": "matched" if match.state_id else "unresolved",
            "state_id": match.state_id,
            "best_distance": match.best_distance,
            "second_distance": match.second_distance,
            "reason": match.reason,
            "source": "trained_visual_signature",
        }
        if match.state_id is None:
            return ObservationBundle(bundle.observation, replace(bundle.scene, facts=facts))

        values = _CITY_EVIDENCE if match.state_id == CITY_VIEW else _WORLD_EVIDENCE
        confidence = max(0.0, min(1.0, 1.0 - float(match.best_distance or 0.0)))
        added = tuple(
            Evidence(
                "main_view_visual_detector",
                value,
                confidence,
                value=value,
                metadata={
                    "frame_id": bundle.observation.frame_id,
                    "state_id": match.state_id,
                    "profile_reason": match.reason,
                    "visual_distance": match.best_distance,
                },
            )
            for value in values
        )
        observation = Observation(
            bundle.observation.timestamp,
            bundle.observation.frame_id,
            bundle.observation.window_size,
            tuple(bundle.observation.evidence) + added,
        )
        return ObservationBundle(observation, replace(bundle.scene, facts=facts))
