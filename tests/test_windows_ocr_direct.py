"""In-process Windows.Media.Ocr.

The contract tests run anywhere. The one that needs the real engine is skipped
when the winrt bindings are absent, so the suite stays runnable without them.
"""
import json
from pathlib import Path

import pytest

from harness.windows_ocr_direct import (
    BACKEND_NAME,
    SCHEMA_VERSION,
    WindowsOcrError,
    build_payload,
)

ROOT = Path(__file__).resolve().parents[1]
FRAME = ROOT / "workspace" / "runs" / "p3-observe-20260920" / "frame-01.png"
CAPTURE = ROOT / "workspace" / "runs" / "p3-observe-20260920" / "capture-01.json"

CAPTURE_STUB = {
    "frame": {
        "id": "rok-test",
        "width": 4,
        "height": 2,
        "client_bounds": [0, 0, 4, 2],
        "dpi_scale": 1.0,
        "image_sha256": "0" * 64,
    }
}


def test_the_payload_keeps_the_shape_the_powershell_path_emitted():
    """Consumers read this record; its shape is a contract, not a detail."""
    elements = [
        {"bbox": [1, 2, 3, 4], "word_index": 0, "confidence": None,
         "text": "1/5", "line_index": 0}
    ]
    payload = build_payload(
        elements, CAPTURE_STUB, image_sha256="0" * 64,
        width=4, height=2, language="en-US",
    )
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["backend"]["name"] == BACKEND_NAME
    assert payload["coordinate_space"] == "ocr_crop_pixels"
    assert payload["output_coordinate_space"] == "client_pixels"
    assert payload["crop"] == [0, 0, 4, 2]
    assert payload["scale_x"] == 1.0 and payload["scale_y"] == 1.0
    assert payload["frame_id"] == "rok-test"
    assert payload["text"] == "1/5"
    assert payload["elements"] == elements


def test_the_joined_text_is_built_from_the_elements():
    elements = [
        {"text": "a", "bbox": [0, 0, 1, 1], "word_index": 0, "confidence": None, "line_index": 0},
        {"text": "b", "bbox": [2, 0, 1, 1], "word_index": 1, "confidence": None, "line_index": 0},
    ]
    payload = build_payload(
        elements, CAPTURE_STUB, image_sha256="x", width=4, height=2, language="en-US"
    )
    assert payload["text"] == "a b"


def test_the_payload_is_json_serialisable():
    payload = build_payload(
        [], CAPTURE_STUB, image_sha256="x", width=4, height=2, language="en-US"
    )
    assert json.loads(json.dumps(payload))["elements"] == []


def test_a_frame_that_contradicts_its_capture_metadata_is_refused():
    import numpy as np

    from harness.windows_ocr_direct import recognize_frame

    pytest.importorskip("cv2")
    wrong = np.zeros((9, 9, 3), dtype=np.uint8)
    with pytest.raises(WindowsOcrError, match="capture metadata declares"):
        recognize_frame(wrong, CAPTURE_STUB)


def test_a_non_image_array_is_refused():
    import numpy as np

    from harness.windows_ocr_direct import recognize_frame

    pytest.importorskip("cv2")
    with pytest.raises(WindowsOcrError, match="HxWx3"):
        recognize_frame(np.zeros((4, 4), dtype=np.uint8), CAPTURE_STUB)


def _winrt_available() -> bool:
    try:
        import winrt.windows.media.ocr  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.mark.skipif(not _winrt_available(), reason="winrt bindings not installed")
@pytest.mark.skipif(not FRAME.exists(), reason="live capture not present")
def test_it_reproduces_the_powershell_output_on_a_real_frame():
    """OCR-004. Same engine, no process boundary, identical elements."""
    from harness.windows_ocr_direct import WindowsOcr, recognize_path

    capture = json.loads(CAPTURE.read_text(encoding="utf-8"))
    payload = recognize_path(FRAME, capture, engine=WindowsOcr())

    assert payload["frame_id"] == capture["frame"]["id"]
    assert payload["image_sha256"] == capture["frame"]["image_sha256"]
    assert payload["client_bounds"] == capture["frame"]["client_bounds"]
    assert len(payload["elements"]) == 75

    queue_decoys = [e for e in payload["elements"] if e["text"] == "(5/5)"]
    assert queue_decoys, "the Trade Deal decoy is part of this frame"

    for element in payload["elements"]:
        assert set(element) == {"bbox", "word_index", "confidence", "text", "line_index"}
        assert len(element["bbox"]) == 4


