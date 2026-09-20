from pathlib import Path

import numpy as np
import pytest

from harness.cpu_roi import CpuRoiError, CpuRoiProfile


PROFILE = Path(__file__).parents[1] / "config" / "cpu_rois.yaml"


def test_cpu_roi_profile_is_explicitly_cpu_only():
    profile = CpuRoiProfile.load(PROFILE)
    assert profile.processing_backend["device"] == "cpu"
    assert profile.processing_backend["allow_opencl"] is False
    assert profile.processing_backend["allow_cuda"] is False
    assert profile.resolve("signature_canvas", (1366, 768)).rect.as_list() == [109, 61, 1148, 614]


def test_roi_scales_with_same_aspect_ratio_and_returns_copy():
    profile = CpuRoiProfile.load(PROFILE)
    image = np.zeros((384, 683, 3), dtype=np.uint8)
    crop, resolved = profile.crop(image, "signature_canvas")
    assert resolved.source_client_size == (683, 384)
    assert crop.shape[:2] == (resolved.rect.height, resolved.rect.width)
    assert crop.shape[:2] == (308, 574)
    assert not np.shares_memory(crop, image)


def test_roi_rejects_implausible_window_aspect_ratio():
    profile = CpuRoiProfile.load(PROFILE)
    with pytest.raises(CpuRoiError, match="aspect ratio"):
        profile.resolve("signature_canvas", (1280, 800))


def test_roi_description_preserves_processing_boundary():
    profile = CpuRoiProfile.load(PROFILE)
    description = profile.describe("center_canvas", (1366, 768))
    assert description["coordinate_space"] == "client_pixels"
    assert description["processing_device"] == "cpu"
    assert description["opencl_enabled"] is False
    assert description["cuda_enabled"] is False


def test_visual_signature_turns_opencl_off_before_processing(tmp_path):
    import cv2

    from harness.main_view_detector import extract_visual_signature

    image = np.zeros((768, 1366, 3), dtype=np.uint8)
    cv2.rectangle(image, (250, 120), (1050, 560), (80, 160, 210), thickness=-1)
    path = tmp_path / "frame.png"
    assert cv2.imwrite(str(path), image)
    if hasattr(cv2, "ocl"):
        cv2.ocl.setUseOpenCL(True)
    extract_visual_signature(path)
    assert not hasattr(cv2, "ocl") or cv2.ocl.useOpenCL() is False


def test_every_region_carries_a_measured_ocr_scale():
    """A scale nobody measured is a guess with a number on it."""
    profile = CpuRoiProfile.load(PROFILE)
    for roi_id in profile.regions:
        scale = profile.resolve(roi_id, (1366, 768)).ocr_scale
        assert 1.0 <= scale <= 8.0, f"{roi_id} has an out-of-range ocr_scale"


def test_an_out_of_range_ocr_scale_is_refused(tmp_path):
    source = PROFILE.read_text(encoding="utf-8")
    broken = source.replace("ocr_scale: 1.0", "ocr_scale: 99", 1)
    path = tmp_path / "bad.yaml"
    path.write_text(broken, encoding="utf-8")
    with pytest.raises(CpuRoiError, match="ocr_scale"):
        CpuRoiProfile.load(path)


def test_the_header_strip_stops_short_of_the_plus_button():
    """Calibrated 2026-09-20. Including it corrupted the gem counter.

    This is a boundary someone will widen back to the full client width
    because it looks tidier. The measurement said 1340 reads 10/10 exact and
    1366 reads 8/10, at every magnification tried.
    """
    profile = CpuRoiProfile.load(PROFILE)
    rect = profile.resolve("top_resource_bar", (1366, 768)).rect
    assert rect.right == 1340, (
        "the header ROI must stop before the green + button; widening it "
        "silently corrupts the gem counter rather than failing"
    )
    assert rect.height >= 60, (
        "the strip must keep full glyph height; clipping it to 30px dropped "
        "the read to zero elements"
    )
