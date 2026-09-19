"""Caller-driven, no-input mission tick over the data-driven timeline."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from harness.mission_knowledge import SQLiteMissionKnowledgeStore
from harness.mission_timeline import MissionTimeline, TaskState, TaskSignal, bounded_llm_packet


_FORBIDDEN_FACT_KEY_PARTS = ("bbox", "coord", "rect", "screen", "hwnd", "pid", "path", "image")


class MissionScheduler:
    """Evaluate due work and persist facts; never dispatches game input.

    A future action runner may consume the returned signals through the existing
    occurrence-bound mission engine.  Keeping this tick input-free lets the
    scheduler run while the local LLM is unavailable and makes its output
    replayable from a semantic fact packet.
    """

    def __init__(self, timeline: MissionTimeline, store: SQLiteMissionKnowledgeStore) -> None:
        self.timeline = timeline
        self.store = store

    def tick(self, *, character_id: str, now: datetime,
             facts: Mapping[str, Any], states: Mapping[str, TaskState] | None = None,
             source: str = "direct_ui_observation", frame_id: str | None = None,
             evidence_ref: str | None = None) -> tuple[TaskSignal, ...]:
        current = now.astimezone(timezone.utc)
        self._record_facts(facts, observed_at=current, source=source,
                           frame_id=frame_id, evidence_ref=evidence_ref)
        signals = self.timeline.signals(character_id=character_id, now=current,
                                        states=states, facts=facts)
        for signal in signals:
            self.store.record_occurrence(signal, updated_at=current)
        return signals

    def decision_packets(self, signals: tuple[TaskSignal, ...], facts: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
        packets = []
        for signal in signals:
            if signal.status not in {"NEEDS_DECISION", "UNKNOWN_STATE"}:
                continue
            task = self.timeline.tasks[signal.task_id]
            packets.append(bounded_llm_packet(signal, task, facts))
        return tuple(packets)

    def _record_facts(self, value: Mapping[str, Any], *, prefix: str = "",
                      observed_at: datetime, source: str,
                      frame_id: str | None, evidence_ref: str | None) -> None:
        for key, item in value.items():
            if not isinstance(key, str):
                continue
            if any(part in key.casefold() for part in _FORBIDDEN_FACT_KEY_PARTS):
                continue
            name = f"{prefix}.{key}" if prefix else key
            if isinstance(item, Mapping):
                self._record_facts(item, prefix=name, observed_at=observed_at,
                                   source=source, frame_id=frame_id, evidence_ref=evidence_ref)
            else:
                self.store.record_fact(name, item, observed_at=observed_at, source=source,
                                       frame_id=frame_id, evidence_ref=evidence_ref)


__all__ = ["MissionScheduler"]
