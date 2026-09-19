from pathlib import Path

import numpy as np

from harness.cpu_roi import CpuRoiProfile
from harness.rapidocr_fixed_roi import (
    DEFAULT_LABELS,
    normalize_text,
    recognize_crop,
)


PROFILE = Path(__file__).parents[1] / "config" / "cpu_rois.yaml"


def test_resource_label_rois_are_centralized_in_cpu_profile():
    profile = CpuRoiProfile.load(PROFILE)
    assert profile.resolve("resource_category_cropland", (1366, 768)).rect.as_list() == [
        500,
        732,
        105,
        24,
    ]
    assert [spec.label for spec in DEFAULT_LABELS] == [
        "Barbarians",
        "Cropland",
        "Logging Camp",
        "Stone Deposit",
        "Gold Deposit",
    ]


def test_recognizer_only_adapter_parses_one_fixed_roi_without_detection():
    seen_shapes = []

    def fake_engine(image):
        seen_shapes.append(tuple(image.shape[:2]))
        return [["Cropland", 0.989]], [0.01]

    text, score = recognize_crop(fake_engine, np.zeros((24, 105, 3), dtype=np.uint8))
    assert text == "Cropland"
    assert score == 0.989
    assert seen_shapes == [(288, 1260)]
    assert normalize_text("Cropland") == "cropland"