CITY_FRAME = ROOT / "workspace" / "runs" / "m7-live-20260920" / "city-01.png"
CITY_CAPTURE = ROOT / "workspace" / "runs" / "m7-live-20260920" / "capture-01.json"

#: The quest panel, in client pixels. Byte-identical in the world-map frame
#: and the city frame - the same panel, the same text, the same place.
QUEST_PANEL = (0, 180, 180, 280)


def test_a_region_that_runs_off_the_frame_is_refused_not_clamped():
    import numpy as np

    from harness.windows_ocr_direct import recognize_frame

    pytest.importorskip("cv2")
    frame = np.zeros((2, 4, 3), dtype=np.uint8)
    for bad in ((0, 0, 5, 1), (-1, 0, 2, 1), (3, 0, 2, 1)):
        with pytest.raises(WindowsOcrError, match="does not fit inside"):
            recognize_frame(frame, CAPTURE_STUB, roi=bad)
    with pytest.raises(WindowsOcrError, match="must be positive"):
        recognize_frame(frame, CAPTURE_STUB, roi=(0, 0, 0, 1))


def test_the_payload_reports_the_crop_and_scale_it_actually_used():
    """A wrong scale silently relocates every grounded target."""
    payload = build_payload(
        [], CAPTURE_STUB, image_sha256="x", width=4, height=2,
        language="en-US", crop=(1, 0, 2, 2), scale=4.0,
    )
    assert payload["crop"] == [1, 0, 2, 2]
    assert payload["scale_x"] == 4.0 and payload["scale_y"] == 4.0


@pytest.mark.skipif(not _winrt_available(), reason="winrt bindings not installed")
@pytest.mark.skipif(not CITY_FRAME.exists(), reason="live city capture not present")
def test_whole_frame_ocr_collapses_on_a_busy_scene_but_the_roi_does_not():
    """Why ROI-only is correctness, not tuning - DESIGN_BRIEF D1b.

    Measured 2026-09-20 against two real frames from one session. The quest
    panel is identical in both. Swept as part of the whole frame it survives
    on the world map and vanishes in the city; cropped out on its own it
    reads the same in either. The frame around the text decides whether the
    text is read at all, which means a full-frame sweep fails by returning
    nothing rather than by returning an error.
    """
    from harness.windows_ocr_direct import WindowsOcr, recognize_path

    engine = WindowsOcr()
    city_capture = json.loads(CITY_CAPTURE.read_text(encoding="utf-8"))

    whole = recognize_path(CITY_FRAME, city_capture, engine=engine)
    panel = recognize_path(
        CITY_FRAME, city_capture, engine=engine, roi=QUEST_PANEL
    )

    assert len(whole["elements"]) < 10, (
        "the city frame is expected to defeat a full-frame sweep; if this "
        "starts passing, the engine changed and D1b needs re-measuring"
    )
    assert len(panel["elements"]) > 25
    assert "Courier Station" in panel["text"]

    # And the same panel inside the world frame does survive the sweep, which
    # is what makes the failure state-dependent rather than a broken ROI.
    if FRAME.exists():
        world = recognize_path(FRAME, json.loads(CAPTURE.read_text(encoding="utf-8")), engine=engine)
        assert len(world["elements"]) > 50


@pytest.mark.skipif(not _winrt_available(), reason="winrt bindings not installed")
@pytest.mark.skipif(not CITY_FRAME.exists(), reason="live city capture not present")
def test_an_roi_box_maps_back_into_client_pixels():
    """OCR-002 depends on this: a box is useless if it lands somewhere else."""
    from harness.windows_ocr_direct import WindowsOcr, recognize_path

    header = (1020, 0, 346, 26)
    payload = recognize_path(
        CITY_FRAME,
        json.loads(CITY_CAPTURE.read_text(encoding="utf-8")),
        engine=WindowsOcr(),
        roi=header,
        scale=4,
    )
    assert payload["crop"] == list(header)
    assert payload["scale_x"] == 4.0

    crop_x, crop_y, crop_w, crop_h = header
    for element in payload["elements"]:
        x, y, width, height = element["bbox"]
        client_x = crop_x + round(x / payload["scale_x"])
        client_y = crop_y + round(y / payload["scale_y"])
        assert crop_x <= client_x <= crop_x + crop_w
        assert crop_y <= client_y <= crop_y + crop_h


