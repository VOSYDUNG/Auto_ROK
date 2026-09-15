"""Occurrence-bound operator approval for the GATHER troop/commander precondition.

This module never infers gameplay policy.  It only turns an explicit operator
approval into the exact compiled precondition evidence for one mission
occurrence and one character.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping

from harness.mission_runtime import MissionContext


TROOP_SELECTION_PRECONDITION = "troop/commander selection policy is valid for this mission"


class TroopSelectionApprovalError(ValueError):
    """Raised when an operator approval artifact is malformed."""


@dataclass(frozen=True)
class TroopSelectionApproval:
    """Explicit operator approval bound to one exact mission occurrence.

    The approval does not describe or choose commanders.  It states only that
    the operator accepts the *currently visible selection* for the exact
    mission/task/run/character tuple.  Any mismatch fails closed and therefore
    leaves the compiled precondition unresolved.
    """

    approval_id: str
    mission_id: str
    task_id: str
    run_id: str
    character_id: str
    approved: bool
    approved_by: str
    approved_at: str
    source: str = "operator_artifact"
    note: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise TroopSelectionApprovalError("unsupported troop approval schema_version")
        for name in (
            "approval_id",
            "mission_id",
            "task_id",
            "run_id",
            "character_id",
            "approved_by",
            "approved_at",
            "source",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise TroopSelectionApprovalError(f"{name} must be a non-empty string")
        if type(self.approved) is not bool:
            raise TroopSelectionApprovalError("approved must be a boolean")
        try:
            datetime.fromisoformat(self.approved_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise TroopSelectionApprovalError("approved_at must be ISO 8601") from exc
        if self.note is not None and not isinstance(self.note, str):
            raise TroopSelectionApprovalError("note must be a string or null")

    def is_bound_to(self, context: MissionContext, character_id: str) -> bool:
        """Return True only for a positive approval bound to this exact occurrence."""
        return (
            self.approved is True
            and self.mission_id == context.mission_id
            and self.task_id == context.task_id
            and self.run_id == context.run_id
            and self.character_id == character_id
        )

    def approvals_for(self, context: MissionContext, character_id: str) -> dict[str, bool]:
        if not self.is_bound_to(context, character_id):
            return {}
        return {TROOP_SELECTION_PRECONDITION: True}

    def to_summary(self, context: MissionContext, character_id: str) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "approved": self.approved,
            "bound_to_occurrence": self.is_bound_to(context, character_id),
            "mission_id": self.mission_id,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "character_id": self.character_id,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "source": self.source,
            "note": self.note,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "approval_id": self.approval_id,
            "mission_id": self.mission_id,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "character_id": self.character_id,
            "approved": self.approved,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "source": self.source,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "TroopSelectionApproval":
        if not isinstance(raw, Mapping):
            raise TroopSelectionApprovalError("approval payload must be an object")
        required = {
            "approval_id",
            "mission_id",
            "task_id",
            "run_id",
            "character_id",
            "approved",
            "approved_by",
            "approved_at",
        }
        missing = sorted(required - set(raw))
        if missing:
            raise TroopSelectionApprovalError(
                "approval payload is missing required fields: " + ", ".join(missing)
            )
        return cls(
            schema_version=int(raw.get("schema_version", 1)),
            approval_id=str(raw["approval_id"]),
            mission_id=str(raw["mission_id"]),
            task_id=str(raw["task_id"]),
            run_id=str(raw["run_id"]),
            character_id=str(raw["character_id"]),
            approved=raw["approved"],
            approved_by=str(raw["approved_by"]),
            approved_at=str(raw["approved_at"]),
            source=str(raw.get("source", "operator_artifact")),
            note=raw.get("note"),
        )

    @classmethod
    def load(cls, path: str | Path) -> "TroopSelectionApproval":
        source = Path(path)
        try:
            raw = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TroopSelectionApprovalError(f"cannot read troop approval {source}: {exc}") from exc
        approval = cls.from_dict(raw)
        if approval.source == "operator_artifact":
            return replace(approval, source=f"operator_artifact:{source.resolve()}")
        return approval

    @classmethod
    def explicit_cli(
        cls,
        context: MissionContext,
        character_id: str,
        *,
        approved_by: str = "operator",
    ) -> "TroopSelectionApproval":
        now = datetime.now(timezone.utc).isoformat()
        return cls(
            approval_id=f"cli-{context.run_id}",
            mission_id=context.mission_id,
            task_id=context.task_id,
            run_id=context.run_id,
            character_id=character_id,
            approved=True,
            approved_by=approved_by,
            approved_at=now,
            source="explicit_cli_flag",
            note="Operator explicitly approved the currently visible troop/commander selection for this occurrence.",
        )
