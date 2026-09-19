from __future__ import annotations

from scripts.evaluate_ocr_quality import _flatten_elements, _label_matches, _levenshtein, _lock_summary


def test_levenshtein_handles_insert_delete_and_substitute() -> None:
    assert _levenshtein(tuple("kitten"), tuple("sitting")) == 3
    assert _levenshtein(("logging", "camp"), ("logging",)) == 1


def test_label_matches_keep_compiled_provenance_and_bound_phrase_rows() -> None:
    flattened = _flatten_elements([
        {"text": "Logging", "bbox": [100, 700, 20, 20], "grounding_authority": "compiled_ui_layout"},
        {"text": "Camp", "bbox": [125, 700, 20, 20], "grounding_authority": "compiled_ui_layout"},
    ])
    matches = _label_matches(flattened, "Logging Camp")
    assert len(matches) == 1
    assert matches[0]["compiled"] is True


def test_label_matches_reject_cross_row_phrase() -> None:
    flattened = _flatten_elements([
        {"text": "Gold", "bbox": [100, 100, 20, 20]},
        {"text": "Deposit", "bbox": [100, 300, 20, 20]},
    ])
    assert _label_matches(flattened, "Gold Deposit") == ()


def test_bounded_ocr_normalization_is_diagnostic_only() -> None:
    flattened = _flatten_elements([
        {"text": "Cold", "bbox": [100, 700, 20, 20]},
        {"text": "cposit", "bbox": [125, 700, 20, 20]},
    ])
    assert _label_matches(flattened, "Gold Deposit") == ()
    normalized = _label_matches(
        flattened,
        "Gold Deposit",
        allow_bounded_ocr_normalization=True,
    )
    assert len(normalized) == 1
    assert normalized[0]["match_mode"] == "bounded_edit_distance_1_or_2"


def test_lock_summary_stays_pending_without_independent_reviewer() -> None:
    manifest = {
        "lock_requirements": {"minimum_reviewers": 2},
        "reviewers": [{"reviewer_id": "operator", "reviewed_at": "2026-09-18", "independent": False}],
    }
    summary = _lock_summary(manifest, [{"review_status": "operator_reviewed"}])
    assert summary["ready"] is False
    assert summary["independent_reviewer_count"] == 0