@pytest.mark.skipif(not _winrt_available(), reason="winrt bindings not installed")
def test_control_characters_are_stripped_the_way_the_old_path_did():
    from harness.windows_ocr_direct import _clean

    assert _clean("a\x00b\x1fc") == "abc"
    assert _clean("1/5") == "1/5"
    assert _clean("\t keep \n") == "\t keep \n"


def test_light_label_preprocessing_preserves_geometry_and_records_pixels(monkeypatch):
    import numpy as np
    from harness.windows_ocr_direct import recognize_frame

    pytest.importorskip("cv2")
    monkeypatch.setattr("harness.windows_ocr_direct._os_version", lambda: "test")

    class Engine:
        language = "en-US"

        def recognize(self, buffer, width, height):
            assert (width, height) == (4, 4)
            pixels = np.frombuffer(buffer, dtype=np.uint8).reshape(height, width, 4)
            assert set(pixels[:, :, 0].flat) == {0, 255}
            # A bright coloured pixel is background; all channels must pass.
            assert pixels[0, 0, 0] == 255
            assert pixels[0, 2, 0] == 0
            return [{"text": "Cropland", "bbox": [0, 0, 4, 4], "line_index": 0, "word_index": 0}]

    frame = np.zeros((2, 4, 3), dtype=np.uint8)
    frame[0, 1] = [0, 200, 200]
    frame[0, 2] = [200, 200, 200]
    payload = recognize_frame(frame, CAPTURE_STUB, engine=Engine(), roi=(1, 0, 2, 2), scale=2, light_text_threshold=85)
    assert payload["crop"] == [1, 0, 2, 2]
    assert payload["scale_x"] == 2
    assert payload["image_sha256"] == CAPTURE_STUB["frame"]["image_sha256"]
    assert payload["preprocessing"] == {"name": "light_text_min_bgr", "threshold": 85}


@pytest.mark.parametrize("key,value", [("frame_id", "other"), ("image_sha256", "1" * 64), ("client_bounds", [0, 0, 5, 2])])
def test_region_merge_refuses_mismatched_provenance(monkeypatch, key, value):
    from harness.windows_ocr_direct import merge_region_elements

    monkeypatch.setattr("harness.windows_ocr_direct._os_version", lambda: "test")
    base = build_payload([], CAPTURE_STUB, image_sha256="0" * 64, width=4, height=2, language="en-US")
    region = dict(base, **{key: value})
    with pytest.raises(WindowsOcrError, match=key):
        merge_region_elements(base, region, region_id="search")


def test_region_merge_maps_actual_words_and_retains_region_authority(monkeypatch):
    from harness.windows_ocr_direct import merge_region_elements

    monkeypatch.setattr("harness.windows_ocr_direct._os_version", lambda: "test")
    base = build_payload([], CAPTURE_STUB, image_sha256="0" * 64, width=4, height=2, language="en-US")
    region = build_payload([{"text": "SEARCH", "bbox": [0, 0, 4, 4]}], CAPTURE_STUB,
                           image_sha256="0" * 64, width=4, height=2, language="en-US", crop=(1, 0, 2, 2), scale=2)
    merged = merge_region_elements(base, region, region_id="search_execution_strip")
    word = merged["elements"][0]
    assert word["bbox"] == [1, 0, 2, 2]
    assert word["confidence"] is None
    assert word["acquisition"] == "ocr_search_execution_strip"
    region["elements"][0]["bbox"] = [0, 0, 5, 4]
    with pytest.raises(WindowsOcrError, match="outside its OCR crop"):
        merge_region_elements(base, region)


