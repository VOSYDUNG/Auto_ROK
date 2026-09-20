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
from harness.map_coordinate import COORDINATE_EVIDENCE
from harness.scene_graph import SceneGraph


UNKNOWN_STATE = "UNKNOWN_STATE"
AMBIGUOUS_STATE = "AMBIGUOUS_STATE"


@dataclass(frozen=True)
class StateClassification:
    """A bounded state decision and the current-frame evidence that supports it."""

    state_id: str
    matching_evidence: Sequence[Evidence] = field(default_factory=tuple)
    ambiguity: Mapping[str, Any] = field(default_factory=dict)


#: Each state maps to one or more ALTERNATIVE requirement sets. A state is
#: established when every phrase in any one set is present on the current
#: frame.
#:
#: Alternatives exist because two sensors can establish the same state by
#: looking at different things, and neither should have to claim it checked
#: what the other checked. WORLD_MAP_VIEW has two routes:
#:
#:   * the trained visual signature, which reports the whole canvas
#:   * the coordinate readout in the top-left corner
#:
#: The second was added 2026-09-20 because the first never fires on the world
#: map. A city always looks like itself, so one prototype represents it at
#: distance 0.0001; open terrain looks different everywhere you pan, and every
#: real world frame measured 0.15 to 0.22 against a 0.08 threshold. That is
#: not a threshold to widen - widening it to 0.22 would swallow the city too.
#: It is a signal that cannot carry this state, so a second one carries it.
_STATE_RULES: Mapping[str, tuple[tuple[str, ...], ...]] = {
    "CITY_VIEW": (
        (
            "city buildings occupy central world canvas",
            "resource counters across top",
            "primary circular navigation/actions at bottom-right",
            "quest/task list at left",
        ),
    ),
    "WORLD_MAP_VIEW": (
        (
            "map terrain and world objects occupy central canvas",
            "resource counters across top",
            "bottom-right primary navigation is visible",
        ),
        # One phrase, and that is deliberate. The widget is drawn ONLY on the
        # bare world map: the city hides it and every open panel replaces it
        # with a back arrow, measured across the stored frames. So its
        # presence already carries "world map, nothing on top", and padding
        # this set with HUD phrases this sensor never looked at would be a
        # lie that happened to be true.
        (COORDINATE_EVIDENCE,),
    ),
    "RESOURCE_SEARCH_PANEL": (("SEARCH", "Barbarians", "Cropland"),),
    "RESOURCE_POINT_DETAIL": (("Resource Point", "GATHER"),),
    "TROOP_DISPATCH_DRAWER": (
        (
            "Dispatch a new troop from your city",
            "New Troop",
            "Queue X/5",
        ),
    ),
    # Keep this synchronized with config/ui_states.yaml. "Load" was an older
    # training note; the accepted positive anchor is now "Total Power".
    "NEW_TROOP_SETUP": (("New Troop", "MARCH", "Units", "Total Power"),),
    "MARCH_IN_PROGRESS": (
        (
            "used march count is greater than before dispatch",
            "troop/path indicator may be visible on map",
        ),
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
    if expected == "Dispatch a new troop from your city":
        return any(
            value == expected or value in ("Dispatch a new", "troop from your city")
            for value in _text(item)
        )
    return any(value == expected or value.rstrip(":") == expected for value in _text(item))


def _matches_drawer_queue_anchor(item: Evidence) -> bool:
    """Accept a bounded queue ROI anchor when digits are unreadable.

    The dispatch drawer can expose a current-frame ``Queue`` token while the
    small ``0/5`` glyph is lost by Windows OCR.  The queue counter itself is
    still required for completion evidence by ``gather_facts``; this fallback
    only lets the state machine reach the drawer's next guarded action when
    the card and its queue ROI are otherwise positively grounded.
    """
    if _matches(item, "Queue X/5"):
        return True
    return (
        _matches(item, "Queue")
        and item.metadata.get("acquisition") in {"ocr_march_queue_region", "ocr_troop_drawer_region"}
    )


def _first_satisfied(
    state_id: str,
    alternatives: Sequence[Sequence[str]],
    evidence: Sequence[Evidence],
) -> tuple[Evidence, ...] | None:
    """The evidence for the first fully satisfied requirement set, or None."""
    for required in alternatives:
        matched: list[Evidence] = []
        for expected in required:
            if state_id == "TROOP_DISPATCH_DRAWER" and expected == "Queue X/5":
                item = next(
                    (c for c in evidence if _matches_drawer_queue_anchor(c)), None
                )
            else:
                item = next((c for c in evidence if _matches(c, expected)), None)
            if item is None:
                break
            matched.append(item)
        else:
            return tuple(matched)
    return None


class StateClassifier:
    """Classify only the seven gather-flow state IDs plus fail-closed outcomes."""

    def classify(
        self, observation: Observation, scene: SceneGraph | None = None
    ) -> StateClassification:
        evidence = _current_evidence(observation, scene)
        candidates: list[tuple[str, tuple[Evidence, ...]]] = []
        for state_id, alternatives in _STATE_RULES.items():
            matched = _first_satisfied(state_id, alternatives, evidence)
            if matched is not None:
                # At most one entry per state, even when several routes are
                # satisfied. Two ways of proving the same state is agreement,
                # not the competing evidence that AMBIGUOUS_STATE is for.
                candidates.append((state_id, matched))

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
