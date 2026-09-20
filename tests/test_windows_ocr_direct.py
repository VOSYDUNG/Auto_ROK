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


@pytest.mark.skipif(not _winrt_available(), reason="winrt bindings not installed")
def test_control_characters_are_stripped_the_way_the_old_path_did():
    from harness.windows_ocr_direct import _clean

    assert _clean("a\x00b\x1fc") == "abc"
    assert _clean("1/5") == "1/5"
    assert _clean("\t keep \n") == "\t keep \n"