def test_all_regions_use_one_decoded_frame_and_layout_override_is_refused(tmp_path, monkeypatch):
    import hashlib
    import numpy as np
    from harness.cpu_roi import load_default_cpu_roi_profile
    from harness.windows_ocr_direct import recognize_with_regions

    cv2 = pytest.importorskip("cv2")
    monkeypatch.setattr("harness.windows_ocr_direct._os_version", lambda: "test")
    image = tmp_path / "frame.png"
    cv2.imwrite(str(image), np.zeros((768, 1366, 3), dtype=np.uint8))
    capture = {"frame": dict(CAPTURE_STUB["frame"], width=1366, height=768, client_bounds=[0, 0, 1366, 768],
                            image_sha256=hashlib.sha256(image.read_bytes()).hexdigest())}

    class Engine:
        language = "en-US"
        calls = 0

        def recognize(self, buffer, width, height):
            self.calls += 1
            if self.calls == 1:
                cv2.imwrite(str(image), np.full((768, 1366, 3), 255, dtype=np.uint8))
            # Pale-label processing turns the original blank black crop white.
            assert set(buffer[0::4]) == ({255} if self.calls == 2 else {0})
            return []

    engine = Engine()
    result = recognize_with_regions(image, capture, engine=engine, regions=("resource_category_cropland",))
    assert engine.calls == 2 and not result["elements"]
    # Restore the original file; the wrong layout must never shift OCR boxes.
    cv2.imwrite(str(image), np.zeros((768, 1366, 3), dtype=np.uint8))
    with pytest.raises(WindowsOcrError, match="window size"):
        recognize_with_regions(image, capture, engine=engine, window_size=(1280, 720))
    assert load_default_cpu_roi_profile().reference_client_size == (1366, 768)


SEARCH_REPLAY = ROOT / "workspace" / "runs" / "f6-search-blocker-20260927-01"
CURRENT_SEARCH_REPLAY = ROOT / "workspace" / "runtime" / "gather_resource-47aa1a0f9012e418" / "observation-65c9a529e01346229f8421c5da3023a6"


@pytest.mark.skipif(not _winrt_available(), reason="winrt bindings not installed")
@pytest.mark.skipif(not (CURRENT_SEARCH_REPLAY / "current.png").exists(), reason="native Search regression frame unavailable")
def test_search_scale_regression_restores_exact_region_target_from_native_frame():
    from datetime import datetime
    from harness.mission_tool import ObservationBundle
    from harness.observation_bridge import project_observation
    from harness.ocr_semantics import OcrSemanticObservationProvider, OcrTargetSpec
    from harness.windows_ocr_direct import WindowsOcr, recognize_path, recognize_with_regions
    from harness.state_classifier import StateClassifier

    capture = json.loads((CURRENT_SEARCH_REPLAY / "capture.json").read_text())
    assert capture["frame"]["image_sha256"] == "97e5e856b03191c3c777da631891bc689677d093a2f6c7a1118dd52b8779ff71"
    engine = WindowsOcr()
    old = recognize_path(CURRENT_SEARCH_REPLAY / "current.png", capture, engine=engine,
                         roi=(330, 562, 740, 50), scale=2)
    assert old["elements"] == []
    payload = recognize_with_regions(CURRENT_SEARCH_REPLAY / "current.png", capture, engine=engine)
    projection = project_observation(capture, payload, CURRENT_SEARCH_REPLAY / "current.png",
                                     now=datetime.fromisoformat(capture["frame"]["captured_at"]))

    class Stored:
        def observe(self, context):
            return ObservationBundle(projection.observation, projection.scene)

    spec = OcrTargetSpec("SEARCH_EXECUTE", ("SEARCH",), allow_unscored_exact=True,
                        require_acquisition="ocr_search_execution_strip")
    bundle = OcrSemanticObservationProvider(Stored(), [spec]).observe(None)
    assert StateClassifier().classify(bundle.observation, bundle.scene).state_id == "RESOURCE_SEARCH_PANEL"
    assert len(bundle.scene.targets) == 1
    target = bundle.scene.targets[0]
    assert target.target_id == "SEARCH_EXECUTE" and target.frame_id == capture["frame"]["id"]
    assert target.metadata["acquisition"] == "ocr_search_execution_strip"
    assert 330 <= target.bbox.x1 < target.bbox.x2 <= 1070
    assert 562 <= target.bbox.y1 < target.bbox.y2 <= 612


