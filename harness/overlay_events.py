"""Append-only JSONL events for local operator shadow overlays."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from threading import Lock
from typing import Any, Mapping
from uuid import uuid4


class OverlayEventError(ValueError):
    pass


class OverlayEventWriter:
    """Small JSONL writer shared by live ticks and the shadow HUD.

    The event stream is diagnostic only.  It is not an input channel and must
    not be used as action authority.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve()
        self._lock = Lock()

    def emit(self, event_type: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(event_type, str) or not event_type:
            raise OverlayEventError("event_type must be non-empty text")
        if not isinstance(payload, Mapping):
            raise OverlayEventError("payload must be a mapping")
        event = {
            "schema_version": 1,
            "event_id": str(uuid4()),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "payload": _json_safe(payload),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event, ensure_ascii=False, sort_keys=True, default=str)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        return event


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)
