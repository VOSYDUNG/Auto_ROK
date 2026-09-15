"""Deterministically classify the bounded gather UI states from frame evidence.

The rules below mirror the positive evidence recorded in ``config/ui_states.yaml``.
They deliberately do not infer unobserved UI: every positive match must be bound
to the current frame. OCR phrase evidence is acceptable when it was assembled
from current-frame word boxes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Mapping, Sequence

from harness.contracts import Evidence, Observation
from harness.scene_graph import SceneGraph


UNKNOWN_STATE = "UNKNOWN_STATE"
AMBIGUOUS_STATE = "AMBIGUOUS_STATE"


@dataclass(frozen=True)
class StateClassification:
    """A bounded state decision and the current-frame evidence that supports it."""

    state_id: str
    matching_evidence: Sequence[Evidence] = field(default_factory=tuple)
    ambiguity: Mapping[str, Any] = field(default_factory=dict)


_STATE_RULES: Mapping[str, tuple[str, ...]] = {
    "CITY_VIEW": (
        "city buildings occupy central world canvas",
        "resource counters across top",
        "primary circular navigation/actions at bottom-right",
        "quest/task list at left",
    ),
    "WORLD_MAP_VIEW": (
        "map terrain and world objects occupy central canvas",
        "resource counters across top",
        "bottom-right primary navigation is visible",
    ),
    "RESOURCE_SEARCH_PANEL": ("SEARCH", "Barbarians", "Cropland"),
    "RESOURCE_POINT_DETAIL": ("Resource Point", "GATHER"),
    "TROOP_DISPATCH_DRAWER": (
        "Dispatch a new troop from your city",
        "New Troop",
        "Queue X/5",
    ),
    # Keep this synchronized with config/ui_states.yaml. "Load" was an older
    # training note; the accepted positive anchor is now "Total Power".
    "NEW_TROOP_SETUP": ("New Troop", "MARCH", "Units", "Total Power"),
    "MARCH_IN_PROGRESS": (
        "used march count is greater than before dispatch",
        "troop/path indicator may be visible on map",
    ),
}

_QUEUE_PATTERN = re.compile(r"^queue\s+\d{1,2}\s*/\s*\d{1,2}$", re.IGNORECASE)


def _current_evidence(observation: Observation, scene: SceneGraph | None) -> tuple[Evidence, ...]:
    """Return only evidence bound to the supplied observation and scene frame."""
    if not observation.frame_id or scene is not None and scene.frame_id != observation.frame_id:
        return ()
    return tuple(
        item
        for item in observation.evidence
        if isinstance(item.metadata, Mapping) and item.metadata.get("frame_id") == observation.frame_id
    )


def _text(item: Evidence) -> tuple[str, ...]:
    values = [item.label]
    if isinstance(item.value, str) and item.value != item.label:
        values.append(item.value)
    return tuple(value for value in values if isinstance(value, str))


def _matches(item: Evidence, expected: str) -> bool:
    """Match exact trained anchors plus the one declared queue text pattern."""
    if expected == "Queue X/5":
        return any(_QUEUE_PATTERN.fullmatch(value.strip()) is not None for value in _text(item))
    return any(value == expected for value in _text(item))


class StateClassifier:
    """Classify only the seven gather-flow state IDs plus fail-closed outcomes."""

    def classify(
        self, observation: Observation, scene: SceneGraph | None = None
    ) -> StateClassification:
        evidence = _current_evidence(observation, scene)
        candidates: list[tuple[str, tuple[Evidence, ...]]] = []
        for state_id, required in _STATE_RULES.items():
            matched: list[Evidence] = []
            for expected in required:
                item = next((candidate for candidate in evidence if _matches(candidate, expected)), None)
                if item is None:
                    break
                matched.append(item)
            else:
                candidates.append((state_id, tuple(matched)))

        if len(candidates) == 1:
            state_id, matched = candidates[0]
            return StateClassification(state_id, matched, {"candidate_states": (state_id,)})
        if len(candidates) > 1:
            return StateClassification(
                AMBIGUOUS_STATE,
                (),
                {"reason": "competing_state_evidence", "candidate_states": tuple(state for state, _ in candidates)},
            )
        return StateClassification(
            UNKNOWN_STATE,
            (),
            {"reason": "missing_current_frame_evidence", "candidate_states": ()},
        )