@pytest.mark.skipif(not _winrt_available(), reason="winrt bindings not installed")
@pytest.mark.skipif(not (SEARCH_REPLAY / "current.png").exists(), reason="stored Search frame unavailable")
def test_stored_search_frame_reaches_classifier_and_exact_action_targets():
    from datetime import datetime
    from harness.mission_tool import ObservationBundle
    from harness.observation_bridge import project_observation
    from harness.ocr_semantics import OcrSemanticObservationProvider, OcrTargetSpec
    from harness.state_classifier import StateClassifier
    from harness.windows_ocr_direct import WindowsOcr, recognize_with_regions

    capture = json.loads((SEARCH_REPLAY / "capture.json").read_text())
    payload = recognize_with_regions(SEARCH_REPLAY / "current.png", capture, engine=WindowsOcr())
    projection = project_observation(capture, payload, SEARCH_REPLAY / "current.png",
                                     now=datetime.fromisoformat(capture["frame"]["captured_at"]))

    class Stored:
        def observe(self, context):
            return ObservationBundle(projection.observation, projection.scene)

    names = {"SEARCH": "search_execution_strip", "Cropland": "resource_category_cropland",
             "Logging Camp": "resource_category_logging_camp", "Stone Deposit": "resource_category_stone_deposit",
             "Gold Deposit": "resource_category_gold_deposit"}
    specs = [OcrTargetSpec(name, (name,), allow_unscored_exact=True, require_acquisition=f"ocr_{region}")
             for name, region in names.items()]
    bundle = OcrSemanticObservationProvider(Stored(), specs).observe(None)
    assert StateClassifier().classify(bundle.observation, bundle.scene).state_id == "RESOURCE_SEARCH_PANEL"
    assert {target.target_id for target in bundle.scene.targets} == set(names)
    for target in bundle.scene.targets:
        assert target.frame_id == capture["frame"]["id"]
        assert target.metadata["acquisition"] == f"ocr_{names[target.target_id]}"
        assert target.confidence == 0.0
        assert target.metadata["unscored_exact_authorized"] is True
        assert 330 <= target.bbox.x1 < target.bbox.x2 <= 1055
        assert (562 <= target.bbox.y1 < target.bbox.y2 <= 612 if target.target_id == "SEARCH"
                else 732 <= target.bbox.y1 < target.bbox.y2 <= 756)
    # Replay the actual canonical target configuration as well, without the
    # test's stricter acquisition requirement. Region reads must not introduce
    # duplicate labels that make the real runner's targets ambiguous.
    raw_specs = json.loads((ROOT / "config" / "gather_ocr_targets.json").read_text())
    canonical = [OcrTargetSpec(**dict(item, labels=tuple(item["labels"]))) for item in raw_specs]
    actual = OcrSemanticObservationProvider(Stored(), canonical).observe(None)
    assert {target.target_id for target in actual.scene.targets} == {
        "SEARCH_CATEGORY_FOOD", "SEARCH_CATEGORY_WOOD", "SEARCH_CATEGORY_STONE", "SEARCH_CATEGORY_GOLD", "SEARCH_EXECUTE"}


@pytest.mark.parametrize("shape", [(768, 1366), (400, 400)])
def test_blank_or_unsupported_layout_adds_no_search_facts(tmp_path, monkeypatch, shape):
    import hashlib
    import numpy as np
    from harness.contracts import Observation
    from harness.state_classifier import UNKNOWN_STATE, StateClassifier
    from harness.windows_ocr_direct import recognize_with_regions

    cv2 = pytest.importorskip("cv2")
    monkeypatch.setattr("harness.windows_ocr_direct._os_version", lambda: "test")
    height, width = shape
    image = tmp_path / "blank.png"
    cv2.imwrite(str(image), np.zeros((height, width, 3), dtype=np.uint8))
    capture = {"frame": dict(CAPTURE_STUB["frame"], width=width, height=height, client_bounds=[0, 0, width, height],
                            image_sha256=hashlib.sha256(image.read_bytes()).hexdigest())}

    class Engine:
        language = "en-US"
        calls = 0

        def recognize(self, buffer, width, height):
            self.calls += 1
            return []

    engine = Engine()
    payload = recognize_with_regions(image, capture, engine=engine)
    assert not payload["elements"] and not payload["text"]
    assert StateClassifier().classify(Observation(1.0, "rok-test", (width, height), ())).state_id == UNKNOWN_STATE
    if width == 400:
        assert engine.calls == 1  # Aspect mismatch skips every calibrated ROI.
    capture["frame"]["image_sha256"] = "1" * 64
    with pytest.raises(WindowsOcrError, match="hash does not match"):
        recognize_with_regions(image, capture, engine=engine)


