from harness.action_surface import ActionRequest, SemanticActionSurface
from harness.contracts import BoundingBox, Evidence, Observation
from harness.mission_runtime import MissionContext
from harness.mission_tool import ObservationBundle
from harness.ocr_semantics import OcrSemanticObservationProvider, OcrTargetSpec
from harness.scene_graph import SceneGraph
from harness.state_classifier import StateClassifier


CONTEXT = MissionContext("GATHER_RESOURCE", "one-character", "run-ocr")


class One:
    def __init__(self, bundle):
        self.bundle = bundle

    def observe(self, context):
        return self.bundle


def word(frame, text, x1, y1, x2, y2, index, *, confidence=None):
    known = confidence is not None
    return Evidence(
        "ocr",
        text,
        confidence or 0.0,
        BoundingBox(x1, y1, x2, y2),
        text,
        {
            "frame_id": frame,
            "ocr_element_index": index,
            "confidence_known": known,
            "raw_confidence": confidence,
        },
    )


def make_bundle(*evidence):
    frame = "f1"
    return ObservationBundle(
        Observation(1.0, frame, (1280, 720), tuple(evidence)),
        SceneGraph(frame, None),
    )


def test_unscored_phrase_is_preserved_as_zero_confidence_and_requires_double_opt_in():
    bundle = make_bundle(
        word("f1", "New", 100, 100, 140, 125, 0),
        word("f1", "Troop", 145, 100, 205, 125, 1),
    )
    enriched = OcrSemanticObservationProvider(
        One(bundle),
        (OcrTargetSpec("NEW_TROOP", ("New Troop",), allow_unscored_exact=True),),
    ).observe(CONTEXT)

    target = enriched.scene.target("NEW_TROOP", allow_unscored_exact=True)
    assert target is not None
    assert target.confidence == 0.0
    assert target.metadata["confidence_known"] is False
    assert target.metadata["grounding_mode"] == "unique_phrase_unscored"

    strict = SemanticActionSurface({})
    try:
        strict.resolve(ActionRequest("CLICK", "NEW_TROOP"), scene=enriched.scene)
        assert False, "strict surface must reject unscored OCR target"
    except LookupError:
        pass

    opted_in = SemanticActionSurface({}, allow_unscored_exact_targets=True)
    resolved = opted_in.resolve(ActionRequest("CLICK", "NEW_TROOP"), scene=enriched.scene)
    assert resolved.point == (152, 112)


def test_duplicate_unscored_exact_labels_fail_closed():
    bundle = make_bundle(
        word("f1", "GATHER", 10, 10, 80, 35, 0),
        word("f1", "GATHER", 200, 10, 270, 35, 1),
    )
    enriched = OcrSemanticObservationProvider(
        One(bundle),
        (OcrTargetSpec("RESOURCE_GATHER", ("GATHER",), allow_unscored_exact=True),),
    ).observe(CONTEXT)
    assert enriched.scene.target("RESOURCE_GATHER", allow_unscored_exact=True) is None
    decisions = enriched.scene.facts["ocr_grounding_decisions"]
    assert decisions[0]["reason"] == "candidate_ambiguous"
    assert decisions[0]["match_count"] == 2


def test_scored_target_still_uses_confidence_threshold():
    bundle = make_bundle(word("f1", "SEARCH", 10, 10, 80, 35, 0, confidence=0.96))
    enriched = OcrSemanticObservationProvider(
        One(bundle),
        (OcrTargetSpec("SEARCH_EXECUTE", ("SEARCH",), min_confidence=0.90),),
    ).observe(CONTEXT)
    target = enriched.scene.require_target("SEARCH_EXECUTE", 0.90)
    assert target.confidence == 0.96
    assert target.metadata["grounding_mode"] == "scored_exact"


def test_phrase_assembly_enables_text_heavy_state_classification():
    bundle = make_bundle(
        word("f1", "New", 10, 10, 40, 30, 0),
        word("f1", "Troop", 45, 10, 95, 30, 1),
        word("f1", "MARCH", 10, 60, 70, 80, 2),
        word("f1", "Units", 10, 100, 60, 120, 3),
        word("f1", "Total", 10, 140, 55, 160, 4),
        word("f1", "Power", 60, 140, 110, 160, 5),
    )
    enriched = OcrSemanticObservationProvider(One(bundle)).observe(CONTEXT)
    result = StateClassifier().classify(enriched.observation, enriched.scene)
    assert result.state_id == "NEW_TROOP_SETUP"
    labels = {item.label for item in enriched.observation.evidence}
    assert "New Troop" in labels
    assert "Total Power" in labels


def test_phrase_assembly_keeps_words_on_different_lines_separate():
    bundle = make_bundle(
        word("f1", "New", 10, 10, 40, 30, 0),
        word("f1", "Troop", 45, 80, 95, 100, 1),
    )
    enriched = OcrSemanticObservationProvider(One(bundle)).observe(CONTEXT)
    assert "New Troop" not in {item.label for item in enriched.observation.evidence}
