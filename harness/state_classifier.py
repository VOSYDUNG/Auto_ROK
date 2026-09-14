"""Deterministically classify the bounded gather UI states from frame evidence.

The rules below are the positive semantic evidence recorded for these states in
``config/ui_states.yaml``.  They deliberately do not infer unobserved UI or use
coordinates: every positive match must be explicitly bound to the observation's
current frame.
"""
from __future__ import annotations

from dataclasses import dataclass, field
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


# Exact positive-evidence values from config/ui_states.yaml.  A state is a
# candidate only when every value documented for it is observed in this frame.
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
    "NEW_TROOP_SETUP": ("New Troop", "MARCH", "Units", "Load"),
    "MARCH_IN_PROGRESS": (
        "used march count is greater than before dispatch",
        "troop/path indicator may be visible on map",
    ),
}


def _current_evidence(observation: Observation, scene: SceneGraph | None) -> tuple[Evidence, ...]:
    """Return only evidence bound to the supplied observation and scene frame."""
    if not observation.frame_id or scene is not None and scene.frame_id != observation.frame_id:
        return ()
    return tuple(
        item
        for item in observation.evidence
        if isinstance(item.metadata, Mapping) and item.metadata.get("frame_id") == observation.frame_id
    )


def _matches(item: Evidence, expected: str) -> bool:
    """Match an observed semantic label/value without interpreting metadata."""
    return item.label == expected or isinstance(item.value, str) and item.value == expected


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
