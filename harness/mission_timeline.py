"""Data-driven mission timeline for the CPU-only ROK harness.

The timeline is deliberately independent from the Windows action surface.  It
turns current, semantic game facts into due/wait/unknown signals and keeps
local-LLM input bounded to a decision packet.  No wall-clock ``sleep`` and no
desktop coordinate is part of this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from autorok.llm.boundary import is_forbidden_key

try:  # PyYAML is already a runtime dependency of the mission compiler.
    import yaml
except ImportError:  # pragma: no cover - config loading is not used without it
    yaml = None


UTC = timezone.utc
DEFAULT_RESET_ZONE = "UTC"
DEFAULT_DISPLAY_ZONE = "Asia/Ho_Chi_Minh"
TIMELINE_STATUSES = frozenset({
    "DUE", "WAITING", "COMPLETE", "BLOCKED", "UNKNOWN_STATE", "NEEDS_DECISION",
})


class TimelineError(ValueError):
    """Raised when a mission/timeline contract is malformed."""


def _aware(value: datetime, label: str = "time") -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise TimelineError(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


def _zone(value: str) -> ZoneInfo:
    if not isinstance(value, str) or not value:
        raise TimelineError("timezone must be non-empty text")
    try:
        return ZoneInfo(value)
    except Exception as exc:  # ZoneInfoNotFoundError varies by platform.
        raise TimelineError(f"unknown timezone: {value}") from exc


def _iso(value: datetime | None) -> str | None:
    return _aware(value).isoformat() if value is not None else None


def _path(value: Mapping[str, Any], path: str) -> Any:
    current: Any = value
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def reset_boundary(now: datetime, *, reset_timezone: str = DEFAULT_RESET_ZONE,
                   reset_hour: int = 0, reset_minute: int = 0) -> datetime:
    """Return the most recent reset boundary in UTC.

    ROK's configured canonical reset is 00:00 UTC (07:00 Vietnam time).  The
    function accepts a named zone so the rule is explicit and testable rather
    than being hidden in a local-time comparison.
    """
    current = _aware(now).astimezone(_zone(reset_timezone))
    if type(reset_hour) is not int or not 0 <= reset_hour <= 23:
        raise TimelineError("reset_hour must be in 0..23")
    if type(reset_minute) is not int or not 0 <= reset_minute <= 59:
        raise TimelineError("reset_minute must be in 0..59")
    boundary = current.replace(hour=reset_hour, minute=reset_minute, second=0, microsecond=0)
    if current < boundary:
        boundary -= timedelta(days=1)
    return boundary.astimezone(UTC)


def next_reset(now: datetime, *, reset_timezone: str = DEFAULT_RESET_ZONE,
               reset_hour: int = 0, reset_minute: int = 0) -> datetime:
    current = _aware(now)
    boundary = reset_boundary(current, reset_timezone=reset_timezone,
                              reset_hour=reset_hour, reset_minute=reset_minute)
    if boundary <= current:
        boundary += timedelta(days=1)
    return boundary


@dataclass(frozen=True)
class MissionDefinition:
    mission_id: str
    frequency: str
    reset_timezone: str = DEFAULT_RESET_ZONE
    reset_hour: int = 0
    reset_minute: int = 0
    due_offset_seconds: int = 0
    display_timezone: str = DEFAULT_DISPLAY_ZONE
    priority: int = 100

    def __post_init__(self) -> None:
        if not isinstance(self.mission_id, str) or not self.mission_id.strip():
            raise TimelineError("mission_id is required")
        if self.frequency not in {"daily", "interval", "event_window", "continuous"}:
            raise TimelineError(f"unsupported mission frequency: {self.frequency}")
        _zone(self.reset_timezone)
        _zone(self.display_timezone)
        if type(self.due_offset_seconds) is not int or self.due_offset_seconds < 0:
            raise TimelineError("due_offset_seconds must be a non-negative integer")
        if type(self.priority) is not int:
            raise TimelineError("priority must be an integer")
        reset_boundary(datetime.now(UTC), reset_timezone=self.reset_timezone,
                       reset_hour=self.reset_hour, reset_minute=self.reset_minute)


@dataclass(frozen=True)
class TaskDefinition:
    task_id: str
    mission_id: str
    cadence: str
    priority: int = 100
    cooldown_seconds: int | None = None
    max_per_reset: int | None = None
    prerequisite_facts: tuple[str, ...] = ()
    expected_capabilities: tuple[str, ...] = ()
    risk: str = "observe"
    decision_types: tuple[str, ...] = ()
    idempotency: str = "occurrence"
    availability_fact: str | None = None

    def __post_init__(self) -> None:
        if not self.task_id or not self.mission_id:
            raise TimelineError("task_id and mission_id are required")
        if self.cadence not in {"daily", "interval", "event_window", "continuous"}:
            raise TimelineError(f"unsupported task cadence: {self.cadence}")
        if self.cooldown_seconds is not None and (
            type(self.cooldown_seconds) is not int or self.cooldown_seconds <= 0
        ):
            raise TimelineError("cooldown_seconds must be a positive integer")
        if self.max_per_reset is not None and (
            type(self.max_per_reset) is not int or self.max_per_reset <= 0
        ):
            raise TimelineError("max_per_reset must be a positive integer")
        if self.risk not in {"observe", "claim", "spend", "actuate"}:
            raise TimelineError(f"unsupported task risk: {self.risk}")
        if self.idempotency not in {"occurrence", "event", "none"}:
            raise TimelineError(f"unsupported idempotency mode: {self.idempotency}")
        if self.availability_fact is not None and (
            not isinstance(self.availability_fact, str) or not self.availability_fact.strip()
        ):
            raise TimelineError("availability_fact must be non-empty text")


@dataclass(frozen=True)
class TaskState:
    last_success_at: datetime | None = None
    last_attempt_at: datetime | None = None
    completed_count: int = 0
    cooldown_until: datetime | None = None
    status: str = "NEW"

    def __post_init__(self) -> None:
        for label, value in (("last_success_at", self.last_success_at),
                             ("last_attempt_at", self.last_attempt_at),
                             ("cooldown_until", self.cooldown_until)):
            if value is not None:
                _aware(value, label)
        if type(self.completed_count) is not int or self.completed_count < 0:
            raise TimelineError("completed_count must be non-negative")


@dataclass(frozen=True)
class MissionOccurrence:
    mission_id: str
    task_id: str
    character_id: str
    reset_epoch: datetime
    occurrence_id: str
    status: str


@dataclass(frozen=True)
class TaskSignal:
    task_id: str
    mission_id: str
    character_id: str
    occurrence_id: str
    reset_epoch: datetime
    status: str
    next_due_at: datetime | None
    reason: str
    needs_decision: bool = False
    facts_used: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in TIMELINE_STATUSES:
            raise TimelineError(f"invalid task signal status: {self.status}")
        _aware(self.reset_epoch, "reset_epoch")
        if self.next_due_at is not None:
            _aware(self.next_due_at, "next_due_at")


@dataclass(frozen=True)
class ChangeSignal:
    surface: str
    status: str
    missing: tuple[str, ...]
    added: tuple[str, ...]
    expected: tuple[str, ...]
    observed: tuple[str, ...]
    retraining_required: bool
    reason: str


@dataclass(frozen=True)
class FarmPlan:
    now: datetime
    nominal_gather_finish_at: datetime
    effective_gather_finish_at: datetime
    return_at: datetime
    mining_duration_seconds: int
    travel_out_seconds: int
    travel_back_seconds: int
    limiting_factor: str
    queue_gap_seconds: int = 0


def occurrence_id(mission: MissionDefinition, task: TaskDefinition,
                  character_id: str, now: datetime) -> tuple[str, datetime]:
    reset = reset_boundary(now, reset_timezone=mission.reset_timezone,
                           reset_hour=mission.reset_hour, reset_minute=mission.reset_minute)
    if not character_id:
        raise TimelineError("character_id is required for occurrence identity")
    return f"{mission.mission_id}:{task.task_id}:{character_id}:{reset.isoformat()}", reset


def _future_time(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _aware(value)
    if isinstance(value, str):
        try:
            return _aware(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


class MissionTimeline:
    """Derive task signals from definitions, durable task state and facts."""

    def __init__(self, missions: Sequence[MissionDefinition], tasks: Sequence[TaskDefinition]) -> None:
        missions = tuple(missions)
        tasks = tuple(tasks)
        self.missions = {item.mission_id: item for item in missions}
        self.tasks = {item.task_id: item for item in tasks}
        if len(self.missions) != len(missions) or len(self.tasks) != len(tasks):
            raise TimelineError("mission and task identifiers must be unique")
        for task in self.tasks.values():
            if task.mission_id not in self.missions:
                raise TimelineError(f"task {task.task_id} references unknown mission")

    def signal(self, task_id: str, *, character_id: str, now: datetime,
               state: TaskState | None = None, facts: Mapping[str, Any] | None = None) -> TaskSignal:
        if task_id not in self.tasks:
            raise TimelineError(f"unknown task: {task_id}")
        task = self.tasks[task_id]
        mission = self.missions[task.mission_id]
        state = state or TaskState()
        facts = facts or {}
        current = _aware(now)
        ident, reset = occurrence_id(mission, task, character_id, current)
        due_at = reset + timedelta(seconds=mission.due_offset_seconds)

        missing = [path for path in task.prerequisite_facts if _path(facts, path) is None]
        if missing:
            return TaskSignal(task_id, mission.mission_id, character_id, ident, reset,
                              "UNKNOWN_STATE", None,
                              "missing prerequisite facts: " + ", ".join(missing), True,
                              tuple(missing))

        if task.cadence == "daily":
            if state.last_success_at is not None and _aware(state.last_success_at) >= reset:
                return TaskSignal(task_id, mission.mission_id, character_id, ident, reset,
                                  "COMPLETE", next_reset(current, reset_timezone=mission.reset_timezone,
                                                         reset_hour=mission.reset_hour,
                                                         reset_minute=mission.reset_minute),
                                  "daily occurrence already verified")
            if current < due_at:
                return TaskSignal(task_id, mission.mission_id, character_id, ident, reset,
                                  "WAITING", due_at, "daily reset window has not opened")
            unavailable = self._daily_unavailable(task, facts)
            if unavailable:
                return TaskSignal(task_id, mission.mission_id, character_id, ident, reset,
                                  "COMPLETE", next_reset(current, reset_timezone=mission.reset_timezone,
                                                         reset_hour=mission.reset_hour,
                                                         reset_minute=mission.reset_minute), unavailable)
            return TaskSignal(task_id, mission.mission_id, character_id, ident, reset,
                              "DUE", due_at, "daily task is due")

        if task.cadence == "interval":
            if task.availability_fact is not None:
                availability = _path(facts, task.availability_fact)
                if availability in (None, "unknown", "UNKNOWN_STATE", "ambiguous"):
                    return TaskSignal(task_id, mission.mission_id, character_id, ident, reset,
                                      "UNKNOWN_STATE", None,
                                      f"availability fact is not verified: {task.availability_fact}", True,
                                      (task.availability_fact,))
                if availability == "capped":
                    return TaskSignal(task_id, mission.mission_id, character_id, ident, reset,
                                      "COMPLETE", next_reset(current, reset_timezone=mission.reset_timezone,
                                                             reset_hour=mission.reset_hour,
                                                             reset_minute=mission.reset_minute),
                                      "observed contribution cap reached")
                if availability == "cooldown":
                    observed_due = _future_time(_path(facts, "alliance.cooldown_until"))
                    if observed_due is None:
                        return TaskSignal(task_id, mission.mission_id, character_id, ident, reset,
                                          "UNKNOWN_STATE", None,
                                          "cooldown status has no verified expiry", True,
                                          ("alliance.cooldown_until",))
                    if current < observed_due:
                        return TaskSignal(task_id, mission.mission_id, character_id, ident, reset,
                                          "WAITING", observed_due, "observed alliance contribution cooldown")
                elif availability != "ready":
                    return TaskSignal(task_id, mission.mission_id, character_id, ident, reset,
                                      "UNKNOWN_STATE", None,
                                      f"unsupported availability state: {availability}", True,
                                      (task.availability_fact,))
            if task.max_per_reset is not None and state.completed_count >= task.max_per_reset:
                return TaskSignal(task_id, mission.mission_id, character_id, ident, reset,
                                  "COMPLETE", next_reset(current, reset_timezone=mission.reset_timezone,
                                                         reset_hour=mission.reset_hour,
                                                         reset_minute=mission.reset_minute),
                                  "per-reset contribution limit reached")
            next_due = state.cooldown_until or (
                _aware(state.last_success_at) + timedelta(seconds=task.cooldown_seconds)
                if state.last_success_at is not None and task.cooldown_seconds is not None else current
            )
            if current < next_due:
                return TaskSignal(task_id, mission.mission_id, character_id, ident, reset,
                                  "WAITING", next_due, "interval cooldown is active")
            return TaskSignal(task_id, mission.mission_id, character_id, ident, reset,
                              "DUE", next_due, "interval task is due")

        if task.cadence == "event_window":
            availability = self._event_availability(task, facts, current)
            if availability[0] == "UNKNOWN_STATE":
                return TaskSignal(task_id, mission.mission_id, character_id, ident, reset,
                                  "UNKNOWN_STATE", availability[1], availability[2], True,
                                  ("event_window",))
            if availability[0] == "WAITING":
                return TaskSignal(task_id, mission.mission_id, character_id, ident, reset,
                                  "WAITING", availability[1], availability[2])
            if availability[0] == "NEEDS_DECISION":
                return TaskSignal(task_id, mission.mission_id, character_id, ident, reset,
                                  "NEEDS_DECISION", availability[1], availability[2], True,
                                  ("event_window",))
            return TaskSignal(task_id, mission.mission_id, character_id, ident, reset,
                              "DUE", availability[1], availability[2])

        # Continuous farm scheduling is driven by queue facts, not by a sleep.
        farm = facts.get("farm")
        if not isinstance(farm, Mapping):
            return TaskSignal(task_id, mission.mission_id, character_id, ident, reset,
                              "UNKNOWN_STATE", None, "farm facts are unavailable", True, ("farm",))
        used = farm.get("queue_used")
        capacity = farm.get("queue_capacity")
        if type(used) is not int or type(capacity) is not int or used < 0 or capacity <= 0 or used > capacity:
            return TaskSignal(task_id, mission.mission_id, character_id, ident, reset,
                              "UNKNOWN_STATE", None, "farm queue facts are invalid", True, ("farm.queue",))
        if used < capacity:
            return TaskSignal(task_id, mission.mission_id, character_id, ident, reset,
                              "DUE", current, "a march slot is available")
        returns = [_future_time(item.get("return_at")) for item in farm.get("marches", [])
                   if isinstance(item, Mapping)]
        returns = [item for item in returns if item is not None and item >= current]
        if not returns:
            return TaskSignal(task_id, mission.mission_id, character_id, ident, reset,
                              "UNKNOWN_STATE", None, "full farm queue has no verified return time", True,
                              ("farm.marches.return_at",))
        earliest = min(returns)
        return TaskSignal(task_id, mission.mission_id, character_id, ident, reset,
                          "WAITING", earliest, "all march slots occupied; next slot is return-driven")

    @staticmethod
    def _daily_unavailable(task: TaskDefinition, facts: Mapping[str, Any]) -> str | None:
        # A false availability fact is an observed no-op, not permission to guess.
        for path in task.prerequisite_facts:
            value = _path(facts, path)
            if value is False:
                return f"observed unavailable: {path}"
        return None

    @staticmethod
    def _event_availability(task: TaskDefinition, facts: Mapping[str, Any],
                            now: datetime) -> tuple[str, datetime | None, str]:
        # Courier Station facts are intentionally semantic.  Currency, price and
        # purchase policy stay outside the scheduler and require a bounded LLM
        # decision or operator approval.
        surface = facts.get("courier_station")
        if not isinstance(surface, Mapping):
            return "UNKNOWN_STATE", None, "courier station facts are unavailable"
        expires = _future_time(surface.get("window_expires_at"))
        refresh = _future_time(surface.get("next_refresh_at"))
        if expires is not None and expires <= now:
            return "WAITING", refresh, "courier station event window expired"
        if surface.get("free_claim_available") is True:
            return "DUE", now, "free courier claim is available"
        if surface.get("free_claim_available") is False and surface.get("items_available") is True:
            if task.risk == "spend":
                return "NEEDS_DECISION", expires, "paid station items require policy/LLM decision"
            return "DUE", now, "station has items to inspect; purchase remains separately gated"
        if surface.get("items_available") is False:
            return "WAITING", refresh, "courier station has no observed available item"
        return "UNKNOWN_STATE", refresh, "courier station availability is ambiguous"

    def signals(self, *, character_id: str, now: datetime,
                states: Mapping[str, TaskState] | None = None,
                facts: Mapping[str, Any] | None = None) -> tuple[TaskSignal, ...]:
        states = states or {}
        facts = facts or {}
        result = [self.signal(task_id, character_id=character_id, now=now,
                              state=states.get(task_id), facts=facts)
                  for task_id in self.tasks]
        return tuple(sorted(result, key=lambda item: (
            0 if item.status == "DUE" else 1 if item.status == "NEEDS_DECISION" else 2,
            self.tasks[item.task_id].priority,
            item.task_id,
        )))


def detect_capability_change(expected: Mapping[str, Sequence[str]],
                             observed: Mapping[str, Sequence[str]]) -> tuple[ChangeSignal, ...]:
    """Compare trained semantic labels with a current observation.

    Missing/renamed UI capabilities become ``UNKNOWN_STATE`` and a retraining
    signal.  The detector never maps a new label to an old action implicitly.
    """
    result: list[ChangeSignal] = []
    for surface, expected_values in expected.items():
        exp = tuple(str(item) for item in expected_values)
        raw = observed.get(surface)
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            result.append(ChangeSignal(surface, "UNKNOWN_STATE", exp, (), exp, (), True,
                                       "observed capability surface is missing"))
            continue
        obs = tuple(str(item) for item in raw)
        missing = tuple(item for item in exp if item not in obs)
        added = tuple(item for item in obs if item not in exp)
        changed = bool(missing or added)
        result.append(ChangeSignal(
            surface,
            "NEEDS_DECISION" if changed else "COMPLETE",
            missing,
            added,
            exp,
            obs,
            changed,
            "trained capability changed; collect a new observation and retrain" if changed
            else "trained capability matches current observation",
        ))
    for surface in observed.keys() - expected.keys():
        raw = observed[surface]
        obs = tuple(str(item) for item in raw) if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)) else ()
        result.append(ChangeSignal(surface, "NEEDS_DECISION", (), obs, (), obs, True,
                                   "new capability surface is not in the trained graph"))
    return tuple(result)


def compute_farm_plan(now: datetime, *, nominal_gather_seconds: int,
                      travel_out_seconds: int = 0, travel_back_seconds: int = 0,
                      node_depletion_at: datetime | None = None,
                      buff_expires_at: datetime | None = None,
                      task_deadline_at: datetime | None = None,
                      next_dispatch_at: datetime | None = None) -> FarmPlan:
    """Compute a resource cycle with mining time separate from travel time."""
    current = _aware(now)
    if type(nominal_gather_seconds) is not int or nominal_gather_seconds < 0:
        raise TimelineError("nominal_gather_seconds must be non-negative")
    for label, value in (("travel_out_seconds", travel_out_seconds), ("travel_back_seconds", travel_back_seconds)):
        if type(value) is not int or value < 0:
            raise TimelineError(f"{label} must be non-negative")
    nominal_finish = current + timedelta(seconds=nominal_gather_seconds)
    limits: list[tuple[str, datetime]] = [("nominal_gather", nominal_finish)]
    for label, value in (("node_depletion", node_depletion_at),
                         ("buff_expiry", buff_expires_at),
                         ("task_deadline", task_deadline_at)):
        if value is not None:
            limits.append((label, _aware(value, label)))
    limiting_factor, effective_finish = min(limits, key=lambda item: item[1])
    if effective_finish < current:
        effective_finish = current
    return_at = effective_finish + timedelta(seconds=travel_back_seconds)
    planned = _aware(next_dispatch_at, "next_dispatch_at") if next_dispatch_at is not None else return_at
    gap = max(0, int((planned - return_at).total_seconds()))
    return FarmPlan(
        now=current,
        nominal_gather_finish_at=nominal_finish,
        effective_gather_finish_at=effective_finish,
        return_at=return_at,
        mining_duration_seconds=max(0, int((effective_finish - current).total_seconds())),
        travel_out_seconds=travel_out_seconds,
        travel_back_seconds=travel_back_seconds,
        limiting_factor=limiting_factor,
        queue_gap_seconds=gap,
    )


def bounded_llm_packet(signal: TaskSignal, task: TaskDefinition,
                       facts: Mapping[str, Any]) -> dict[str, Any]:
    """Build the graph/state packet exposed to the local decision worker."""
    visible: dict[str, Any] = {}
    for key in ("daily_reset_epoch", "vip", "courier_station", "farm", "alliance", "change_signals"):
        value = facts.get(key)
        if value is not None:
            visible[key] = _semantic_copy(value)
    return {
        "mission_id": signal.mission_id,
        "task_id": signal.task_id,
        "character_id": signal.character_id,
        "occurrence_id": signal.occurrence_id,
        "reset_epoch": _iso(signal.reset_epoch),
        "status": signal.status,
        "next_due_at": _iso(signal.next_due_at),
        "reason": signal.reason,
        "facts": visible,
        "allowed_decision_types": list(task.decision_types),
        "risk": task.risk,
        "harness_authority": ["schedule", "grounding", "policy", "actuation", "verification"],
        "model_authority": ["bounded_choice", "abstain", "change_feedback"],
    }


def _semantic_copy(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {
            str(key): _semantic_copy(item)
            for key, item in value.items()
            if isinstance(key, str) and not is_forbidden_key(key)
        }
    if isinstance(value, (list, tuple)):
        return [_semantic_copy(item) for item in value]
    return None


def load_timeline_config(path: str | Path) -> MissionTimeline:
    if yaml is None:
        raise TimelineError("PyYAML is required to load mission layer config")
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping) or payload.get("schema_version") != 1:
        raise TimelineError("mission layer schema_version must be 1")
    missions = tuple(MissionDefinition(**dict(item)) for item in payload.get("missions", []))
    tasks = []
    for raw in payload.get("tasks", []):
        item = dict(raw)
        for field_name in ("prerequisite_facts", "expected_capabilities", "decision_types"):
            item[field_name] = tuple(item.get(field_name, ()))
        tasks.append(TaskDefinition(**item))
    return MissionTimeline(missions, tuple(tasks))


__all__ = [
    "ChangeSignal", "FarmPlan", "MissionDefinition", "MissionOccurrence", "MissionTimeline",
    "TaskDefinition", "TaskSignal", "TaskState", "TimelineError", "bounded_llm_packet",
    "compute_farm_plan", "detect_capability_change", "load_timeline_config", "next_reset",
    "occurrence_id", "reset_boundary",
]
