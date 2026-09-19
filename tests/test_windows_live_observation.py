from pathlib import Path
import json

import pytest

from harness.windows_live_observation import WindowsLiveObservationProvider


def test_windows_live_observation_defaults_to_canonical_windows_ocr(tmp_path):
    provider = WindowsLiveObservationProvider(tmp_path)
    assert provider.ocr_backend == "windows"
    assert provider._rapidocr_backend is None


def test_rapidocr_fixed_roi_is_explicit_opt_in(tmp_path):
    provider = WindowsLiveObservationProvider(
        tmp_path,
        ocr_backend="rapidocr_fixed_roi_experiment",
    )
    assert provider.ocr_backend == "rapidocr_fixed_roi_experiment"
    assert provider._rapidocr_backend is None


def test_unknown_ocr_backend_fails_closed(tmp_path):
    with pytest.raises(ValueError, match="ocr_backend"):
        WindowsLiveObservationProvider(tmp_path, ocr_backend="free_form")


def test_rapidocr_overlay_is_frame_bound_and_keeps_base_words(tmp_path):
    provider = WindowsLiveObservationProvider(
        tmp_path,
        ocr_backend="rapidocr_fixed_roi_experiment",
    )

    class FakeBackend:
        def recognize_image(self, image, *, frame_id, expected_sha256):
            assert Path(image).name == "frame.png"
            assert frame_id == "frame-1"
            assert expected_sha256 == "sha-1"
            return {
                "image": str(image),
                "image_sha256": "sha-1",
                "frame_id": "frame-1",
                "roi_profile_id": "profile-1",
                "results": [
                    {
                        "rect": [350, 732, 105, 24],
                        "text": "Barbarians",
                        "score": 0.99,
                        "confidence_known": True,
                        "frame_id": "frame-1",
                        "image_sha256": "sha-1",
                    }
                ],
            }

    provider._rapidocr_backend = FakeBackend()
    image = tmp_path / "frame.png"
    image.write_bytes(b"not decoded; fake backend does not read it")
    capture = {"frame": {"id": "frame-1", "image_sha256": "sha-1"}}
    original = {
        "schema_version": 1,
        "frame_id": "frame-1",
        "image_sha256": "sha-1",
        "elements": [
            {"text": "SEARCH", "bbox": [500, 590, 66, 13]},
            {"text": "old", "bbox": [350, 732, 105, 24]},
        ],
    }
    overlay = provider._overlay_rapidocr(capture, image, original)
    assert overlay["backend"]["name"] == "Windows.Media.Ocr+RapidOCR.fixed_roi"
    assert overlay["rapidocr_overlay"]["capture_binding_verified"] is True
    assert [item["text"] for item in overlay["elements"]] == ["SEARCH", "Barbarians"]
