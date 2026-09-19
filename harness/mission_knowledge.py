"""Small durable SQLite store for mission facts and timeline evidence.

This is intentionally a local, append-friendly knowledge database.  It stores
semantic facts and provenance references, not screenshots, coordinates or
process handles.  A missing/stale fact remains missing; the store never
invents a current value.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from harness.mission_timeline import MissionOccurrence, TaskSignal, TaskState, _aware


class KnowledgeStoreError(ValueError):
    pass


def _json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise KnowledgeStoreError("value is not JSON serializable") from exc


class SQLiteMissionKnowledgeStore:
    """Persist facts, task occurrences, and change signals in one local DB."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self._db = sqlite3.connect(self.path)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._init_schema()

    def _init_schema(self) -> None:
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS facts (
                fact_key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                valid_until TEXT,
                source TEXT NOT NULL,
                frame_id TEXT,
                evidence_ref TEXT
            );
            CREATE TABLE IF NOT EXISTS occurrences (
                occurrence_id TEXT PRIMARY KEY,
                mission_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                reset_epoch TEXT NOT NULL,
                status TEXT NOT NULL,
                next_due_at TEXT,
                reason TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                occurrence_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                FOREIGN KEY (occurrence_id) REFERENCES occurrences(occurrence_id)
            );
            CREATE TABLE IF NOT EXISTS change_signals (
                signal_id INTEGER PRIMARY KEY AUTOINCREMENT,
                surface TEXT NOT NULL,
                status TEXT NOT NULL,
                missing_json TEXT NOT NULL,
                added_json TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                retraining_required INTEGER NOT NULL,
                reason TEXT NOT NULL
            );
            """
        )
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> "SQLiteMissionKnowledgeStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def record_fact(self, fact_key: str, value: Any, *, observed_at: datetime,
                    source: str, valid_until: datetime | None = None,
                    frame_id: str | None = None, evidence_ref: str | None = None) -> None:
        if not fact_key or not source:
            raise KnowledgeStoreError("fact_key and source are required")
        seen = _aware(observed_at, "observed_at").isoformat()
        expires = _aware(valid_until, "valid_until").isoformat() if valid_until is not None else None
        self._db.execute(
            """INSERT INTO facts(fact_key,value_json,observed_at,valid_until,source,frame_id,evidence_ref)
               VALUES(?,?,?,?,?,?,?)
               ON CONFLICT(fact_key) DO UPDATE SET value_json=excluded.value_json,
                 observed_at=excluded.observed_at,valid_until=excluded.valid_until,
                 source=excluded.source,frame_id=excluded.frame_id,evidence_ref=excluded.evidence_ref""",
            (fact_key, _json(value), seen, expires, source, frame_id, evidence_ref),
        )
        self._db.commit()

    def read_fact(self, fact_key: str, *, now: datetime | None = None) -> dict[str, Any] | None:
        row = self._db.execute("SELECT * FROM facts WHERE fact_key=?", (fact_key,)).fetchone()
        if row is None:
            return None
        if now is not None and row["valid_until"] is not None:
            if _aware(now) >= datetime.fromisoformat(row["valid_until"]):
                return None
        return {
            "fact_key": row["fact_key"],
            "value": json.loads(row["value_json"]),
            "observed_at": row["observed_at"],
            "valid_until": row["valid_until"],
            "source": row["source"],
            "frame_id": row["frame_id"],
            "evidence_ref": row["evidence_ref"],
        }

    def record_signal(self, signal: Any, *, observed_at: datetime) -> None:
        required = ("surface", "status", "missing", "added", "retraining_required", "reason")
        if any(not hasattr(signal, name) for name in required):
            raise KnowledgeStoreError("change signal shape is invalid")
        self._db.execute(
            """INSERT INTO change_signals(surface,status,missing_json,added_json,observed_at,retraining_required,reason)
               VALUES(?,?,?,?,?,?,?)""",
            (signal.surface, signal.status, _json(list(signal.missing)), _json(list(signal.added)),
             _aware(observed_at).isoformat(), int(bool(signal.retraining_required)), signal.reason),
        )
        self._db.commit()

    def record_occurrence(self, occurrence: MissionOccurrence | TaskSignal, *, updated_at: datetime) -> None:
        if isinstance(occurrence, TaskSignal):
            mission_id, task_id, character_id = occurrence.mission_id, occurrence.task_id, occurrence.character_id
            occurrence_id, reset, status = occurrence.occurrence_id, occurrence.reset_epoch, occurrence.status
            next_due, reason = occurrence.next_due_at, occurrence.reason
        else:
            mission_id, task_id, character_id = occurrence.mission_id, occurrence.task_id, occurrence.character_id
            occurrence_id, reset, status = occurrence.occurrence_id, occurrence.reset_epoch, occurrence.status
            next_due, reason = None, "occurrence registered"
        self._db.execute(
            """INSERT INTO occurrences(occurrence_id,mission_id,task_id,character_id,reset_epoch,status,next_due_at,reason,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?)
               ON CONFLICT(occurrence_id) DO UPDATE SET status=excluded.status,
                 next_due_at=excluded.next_due_at,reason=excluded.reason,updated_at=excluded.updated_at""",
            (occurrence_id, mission_id, task_id, character_id, _aware(reset).isoformat(), status,
             _iso(next_due), reason, _aware(updated_at).isoformat()),
        )
        self._db.commit()

    def append_event(self, occurrence_id: str, kind: str, payload: Mapping[str, Any], *, at: datetime) -> int:
        if self._db.execute("SELECT 1 FROM occurrences WHERE occurrence_id=?", (occurrence_id,)).fetchone() is None:
            raise KnowledgeStoreError("event references unknown occurrence")
        cursor = self._db.execute(
            "INSERT INTO events(occurrence_id,kind,at,payload_json) VALUES(?,?,?,?)",
            (occurrence_id, kind, _aware(at).isoformat(), _json(dict(payload))),
        )
        self._db.commit()
        return int(cursor.lastrowid)

    def counts(self) -> dict[str, int]:
        return {
            "facts": int(self._db.execute("SELECT COUNT(*) FROM facts").fetchone()[0]),
            "occurrences": int(self._db.execute("SELECT COUNT(*) FROM occurrences").fetchone()[0]),
            "events": int(self._db.execute("SELECT COUNT(*) FROM events").fetchone()[0]),
            "change_signals": int(self._db.execute("SELECT COUNT(*) FROM change_signals").fetchone()[0]),
        }

    def snapshot(self) -> dict[str, Any]:
        return {"schema_version": 1, "counts": self.counts()}


def _iso(value: datetime | None) -> str | None:
    return _aware(value).isoformat() if value is not None else None


__all__ = ["KnowledgeStoreError", "SQLiteMissionKnowledgeStore"]
