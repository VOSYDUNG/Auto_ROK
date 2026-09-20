"""The queue sensor, wired into the observation path.

It replaces a block that cost 3,031 ms a frame - 75% of the OCR pass - and
emitted nothing, because it never managed to read the indicator.
"""
from pathlib import Path

import numpy as np
import pytest

from harness.contracts import Observation
from harness.gather_facts import extract_march_queue
from harness.mission_runtime import MissionContext
from harness.mission_tool import ObservationBundle
from harness.queue_indicator import QueueIndicatorProfile
from harness.queue_indicator_provider import (
    QUEUE_ACQUISITION,
    QueueIndicatorObservationProvider,
)
from harness.scene_graph import SceneGraph

ROOT = Path(__file__).resolve().parents[1]
PROFILE = QueueIndicatorProfile.load(ROOT / "config" / "queue_indicator_profile.json")


class _Inner:
    def __init__(self, facts=None):
        self.facts = facts or {}

    def observe(self, context):
        observation = Observation(
            timestamp=0.0, frame_id="f1", window_size=(1366, 768), evidence=()
        )
        scene = SceneGraph(frame_id="f1", state_hint=None, facts=dict(self.facts))
        return ObservationBundle(observation, scene)


def _frame_with(labels):
    frame = np.full((768, 1366), 120, dtype=np.uint8)
    x, y, _, _ = PROFILE.roi
    cursor = x + 12
    for label in labels:
        # A label carries several accepted renderings; draw the first.
        pattern = PROFILE.glyphs[label][0]
        for row_index, row in enumerate(pattern):
            for col_index, cell in enumerate(row):
                if cell == "#":
                    frame[y + 3 + row_index, cursor + col_index] = 255
        cursor += len(pattern[0]) + 2
    return frame


def _provider(labels=None, *, facts=None, raises=None):
    def loader(_path):
        if raises is not None:
            raise raises
        return _frame_with(["1", "/", "5"] if labels is None else labels)

    return QueueIndicatorObservationProvider(
        _Inner(facts if facts is not None else {"image_path": __file__}),
        PROFILE,
        frame_loader=loader,
    )


CONTEXT = MissionContext("GATHER_RESOURCE", "one-character", "run-1")


def test_a_successful_reading_is_attached_as_evidence():
    bundle = _provider(["1", "/", "5"]).observe(CONTEXT)
    queue = [
        item
        for item in bundle.observation.evidence
        if item.metadata.get("acquisition") == QUEUE_ACQUISITION
    ]
    assert len(queue) == 1
    assert queue[0].value == "1/5"


def test_the_downstream_fact_extractor_accepts_it_unchanged():
    """The whole point of reusing the existing acquisition tag."""
    bundle = _provider(["1", "/", "5"]).observe(CONTEXT)
    assert extract_march_queue(bundle) == (1, 5)


def test_a_refused_reading_attaches_nothing():
    """A missing queue fact is handled; a wrong one is not."""
    provider = _provider([])
    bundle = provider.observe(CONTEXT)
    assert bundle.observation.evidence == ()
    assert provider.last_status == "NO_TEXT"
    assert extract_march_queue(bundle) is None


def test_an_unreadable_frame_degrades_instead_of_raising():
    provider = _provider(raises=OSError("disk gone"))
    bundle = provider.observe(CONTEXT)
    assert bundle.observation.evidence == ()
    assert provider.last_status == "UNREADABLE"


def test_no_frame_path_is_a_normal_state():
    provider = _provider(facts={})
    bundle = provider.observe(CONTEXT)
    assert bundle.observation.evidence == ()
    assert provider.last_status == "NO_FRAME"


def test_the_inner_observation_is_never_discarded():
    provider = _provider(["1", "/", "5"], facts={"image_path": __file__, "state": "WORLD_MAP"})
    bundle = provider.observe(CONTEXT)
    assert bundle.scene.facts["state"] == "WORLD_MAP"
    assert bundle.observation.frame_id == "f1"


def test_the_evidence_carries_its_roi_and_frame_for_audit():
    bundle = _provider(["1", "/", "5"]).observe(CONTEXT)
    item = bundle.observation.evidence[-1]
    assert item.metadata["roi"] == list(PROFILE.roi)
    assert item.metadata["frame_id"] == "f1"
    assert item.metadata["reader"] == "template"
