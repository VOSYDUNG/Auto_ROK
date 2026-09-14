from harness.contracts import Evidence, Observation
from harness.gather_facts import GatherFactObservationProvider, extract_march_queue
from harness.mission_runtime import MissionContext
from harness.mission_tool import ObservationBundle
from harness.scene_graph import SceneGraph


CONTEXT = MissionContext("GATHER_RESOURCE", "one-character", "run-facts")


class One:
    def __init__(self, bundle):
        self.bundle = bundle

    def observe(self, context):
        return self.bundle


def bundle(text):
    frame = "f1"
    observation = Observation(
        1.0,
        frame,
        (1280, 720),
        (Evidence("ocr", text, 1.0, value=text, metadata={"frame_id": frame}),),
    )
    return ObservationBundle(observation, SceneGraph(frame, None, facts={"raw_text": text}))


def test_visible_queue_and_configured_character_are_projected_into_scene_facts():
    provider = GatherFactObservationProvider(One(bundle("Queue 0/5")), character_id="hien")
    result = provider.observe(CONTEXT)
    assert result.scene.facts["march_queue_used"] == 0
    assert result.scene.facts["march_queue_capacity"] == 5
    assert result.scene.facts["march_queue_source"] == "visible_ocr"
    assert result.scene.facts["character_id"] == "hien"
    assert result.scene.facts["character_id_source"] == "configured_single_character_scope"


def test_ambiguous_visible_queue_fails_closed():
    ambiguous = bundle("Queue 0/5 ... Queue 1/5")
    assert extract_march_queue(ambiguous) is None
    result = GatherFactObservationProvider(One(ambiguous), character_id="hien").observe(CONTEXT)
    assert "march_queue_used" not in result.scene.facts
