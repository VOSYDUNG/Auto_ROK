from harness.contracts import Evidence, Observation
from harness.gather_facts import (
    GatherFactObservationProvider,
    extract_march_queue,
    extract_visible_resource_level,
)
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


def roi_bundle(text):
    frame = "f-roi"
    observation = Observation(
        1.0,
        frame,
        (1366, 768),
        (Evidence(
            "ocr",
            text,
            0.0,
            value=text,
            metadata={"frame_id": frame, "acquisition": "ocr_march_queue_region", "grounding_authority": "ocr_backend"},
        ),),
    )
    return ObservationBundle(observation, SceneGraph(frame, None, facts={"raw_text": text}))


def test_visible_queue_and_configured_character_are_projected_into_scene_facts():
    provider = GatherFactObservationProvider(One(bundle("Queue 0/5")), character_id="hien")
    result = provider.observe(CONTEXT)
    assert result.scene.facts["march_queue_used"] == 0
    assert result.scene.facts["march_queue_capacity"] == 5
    assert result.scene.facts["march_queue_source"] == "visible_ocr_queue_anchor"
    assert result.scene.facts["character_id"] == "hien"
    assert result.scene.facts["character_id_source"] == "configured_single_character_scope"


def test_ambiguous_visible_queue_fails_closed():
    ambiguous = bundle("Queue 0/5 ... Queue 1/5")
    assert extract_march_queue(ambiguous) is None
    result = GatherFactObservationProvider(One(ambiguous), character_id="hien").observe(CONTEXT)
    assert "march_queue_used" not in result.scene.facts


def test_queue_ratio_is_accepted_only_from_authorized_march_queue_roi():
    source = roi_bundle("1/5")
    assert extract_march_queue(source) == (1, 5)
    result = GatherFactObservationProvider(One(source), character_id="hien").observe(CONTEXT)
    assert result.scene.facts["march_queue_source"] == "visible_ocr_march_queue_region"


def test_queue_roi_normalizes_thin_slash_ocr_without_opening_generic_ratio_path():
    source = roi_bundle("115")
    assert extract_march_queue(source) == (1, 5)


def test_bare_date_like_ratio_is_rejected_without_roi_provenance():
    source = bundle("09/15")
    assert extract_march_queue(source) is None
    result = GatherFactObservationProvider(One(source), character_id="hien").observe(CONTEXT)
    assert "march_queue_used" not in result.scene.facts


def test_unique_visible_level_is_projected_for_typed_postcondition():
    source = bundle("Logging Camp Level 6 SEARCH")
    assert extract_visible_resource_level(source) == 6
    result = GatherFactObservationProvider(One(source), character_id="hien").observe(CONTEXT)
    assert result.scene.facts["selected_search_level"] == 6
    assert result.scene.facts["selected_search_level_source"] == "visible_ocr_level_text"


def test_ambiguous_visible_levels_fail_closed():
    source = bundle("Level 5 ... Level 6")
    assert extract_visible_resource_level(source) is None
    result = GatherFactObservationProvider(One(source), character_id="hien").observe(CONTEXT)
    assert "selected_search_level" not in result.scene.facts
