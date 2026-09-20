"""The single boundary between harness facts and anything sent to a model.

There were two of these lists and they had already drifted.
``harness/local_llm_selector.py`` blocked eleven key fragments;
``harness/mission_scheduler.py`` blocked eight, missing ``memory``, ``point``
and ``window``. Nothing connected them, so the strategic tier would have
leaked exactly the three the tactical tier was written to stop.

That is the failure mode this module exists to remove: a safety rule that
lives in two places is a safety rule that is already wrong in one of them.

The forbidden fragments here are a substring denylist, and that is deliberate.
It is the last line, not the first. The first line is the per-slice allowlist
in the selector, which names the handful of facts a model may see. The denylist
catches anything that slips past an allowlist someone widened without thinking.

Two rules for changing this file:

  * Only ever add. Removing a fragment widens what a model can see, and that
    is a decision for docs/PROJECT_DECLARATION.md, not for a refactor.
  * Never import it into anything that talks to the game. This is about what
    leaves the harness toward a model, not about what the harness may know.
"""
from __future__ import annotations

from typing import Any, Mapping

#: Substrings that disqualify a fact key from ever reaching a model.
#:
#: Geometry and handles are the point of the list: a bounded chooser has no use
#: for a coordinate, and giving it one turns a constrained selection into an
#: unconstrained desktop-control surface. ``memory``, ``path`` and ``image``
#: cover the other direction - a model must not be handed the host's internals
#: or a route to raw frames.
FORBIDDEN_KEY_PARTS: tuple[str, ...] = (
    "bbox",
    "coord",
    "hwnd",
    "image",
    "memory",
    "path",
    "pid",
    "point",
    "rect",
    "screen",
    "window",
)


def is_forbidden_key(key: str) -> bool:
    """True when a fact key must never be sent to a model.

    Case-folded, so ``BBox`` and ``Screen_Rect`` are caught the same as their
    lowercase spellings.
    """
    folded = str(key).casefold()
    return any(part in folded for part in FORBIDDEN_KEY_PARTS)


def forbidden_parts_in(key: str) -> tuple[str, ...]:
    """Which fragments matched, for a message that says why something was cut."""
    folded = str(key).casefold()
    return tuple(part for part in FORBIDDEN_KEY_PARTS if part in folded)


def strip_forbidden(
    facts: Mapping[str, Any], *, prefix: str = ""
) -> dict[str, Any]:
    """Drop every forbidden key, at any depth.

    Nested mappings are walked, because a forbidden key is just as forbidden
    one level down - and the qualified name is what gets tested, so a nested
    ``target.screen_rect`` is caught by its own segment rather than by luck.

    Sequences are walked too. That was missing, and it was a live hole: the
    strategic packet carries ``due_tasks`` as a LIST of mappings, so a
    ``client_window_rect`` inside one of them passed straight through a
    function whose whole job is to stop exactly that. Found by
    ``test_llm_strategy`` before the strategic tier ever ran.
    """
    kept: dict[str, Any] = {}
    for key, value in facts.items():
        if not isinstance(key, str):
            continue
        qualified = f"{prefix}.{key}" if prefix else key
        if is_forbidden_key(key) or is_forbidden_key(qualified):
            continue
        kept[key] = _strip_value(value, prefix=qualified)
    return kept


def _strip_value(value: Any, *, prefix: str) -> Any:
    if isinstance(value, Mapping):
        return strip_forbidden(value, prefix=prefix)
    if isinstance(value, (list, tuple)):
        return [_strip_value(item, prefix=prefix) for item in value]
    return value


__all__ = [
    "FORBIDDEN_KEY_PARTS",
    "forbidden_parts_in",
    "is_forbidden_key",
    "strip_forbidden",
]
