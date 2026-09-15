"""Deterministic state classifier for CLAIM_ALLIANCE_TERRITORY_RSS.

Only current-frame evidence from the operator-trained alliance screens and the
existing main-view detector is accepted. Unknown or competing evidence fails
closed exactly like the GATHER classifier.
"""
from __future__ import annotations

from typing import Mapping, Sequence

from harness.contracts import Evidence, Observation
from harness.scene_graph import SceneGraph
from harness.state_classifier import AMBIGUOUS_STATE, UNKNOWN_STATE, StateClassification


_RULES: Mapping[str, tuple[str, ...]] = {
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
    "ALLIANCE_HOME": (
        "ALLIANCE",
        "War",
        "Territory",
        "Help",
    ),
    "ALLIANCE_TERRITORY": (
        "ALLIANCE TERRITORY",
        "Territory Resource Earnings",
        "Territory Buildings",
    ),
}


def _normalize(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def _current_evidence(observation: Observation, scene: SceneGraph | None) -> tuple[Evidence, ...]:
    if not observation.frame_id or scene is not None and scene.frame_id != observation.frame_id:
        return ()
    return tuple(
        item
        for item in observation.evidence
        if isinstance(item.metadata, Mapping) and item.metadata.get("frame_id") == observation.frame_id
    )


def _values(item: Evidence) -> tuple[str, ...]:
    values: list[str] = []
    if isinstance(item.label, str):
        values.append(item.label)
    if isinstance(item.value, str) and item.value != item.label:
        values.append(item.value)
    return tuple(values)


def _matches(item: Evidence, expected: str) -> bool:
    wanted = _normalize(expected)
    return any(_normalize(value) == wanted for value in _values(item))


class AllianceClaimStateClassifier:
    """Classify only main-view and alliance-claim states for this mission."""

    def classify(
        self,
        observation: Observation,
        scene: SceneGraph | None = None,
    ) -> StateClassification:
        evidence = _current_evidence(observation, scene)
        candidates: list[tuple[str, tuple[Evidence, ...]]] = []
        for state_id, required in _RULES.items():
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
            return StateClassification(
                state_id,
                matched,
                {"candidate_states": (state_id,), "classifier": "alliance_claim"},
            )
        if len(candidates) > 1:
            return StateClassification(
                AMBIGUOUS_STATE,
                (),
                {
                    "reason": "competing_state_evidence",
                    "candidate_states": tuple(state for state, _ in candidates),
                    "classifier": "alliance_claim",
                },
            )
        return StateClassification(
            UNKNOWN_STATE,
            (),
            {
                "reason": "missing_current_frame_evidence",
                "candidate_states": (),
                "classifier": "alliance_claim",
            },
        )
