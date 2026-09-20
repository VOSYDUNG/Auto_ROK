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
