import json
from pathlib import Path

import pytest

from harness.mission_runtime import MissionContext
from harness.troop_policy import (
    TROOP_SELECTION_PRECONDITION,
    TroopSelectionApproval,
    TroopSelectionApprovalError,
)


CONTEXT = MissionContext("GATHER_RESOURCE", "one-character", "run-42")


def approval(**overrides):
    raw = {
        "schema_version": 1,
        "approval_id": "approval-1",
        "mission_id": "GATHER_RESOURCE",
        "task_id": "one-character",
        "run_id": "run-42",
        "character_id": "char-a",
        "approved": True,
        "approved_by": "operator",
        "approved_at": "2026-09-15T00:00:00+00:00",
        "source": "operator_artifact",
        "note": "current selection accepted",
    }
    raw.update(overrides)
    return TroopSelectionApproval.from_dict(raw)


def test_positive_approval_is_bound_to_exact_occurrence_and_character():
    item = approval()
    assert item.is_bound_to(CONTEXT, "char-a") is True
    assert item.approvals_for(CONTEXT, "char-a") == {TROOP_SELECTION_PRECONDITION: True}
    summary = item.to_summary(CONTEXT, "char-a")
    assert summary["approval_id"] == "approval-1"
    assert summary["bound_to_occurrence"] is True


@pytest.mark.parametrize(
    "changed,character",
    [
        ({"mission_id": "OTHER"}, "char-a"),
        ({"task_id": "other-task"}, "char-a"),
        ({"run_id": "other-run"}, "char-a"),
        ({}, "char-b"),
        ({"approved": False}, "char-a"),
    ],
)
def test_mismatch_or_negative_approval_fails_closed(changed, character):
    item = approval(**changed)
    assert item.is_bound_to(CONTEXT, character) is False
    assert item.approvals_for(CONTEXT, character) == {}


def test_load_preserves_provenance_and_requires_complete_schema(tmp_path: Path):
    path = tmp_path / "approval.json"
    path.write_text(json.dumps(approval().to_dict()), encoding="utf-8")
    loaded = TroopSelectionApproval.load(path)
    assert loaded.approval_id == "approval-1"
    assert str(path.resolve()) in loaded.source

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"approval_id": "x"}), encoding="utf-8")
    with pytest.raises(TroopSelectionApprovalError):
        TroopSelectionApproval.load(bad)


def test_schema_and_boolean_validation_fail_closed():
    with pytest.raises(TroopSelectionApprovalError):
        approval(schema_version=2)
    with pytest.raises(TroopSelectionApprovalError):
        approval(approved="yes")
    with pytest.raises(TroopSelectionApprovalError):
        approval(approved_at="not-a-time")


def test_explicit_cli_approval_is_still_occurrence_bound():
    item = TroopSelectionApproval.explicit_cli(CONTEXT, "char-a")
    assert item.source == "explicit_cli_flag"
    assert item.is_bound_to(CONTEXT, "char-a") is True
    assert item.is_bound_to(MissionContext("GATHER_RESOURCE", "one-character", "run-43"), "char-a") is False
