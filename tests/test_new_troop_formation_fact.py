"""Offline replay of archived positives and conservative formation refusals."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

from harness.contracts import BoundingBox, Evidence, Observation
from harness.gather_facts import GatherFactObservationProvider, extract_new_troop_formation_ready
from harness.mission_runtime import MissionContext
from harness.mission_tool import ObservationBundle
from harness.scene_graph import SceneGraph, VisualTarget


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_PATH = ROOT / "workspace/agents/f1c-evidence/root/new-troop-ocr-archive.json"
ARCHIVE = json.loads(ARCHIVE_PATH.read_text(encoding="utf-8")) if ARCHIVE_PATH.is_file() else {"frames": []}
CONTEXT = MissionContext("GATHER_RESOURCE", "task-1", "run-1")


class One:
    def __init__(self, bundle):
        self.bundle = bundle

    def observe(self, context):
        return self.bundle


def archive_bundle(record):
    """Rebuild the OCR result; the target is reconstructed from its MARCH token."""
    path = ROOT / record["path"]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest == record["sha256"]
    assert record["size"] == [1366, 768]
    frame = path.stem + "-" + path.parent.name
    evidence = []
    for token in record["ocr_tokens"]:
        x, y, width, height = token["bbox"]
        evidence.append(Evidence(
            "ocr", token["text"], 0.0, BoundingBox(x, y, x + width, y + height),
            token["text"], {"frame_id": frame, "image_sha256": digest},
        ))
    march = next(item for item in evidence if item.label == "MARCH")
    target = VisualTarget("TROOP_MARCH", frame, "MARCH", march.bbox, 0.0, "ocr",
                          {"frame_id": frame, "image_sha256": digest})
    return ObservationBundle(
        Observation(1.0, frame, (1366, 768), tuple(evidence)),
        SceneGraph(frame, None, (target,), {
            "image_path": str(path), "image_path_source": "current_capture_artifact",
            "image_sha256": digest, "raw_text": record["whole_text"],
        }),
    )


def synthetic_bundle(tmp_path):
    """Portable positive fixture; archived replay runs only where local images exist."""
    image = np.zeros((768, 1366, 3), dtype=np.uint8)
    image[245:465, 380:500] = (20, 60, 200)   # occupied primary portrait
    image[295:465, 520:595] = (20, 60, 200)   # occupied secondary portrait
    image[233:246, 703:735] = (30, 180, 30)  # selected troop slider
    image[568:607, 815:975] = (20, 130, 230) # active March button
    path = tmp_path / "base.png"
    assert cv2.imwrite(str(path), image)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    frame = "synthetic-new-troop"
    words = [
        ("New", (628, 141, 673, 157)),
        ("Troop", (679, 141, 741, 161)),
        ("Total", (665, 513, 695, 524)),
        ("Power:", (698, 513, 738, 524)),
        ("100,000", (742, 513, 793, 526)),
        ("39,757", (941, 235, 980, 247)),
        ("MARCH", (869, 572, 928, 584)),
    ]
    evidence = tuple(Evidence("ocr", word, 0.0, BoundingBox(*box), word,
                              {"frame_id": frame, "image_sha256": digest})
                     for word, box in words)
    march = evidence[-1]
    target = VisualTarget("TROOP_MARCH", frame, "MARCH", march.bbox, 0.0, "ocr",
                          {"frame_id": frame, "image_sha256": digest})
    return ObservationBundle(
        Observation(1.0, frame, (1366, 768), evidence),
        SceneGraph(frame, None, (target,), {
            "image_path": str(path), "image_path_source": "current_capture_artifact",
            "image_sha256": digest,
        }),
    )


def replace_image(bundle, tmp_path, *, rect, color):
    image = cv2.imread(bundle.scene.facts["image_path"])
    x1, y1, x2, y2 = rect
    image[y1:y2, x1:x2] = color
    path = tmp_path / "frame.png"
    assert cv2.imwrite(str(path), image)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    evidence = tuple(replace(item, metadata=dict(item.metadata) | {"image_sha256": digest})
                     for item in bundle.observation.evidence)
    targets = tuple(replace(target, metadata=dict(target.metadata) | {"image_sha256": digest})
                    for target in bundle.scene.targets)
    facts = dict(bundle.scene.facts) | {"image_path": str(path), "image_sha256": digest}
    return ObservationBundle(replace(bundle.observation, evidence=evidence),
                             replace(bundle.scene, targets=targets, facts=facts))


@pytest.mark.parametrize("record", [item for item in ARCHIVE["frames"]
                                    if (ROOT / item["path"]).is_file()],
                         ids=lambda item: Path(item["path"]).parent.name)
def test_archived_populated_new_troop_frames_project_readiness(record):
    source = archive_bundle(record)
    assert extract_new_troop_formation_ready(source) is True
    facts = GatherFactObservationProvider(One(source), character_id="character-1").observe(CONTEXT).scene.facts
    assert facts["new_troop_formation_ready"] is True
    assert facts["new_troop_formation_source"] == "same_frame_new_troop_ocr_and_pixels_1366x768"
    assert facts["new_troop_formation_frame_id"] == source.scene.frame_id
    assert facts["new_troop_formation_image_sha256"] == record["sha256"]


def test_portable_positive_projects_current_frame_readiness(tmp_path):
    source = synthetic_bundle(tmp_path)
    assert extract_new_troop_formation_ready(source) is True
    facts = GatherFactObservationProvider(One(source), character_id="character-1").observe(CONTEXT).scene.facts
    assert facts["new_troop_formation_ready"] is True
    assert facts["new_troop_formation_frame_id"] == source.scene.frame_id
    assert facts["new_troop_formation_image_sha256"] == source.scene.facts["image_sha256"]


def test_nonfirst_troop_row_is_accepted_when_game_selects_another_type(tmp_path):
    source = synthetic_bundle(tmp_path)
    moved = replace(source, observation=replace(
        source.observation,
        evidence=tuple(replace(item, bbox=BoundingBox(941, 365, 980, 377))
                       if item.label == "39,757" else item for item in source.observation.evidence),
    ))
    assert extract_new_troop_formation_ready(moved) is True


def test_missing_stale_wrong_layout_and_zero_facts_fail_closed(tmp_path):
    source = synthetic_bundle(tmp_path)
    missing_target = replace(source, scene=replace(source.scene, targets=()))
    stale_ocr = replace(source, observation=replace(
        source.observation,
        evidence=tuple(replace(item, metadata=dict(item.metadata) | {"frame_id": "old"})
                       for item in source.observation.evidence),
    ))
    wrong_hash = replace(source, scene=replace(
        source.scene, facts=dict(source.scene.facts) | {"image_sha256": "f" * 64},
    ))
    wrong_layout = replace(source, observation=replace(source.observation, window_size=(1280, 720)))
    moved_title = replace(source, observation=replace(
        source.observation,
        evidence=tuple(replace(item, bbox=BoundingBox(20, 20, 65, 36))
                       if item.label == "New" else item for item in source.observation.evidence),
    ))
    stale_target = replace(source, scene=replace(
        source.scene, targets=(replace(source.scene.targets[0],
                                       metadata={"frame_id": source.scene.frame_id,
                                                 "image_sha256": "e" * 64}),),
    ))
    no_image_source = replace(source, scene=replace(source.scene, facts={
        **source.scene.facts, "image_path_source": "archive_path",
    }))
    zero = replace(source, observation=replace(
        source.observation,
        evidence=tuple(replace(item, label="0", value="0") if item.label == "39,757" else item
                       for item in source.observation.evidence),
    ))
    missing_power_label = replace(source, observation=replace(
        source.observation,
        evidence=tuple(item for item in source.observation.evidence if item.label != "Power:"),
    ))
    for denied in (missing_target, stale_ocr, stale_target, wrong_hash,
                   wrong_layout, moved_title, no_image_source, zero, missing_power_label):
        assert extract_new_troop_formation_ready(denied) is False
        forged = replace(denied, scene=replace(denied.scene, facts={
            **denied.scene.facts, "new_troop_formation_ready": True,
        }))
        facts = GatherFactObservationProvider(One(forged), character_id="character-1").observe(CONTEXT).scene.facts
        assert "new_troop_formation_ready" not in facts


@pytest.mark.parametrize("rect,color", [
    ((815, 568, 975, 607), (90, 90, 90)),       # grey, inactive March
    ((520, 295, 595, 465), (240, 210, 90)),    # empty cyan second portrait
    ((380, 245, 500, 465), (240, 210, 90)),    # empty cyan first portrait
    ((703, 233, 735, 246), (100, 50, 20)),     # no selected troop slider
])
def test_pixel_negative_fails_even_with_valid_ocr_and_rehashed_image(tmp_path, rect, color):
    source = synthetic_bundle(tmp_path)
    edited = replace_image(source, tmp_path, rect=rect, color=color)
    assert extract_new_troop_formation_ready(edited) is False


NATIVE_NEW_TROOP = ROOT / "workspace/runtime/gather_resource-87d063bc35de06f9/observation-3c9b85d07a4c4a0a896bfca100f91b9e"


@pytest.mark.skipif(not (NATIVE_NEW_TROOP / "current.png").exists(), reason="stored native New Troop frame unavailable")
def test_native_new_troop_roi_reaches_classifier_and_formation_fact():
    """The measured Units ROI and blue selected-row signature close the offline chain."""
    from datetime import datetime
    from harness.observation_bridge import project_observation
    from harness.ocr_semantics import OcrSemanticObservationProvider, OcrTargetSpec
    from harness.state_classifier import StateClassifier
    from harness.windows_ocr_direct import WindowsOcr, recognize_with_regions

    capture = json.loads((NATIVE_NEW_TROOP / "capture.json").read_text())
    payload = recognize_with_regions(NATIVE_NEW_TROOP / "current.png", capture,
                                     engine=WindowsOcr())
    projected = project_observation(
        capture, payload, NATIVE_NEW_TROOP / "current.png",
        now=datetime.fromisoformat(capture["frame"]["captured_at"]),
    )
    scene = replace(projected.scene, facts={
        **projected.scene.facts,
        "image_path": str(NATIVE_NEW_TROOP / "current.png"),
        "image_path_source": "current_capture_artifact",
    })

    class Stored:
        def observe(self, context):
            return ObservationBundle(projected.observation, scene)

    inner = OcrSemanticObservationProvider(
        Stored(), [OcrTargetSpec("TROOP_MARCH", ("MARCH",), allow_unscored_exact=True)]
    )
    bundle = GatherFactObservationProvider(inner, character_id="character-1").observe(CONTEXT)
    assert StateClassifier().classify(bundle.observation, bundle.scene).state_id == "NEW_TROOP_SETUP"
    assert bundle.scene.facts["new_troop_formation_ready"] is True


@pytest.mark.skipif(not (NATIVE_NEW_TROOP / "current.png").exists(), reason="stored native New Troop frame unavailable")
def test_native_empty_row_transplant_rejects_knob_only_selection(tmp_path):
    """A real zero row transplanted over row one must not pass the pixel guard."""
    from harness.gather_facts import _new_troop_pixels

    source = cv2.imread(str(NATIVE_NEW_TROOP / "current.png"))
    assert source is not None
    transplanted = source.copy()
    transplanted[233:246, 703:735] = source[297:310, 703:735]
    path = tmp_path / "native-empty-row-transplant.png"
    assert cv2.imwrite(str(path), transplanted)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert _new_troop_pixels(str(path), digest) is False
