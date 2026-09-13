from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from harness.contracts import BoundingBox


@dataclass(frozen=True)
class VisualTarget:
    """A semantic UI target grounded in one captured frame.

    Coordinates are execution data, not game knowledge. A target must be
    re-grounded after a UI transition or whenever its frame is no longer valid.
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


@dataclass(frozen=True)
class SceneGraph:
    frame_id: str
    state_hint: str | None
    targets: Sequence[VisualTarget] = field(default_factory=tuple)
    facts: Mapping[str, Any] = field(default_factory=dict)

    def target(self, target_id: str, min_confidence: float = 0.0) -> VisualTarget | None:
        matches = [
            target
            for target in self.targets
            if target.target_id == target_id and target.confidence >= min_confidence
        ]
        if not matches:
            return None
        return max(matches, key=lambda item: item.confidence)

    def require_target(
        self, target_id: str, min_confidence: float = 0.90
    ) -> VisualTarget:
        target = self.target(target_id, min_confidence=min_confidence)
        if target is None:
            raise LookupError(
                f"target {target_id!r} is not grounded with confidence "
                f">= {min_confidence:.2f} in frame {self.frame_id!r}"
            )
        return target

    def is_current(self, target: VisualTarget) -> bool:
        return target.frame_id == self.frame_id
