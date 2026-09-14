from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from harness.contracts import BoundingBox


@dataclass(frozen=True)
class VisualTarget:
    """A semantic UI target grounded in one captured frame.

    Coordinates are execution data, not game knowledge. A target must be
    re-grounded after a UI transition or whenever its frame is no longer valid.
    ``confidence`` is never fabricated: unscored exact OCR targets remain 0.0
    and are usable only through the explicit unscored-exact authorization path.
    """

    target_id: str
    frame_id: str
    label: str
    bbox: BoundingBox
    confidence: float
    source: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def click_point(self) -> tuple[int, int]:
        return self.bbox.center

    @property
    def is_authorized_unscored_exact(self) -> bool:
        return (
            self.metadata.get("confidence_known") is False
            and self.metadata.get("unscored_exact_authorized") is True
            and self.metadata.get("grounding_mode") in {
                "unique_exact_unscored",
                "unique_phrase_unscored",
            }
        )


@dataclass(frozen=True)
class SceneGraph:
    frame_id: str
    state_hint: str | None
    targets: Sequence[VisualTarget] = field(default_factory=tuple)
    facts: Mapping[str, Any] = field(default_factory=dict)

    def target(
        self,
        target_id: str,
        min_confidence: float = 0.0,
        *,
        allow_unscored_exact: bool = False,
    ) -> VisualTarget | None:
        matches = [
            target
            for target in self.targets
            if target.target_id == target_id
            and (
                target.confidence >= min_confidence
                or allow_unscored_exact and target.is_authorized_unscored_exact
            )
        ]
        if not matches:
            return None
        return max(
            matches,
            key=lambda item: (
                item.confidence >= min_confidence,
                item.confidence,
                item.is_authorized_unscored_exact,
            ),
        )

    def require_target(
        self,
        target_id: str,
        min_confidence: float = 0.90,
        *,
        allow_unscored_exact: bool = False,
    ) -> VisualTarget:
        target = self.target(
            target_id,
            min_confidence=min_confidence,
            allow_unscored_exact=allow_unscored_exact,
        )
        if target is None:
            suffix = " or an explicitly authorized unique unscored exact match" if allow_unscored_exact else ""
            raise LookupError(
                f"target {target_id!r} is not grounded with confidence "
                f">= {min_confidence:.2f}{suffix} in frame {self.frame_id!r}"
            )
        return target

    def is_current(self, target: VisualTarget) -> bool:
        return target.frame_id == self.frame_id