@pytest.mark.skipif(not _winrt_available(), reason="winrt bindings not installed")
@pytest.mark.parametrize("image,capture_path", [(FRAME, CAPTURE), (CITY_FRAME, CITY_CAPTURE)])
def test_search_label_regions_do_not_classify_stored_world_or_city(image, capture_path):
    from harness.contracts import Evidence, Observation
    from harness.state_classifier import StateClassifier
    from harness.windows_ocr_direct import WindowsOcr, recognize_with_regions

    if not image.exists() or not capture_path.exists():
        pytest.skip("stored control frame unavailable")
    capture = json.loads(capture_path.read_text())
    payload = recognize_with_regions(image, capture, engine=WindowsOcr())
    # The legacy city control has no captured_at. This checks classification
    # from real OCR words only, without claiming a complete capture projection.
    evidence = tuple(Evidence("ocr", word["text"], 0.0, value=word["text"],
                              metadata={"frame_id": payload["frame_id"]}) for word in payload["elements"])
    observed = Observation(1.0, payload["frame_id"], tuple(payload["client_bounds"][2:]), evidence)
    assert StateClassifier().classify(observed).state_id != "RESOURCE_SEARCH_PANEL"


def test_region_merge_rounds_endpoints_and_refuses_collapsed_boxes(monkeypatch):
    from harness.windows_ocr_direct import merge_region_elements

    monkeypatch.setattr("harness.windows_ocr_direct._os_version", lambda: "test")
    base = build_payload([], CAPTURE_STUB, image_sha256="0" * 64, width=4, height=2, language="en-US")
    region = build_payload([{"text": "label", "bbox": [1, 0, 2, 4]}], CAPTURE_STUB,
                           image_sha256="0" * 64, width=4, height=2, language="en-US", crop=(1, 0, 2, 2), scale=2)
    # round(x) + round(width) yields right=1; round(x+width) yields right=2.
    merged = merge_region_elements(base, region, region_id="point")
    assert merged["elements"][0]["bbox"] == [1, 0, 2, 2]
    region["elements"][0]["bbox"] = [0, 0, 1, 4]
    with pytest.raises(WindowsOcrError, match="no valid client-pixel extent"):
        merge_region_elements(base, region, region_id="point")


DETAIL_REPLAY = ROOT / "workspace" / "runs" / "f6-detail-blocker-20260927-01"


@pytest.mark.skipif(not _winrt_available(), reason="winrt bindings not installed")
@pytest.mark.skipif(not (DETAIL_REPLAY / "current.png").exists(), reason="stored detail frame unavailable")
def test_stored_detail_frame_classifies_and_suppresses_background_coordinates():
    from dataclasses import replace
    from datetime import datetime
    from harness.map_coordinate import COORDINATE_EVIDENCE
    from harness.map_coordinate_provider import MapCoordinateObservationProvider
    from harness.main_view_detector import MainViewProfile, MainViewVisualObservationProvider
    from harness.mission_tool import ObservationBundle
    from harness.observation_bridge import project_observation
    from harness.ocr_semantics import OcrSemanticObservationProvider, OcrTargetSpec
    from harness.state_classifier import StateClassifier
    from harness.windows_ocr_direct import WindowsOcr, recognize_with_regions

    capture = json.loads((DETAIL_REPLAY / "capture.json").read_text())
    payload = recognize_with_regions(DETAIL_REPLAY / "current.png", capture, engine=WindowsOcr())
    projected = project_observation(capture, payload, DETAIL_REPLAY / "current.png",
                                    now=datetime.fromisoformat(capture["frame"]["captured_at"]))

    class Stored:
        def observe(self, context):
            scene = replace(projected.scene, facts=dict(projected.scene.facts, image_path=str(DETAIL_REPLAY / "current.png")))
            return ObservationBundle(projected.observation, scene)

    raw = json.loads((ROOT / "config/gather_ocr_targets.json").read_text())
    specs = [OcrTargetSpec(**dict(item, labels=tuple(item["labels"]))) for item in raw]
    semantic = OcrSemanticObservationProvider(Stored(), specs)
    main_view = MainViewVisualObservationProvider(semantic, MainViewProfile.load(ROOT / "config/main_view_profiles.json"))
    provider = MapCoordinateObservationProvider(main_view)
    bundle = provider.observe(None)
    result = StateClassifier().classify(bundle.observation, bundle.scene)
    assert result.state_id == "RESOURCE_POINT_DETAIL"
    assert result.ambiguity["candidate_states"] == ("RESOURCE_POINT_DETAIL",)
    assert bundle.scene.facts["map_coordinate_readout"]["status"] == "suppressed"
    assert bundle.scene.facts["main_view_detector"]["status"] == "suppressed"
    assert not any(item.label == COORDINATE_EVIDENCE for item in bundle.observation.evidence)
    assert {target.target_id for target in bundle.scene.targets} == {"RESOURCE_GATHER"}
    target = bundle.scene.targets[0]
    assert target.metadata["acquisition"] == "ocr_resource_point_gather"
    assert target.metadata["image_sha256"] == capture["frame"]["image_sha256"]
    assert target.frame_id == capture["frame"]["id"]
    assert target.label == "GATHER" and target.confidence == 0
    assert (target.bbox.x1, target.bbox.y1, target.bbox.x2, target.bbox.y2) == (851, 466, 937, 486)
    assert {item.metadata["acquisition"] for item in result.matching_evidence} == {
        "ocr_resource_point_header", "ocr_resource_point_gather"}


