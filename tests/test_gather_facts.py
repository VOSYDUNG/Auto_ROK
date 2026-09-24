from harness.contracts import BoundingBox, Evidence, Observation
from harness.gather_facts import (
    GatherFactObservationProvider,
    extract_march_queue,
    extract_visible_resource_level,
    extract_visible_troops_status,
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


def test_a_mangled_ocr_shape_is_no_longer_repaired_downstream():
    """"115" used to be normalised to 1/5 here. That workaround is gone.

    Windows.Media.Ocr renders the thin queue slash as a middle 1, and the fix
    was applied at the consumer. It was unsafe on its own terms: the pattern
    ([0-9])1([0-9]) also turns 213 into 2/3 and 919 into 9/9.

    The sensor was replaced instead - harness/queue_indicator.py reads the
    glyphs directly and emits "1/5", or refuses. Nothing downstream has to
    know the shape OCR used to mangle it into.
    """
    assert extract_march_queue(roi_bundle("115")) is None
    assert extract_march_queue(roi_bundle("213")) is None
    assert extract_march_queue(roi_bundle("919")) is None


def test_a_clean_reading_from_the_queue_roi_is_still_accepted():
    """What the template reader actually emits."""
    assert extract_march_queue(roi_bundle("1/5")) == (1, 5)
    assert extract_march_queue(roi_bundle("5/5")) == (5, 5)


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


def test_the_115_workaround_is_gone_from_provenance_too():
    """It was removed from the extractor and survived in march_queue_source.

    A second copy of a rule that was deliberately deleted is the same failure
    the forbidden-key denylist had: the test guarded one call site, so the
    other kept the behaviour. Here it could not invent a value, only claim
    that a value came from the queue region - provenance asserted on the
    strength of a pattern already known to read 213 as 2/3.
    """
    from pathlib import Path

    from harness import gather_facts

    # Comments explain why the pattern is gone and must be allowed to name it.
    code = [
        line
        for line in Path(gather_facts.__file__).read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    ]
    offenders = [line.strip() for line in code if "([0-9])1([0-9])" in line]
    assert not offenders, (
        f"the compact-ratio workaround is back in code: {offenders}; "
        "it reads 213 as 2/3 and 919 as 9/9"
    )


def troops_layout_bundle(*, status_box=None, missing_box=False, status_frame=None,
                         status_hash=None, extra_status=None, raw_text=""):
    """Synthetic OCR from the saved frame's observed relative layout."""
    frame = "troops-f1"
    image_hash = "a" * 64
    labels_and_boxes = [
        ("Troops", (646, 172, 719, 191)),
        ("Unrestricted", (575, 224, 648, 235)),
        ("Troop", (651, 224, 686, 237)),
        ("Movement", (690, 224, 753, 235)),
        ("Guide", (756, 224, 790, 235)),
        ("Gathering", status_box or (681, 318, 732, 330)),
    ]
    if extra_status:
        labels_and_boxes.append(extra_status)
    evidence = tuple(Evidence(
        "ocr", label, 0.0, value=label,
        bbox=None if missing_box and label == "Gathering" else BoundingBox(*coords),
        metadata={
            "frame_id": status_frame if label == "Gathering" and status_frame else frame,
            "image_sha256": status_hash if label == "Gathering" and status_hash else image_hash,
        },
    ) for label, coords in labels_and_boxes)
    return ObservationBundle(
        Observation(1.0, frame, (1366, 768), evidence),
        SceneGraph(frame, None, facts={"image_sha256": image_hash, "raw_text": raw_text}),
    )


def test_one_panel_anchored_gathering_token_projects_with_provenance():
    source = troops_layout_bundle()
    assert extract_visible_troops_status(source) == "Gathering"
    facts = GatherFactObservationProvider(One(source), character_id="hien").observe(CONTEXT).scene.facts
    assert facts["troops_visible_status"] == "Gathering"
    assert facts["troops_visible_status_source"] == "same_frame_ocr_troops_layout"
    assert facts["troops_visible_status_frame_id"] == "troops-f1"
    assert facts["troops_visible_status_image_sha256"] == "a" * 64
    assert not any(key in facts for key in ("troop_row_id", "return_detected", "free_slot",
                                              "buff_remaining", "return_travel_seconds"))


def test_troops_layout_rejects_unrelated_missing_and_stale_status_labels():
    complete = troops_layout_bundle()
    missing_subtitle = ObservationBundle(
        Observation(1.0, "troops-f1", (1366, 768),
                    tuple(item for item in complete.observation.evidence if item.label != "Guide")),
        complete.scene,
    )
    for source in (
        missing_subtitle,
        troops_layout_bundle(status_box=(20, 600, 71, 612)),
        troops_layout_bundle(missing_box=True),
        troops_layout_bundle(status_box=(732, 318, 681, 330)),
        troops_layout_bundle(status_frame="old-frame"),
        troops_layout_bundle(status_hash="b" * 64),
        troops_layout_bundle(extra_status=("Returning", (681, 350, 732, 362))),
        troops_layout_bundle(extra_status=("Gathering", (681, 350, 732, 362))),
    ):
        assert extract_visible_troops_status(source) is None
        facts = GatherFactObservationProvider(One(source), character_id="hien").observe(CONTEXT).scene.facts
        assert "troops_visible_status" not in facts


def test_raw_text_does_not_substitute_for_panel_status_evidence():
    source = troops_layout_bundle(status_frame="old-frame", raw_text="Troops Gathering")
    assert extract_visible_troops_status(source) is None


def test_troops_layout_requires_evidenced_window_profile():
    source = troops_layout_bundle()
    other_size = ObservationBundle(
        Observation(1.0, "troops-f1", (1280, 720), source.observation.evidence),
        source.scene,
    )
    assert extract_visible_troops_status(other_size) is None
    facts = GatherFactObservationProvider(One(other_size), character_id="hien").observe(CONTEXT).scene.facts
    assert "troops_visible_status" not in facts