@pytest.mark.skipif(not _winrt_available(), reason="winrt bindings not installed")
@pytest.mark.parametrize("image,capture_path", [(FRAME, CAPTURE), (CITY_FRAME, CITY_CAPTURE),
                                               (SEARCH_REPLAY / "current.png", SEARCH_REPLAY / "capture.json")])
def test_detail_regions_do_not_ground_gather_on_control_frames(image, capture_path):
    from harness.contracts import Evidence, Observation
    from harness.state_classifier import StateClassifier
    from harness.windows_ocr_direct import WindowsOcr, recognize_with_regions

    if not image.exists() or not capture_path.exists():
        pytest.skip("stored control unavailable")
    capture = json.loads(capture_path.read_text())
    payload = recognize_with_regions(image, capture, engine=WindowsOcr())
    assert not any(item.get("acquisition") == "ocr_resource_point_gather" and item["text"] == "GATHER"
                   for item in payload["elements"])
    evidence = tuple(Evidence("ocr", item["text"], 0.0, value=item["text"],
                              metadata={"frame_id": payload["frame_id"]}) for item in payload["elements"])
    observed = Observation(1.0, payload["frame_id"], tuple(payload["client_bounds"][2:]), evidence)
    assert StateClassifier().classify(observed).state_id != "RESOURCE_POINT_DETAIL"


def test_resource_gather_requires_its_actual_region_acquisition():
    from harness.contracts import BoundingBox, Evidence, Observation
    from harness.mission_tool import ObservationBundle
    from harness.ocr_semantics import OcrSemanticObservationProvider, OcrTargetSpec
    from harness.scene_graph import SceneGraph

    raw = next(item for item in json.loads((ROOT / "config/gather_ocr_targets.json").read_text())
               if item["target_id"] == "RESOURCE_GATHER")
    spec = OcrTargetSpec(**dict(raw, labels=tuple(raw["labels"])))

    class Stored:
        def observe(self, context):
            item = Evidence("ocr", "GATHER", 0.0, BoundingBox(800, 450, 900, 480), "GATHER",
                            {"frame_id": "frame", "confidence_known": False, "acquisition": "ocr_whole_frame"})
            return ObservationBundle(Observation(1.0, "frame", (1366, 768), (item,)), SceneGraph("frame", None))

    assert not OcrSemanticObservationProvider(Stored(), [spec]).observe(None).scene.targets


def test_default_region_set_consumes_measured_new_troop_units_roi(monkeypatch, tmp_path):
    import hashlib
    import numpy as np
    import cv2
    from harness.windows_ocr_direct import recognize_with_regions

    image = np.zeros((768, 1366, 3), dtype=np.uint8)
    path = tmp_path / "frame.png"
    assert cv2.imwrite(str(path), image)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    capture = {"frame": {"id": "frame", "width": 1366, "height": 768,
                          "client_bounds": [0, 0, 1366, 768], "image_sha256": digest}}

    class Engine:
        language = "en-US"
        calls = []

        def recognize(self, buffer, width, height):
            self.calls.append((width, height))
            return [{"text": "Units:", "bbox": [2, 2, 20, 8],
                     "word_index": 0, "confidence": None, "line_index": 0}]

    engine = Engine()
    payload = recognize_with_regions(path, capture, engine=engine,
                                     regions=("new_troop_units",))
    units = [item for item in payload["elements"] if item.get("acquisition") == "ocr_new_troop_units"]
    assert len(units) == 1
    assert units[0]["text"] == "Units:"
    assert units[0]["bbox"] == [661, 481, 10, 4]
