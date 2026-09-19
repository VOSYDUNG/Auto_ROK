"""Deterministic OCR phrase assembly and explicit exact-target grounding."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, Sequence

from harness.contracts import BoundingBox, Evidence, Observation
from harness.mission_runtime import MissionContext
from harness.mission_tool import ObservationBundle, ObservationProvider
from harness.scene_graph import SceneGraph, VisualTarget


@dataclass(frozen=True)
class OcrTargetSpec:
    """Target labels allowed to ground from OCR.

    ``allow_unscored_exact`` is intentionally explicit because Windows.Media.Ocr
    exposes word boxes but not per-word confidence. Enabling it does not invent
    confidence; resulting targets remain confidence=0.0 and carry an explicit
    authorization marker consumed by ``SemanticActionSurface``.
    """

    target_id: str
    labels: tuple[str, ...]
    min_confidence: float = 0.90
    allow_unscored_exact: bool = False

    def __post_init__(self) -> None:
        if not self.target_id:
            raise ValueError("target_id is required")
        if not self.labels or any(not isinstance(label, str) or not label.strip() for label in self.labels):
            raise ValueError(f"target {self.target_id!r} requires non-empty labels")
        if not 0.0 <= self.min_confidence <= 1.0:
            raise ValueError("min_confidence must be within [0, 1]")


@dataclass(frozen=True)
class _Token:
    text: str
    bbox: BoundingBox
    confidence: float
    confidence_known: bool
    index: int


class OcrSemanticObservationProvider:
    """Enrich word OCR with frame-bound phrases and bounded target handles."""

    def __init__(
        self,
        inner: ObservationProvider,
        specs: Sequence[OcrTargetSpec] = (),
        *,
        max_phrase_words: int = 8,
    ) -> None:
        if not 2 <= max_phrase_words <= 12:
            raise ValueError("max_phrase_words must be between 2 and 12")
        ids = [spec.target_id for spec in specs]
        if len(ids) != len(set(ids)):
            raise ValueError("OCR target ids must be unique")
        self.inner = inner
        self.specs = tuple(specs)
        self.max_phrase_words = max_phrase_words

    def observe(self, context: MissionContext) -> ObservationBundle:
        bundle = self.inner.observe(context)
        if bundle.observation.frame_id != bundle.scene.frame_id:
            raise ValueError("observation and scene must share one frame")

        phrases = self._phrases(bundle.observation)
        evidence = tuple(bundle.observation.evidence) + phrases
        enriched_observation = replace(bundle.observation, evidence=evidence)

        targets = list(bundle.scene.targets)
        decisions: list[Mapping[str, Any]] = []
        for spec in self.specs:
            if any(target.target_id == spec.target_id for target in targets):
                decisions.append({
                    "target_id": spec.target_id,
                    "status": "PRESERVED_EXISTING",
                    "reason": "target_already_grounded",
                })
                continue
            matches = self._matches(evidence, spec)
            if len(matches) != 1:
                decisions.append({
                    "target_id": spec.target_id,
                    "status": "NEEDS_DECISION",
                    "reason": "candidate_missing" if not matches else "candidate_ambiguous",
                    "match_count": len(matches),
                })
                continue
            item = matches[0]
            confidence_known = item.metadata.get("confidence_known") is True
            phrase = item.source == "ocr_phrase"
            grounding_mode = (
                "scored_phrase" if phrase and confidence_known
                else "scored_exact" if confidence_known
                else "unique_phrase_unscored" if phrase
                else "unique_exact_unscored"
            )
            metadata = dict(item.metadata)
            metadata.update({
                "grounding_mode": grounding_mode,
                "unscored_exact_authorized": bool(not confidence_known and spec.allow_unscored_exact),
                "candidate_labels": tuple(spec.labels),
            })
            targets.append(VisualTarget(
                spec.target_id,
                bundle.scene.frame_id,
                str(item.value if isinstance(item.value, str) else item.label),
                item.bbox,
                item.confidence if confidence_known else 0.0,
                item.source,
                metadata,
            ))
            decisions.append({
                "target_id": spec.target_id,
                "status": "GROUNDED",
                "grounding_mode": grounding_mode,
                "confidence_known": confidence_known,
            })

        facts = dict(bundle.scene.facts)
        if phrases:
            facts["ocr_phrase_count"] = len(phrases)
        if decisions:
            facts["ocr_grounding_decisions"] = tuple(decisions)
        scene = replace(bundle.scene, targets=tuple(targets), facts=facts)
        return ObservationBundle(enriched_observation, scene)

    def _matches(self, evidence: Sequence[Evidence], spec: OcrTargetSpec) -> tuple[Evidence, ...]:
        labels = {self._normalize(label) for label in spec.labels}
        matches: list[Evidence] = []
        for item in evidence:
            if item.source not in {"ocr", "ocr_phrase"} or item.bbox is None:
                continue
            value = item.value if isinstance(item.value, str) else item.label
            if self._normalize(value) not in labels:
                continue
            known = item.metadata.get("confidence_known") is True
            if known and item.confidence >= spec.min_confidence:
                matches.append(item)
            elif not known and spec.allow_unscored_exact:
                matches.append(item)
        # Same OCR words can produce duplicate labels only if there are multiple
        # boxes. Keep each box distinct so duplicate buttons fail closed.
        unique: list[Evidence] = []
        seen: set[tuple[str, int, int, int, int]] = set()
        for item in matches:
            key = (
                self._normalize(item.value if isinstance(item.value, str) else item.label),
                item.bbox.x1,
                item.bbox.y1,
                item.bbox.x2,
                item.bbox.y2,
            )
            if key not in seen:
                seen.add(key)
                unique.append(item)
        return tuple(unique)

    def _phrases(self, observation: Observation) -> tuple[Evidence, ...]:
        tokens = self._tokens(observation)
        if len(tokens) < 2:
            return ()
        lines = self._group_lines(tokens)
        phrases: list[Evidence] = []
        for line_id, line in enumerate(lines):
            ordered = sorted(line, key=lambda item: (item.bbox.x1, item.index))
            for start in range(len(ordered)):
                upper = min(len(ordered), start + self.max_phrase_words)
                for end in range(start + 2, upper + 1):
                    chunk = ordered[start:end]
                    text = " ".join(item.text.strip() for item in chunk if item.text.strip())
                    if not text:
                        continue
                    bbox = BoundingBox(
                        min(item.bbox.x1 for item in chunk),
                        min(item.bbox.y1 for item in chunk),
                        max(item.bbox.x2 for item in chunk),
                        max(item.bbox.y2 for item in chunk),
                    )
                    known = all(item.confidence_known for item in chunk)
                    confidence = min(item.confidence for item in chunk) if known else 0.0
                    phrases.append(Evidence(
                        "ocr_phrase",
                        text,
                        confidence,
                        bbox,
                        text,
                        {
                            "frame_id": observation.frame_id,
                            "confidence_known": known,
                            "phrase_line": line_id,
                            "source_element_indices": tuple(item.index for item in chunk),
                            "grounding_mode": "scored_phrase" if known else "unscored_phrase",
                        },
                    ))
        return tuple(phrases)

    @staticmethod
    def _tokens(observation: Observation) -> tuple[_Token, ...]:
        tokens: list[_Token] = []
        for fallback_index, item in enumerate(observation.evidence):
            if item.source != "ocr" or item.bbox is None:
                continue
            if item.metadata.get("semantic_excluded") is True:
                continue
            value = item.value if isinstance(item.value, str) else item.label
            if not isinstance(value, str) or not value.strip():
                continue
            index = item.metadata.get("ocr_element_index")
            if type(index) is not int:
                index = fallback_index
            tokens.append(_Token(
                value.strip(),
                item.bbox,
                item.confidence,
                item.metadata.get("confidence_known") is True,
                index,
            ))
        return tuple(tokens)

    @staticmethod
    def _group_lines(tokens: Sequence[_Token]) -> tuple[tuple[_Token, ...], ...]:
        """Group tokens by vertical overlap; no hidden OCR line metadata required."""
        lines: list[list[_Token]] = []
        for token in sorted(tokens, key=lambda item: (item.bbox.y1, item.bbox.x1)):
            best: list[_Token] | None = None
            best_overlap = 0.0
            for line in lines:
                top = min(item.bbox.y1 for item in line)
                bottom = max(item.bbox.y2 for item in line)
                overlap = max(0, min(bottom, token.bbox.y2) - max(top, token.bbox.y1))
                denom = max(1, min(bottom - top, token.bbox.y2 - token.bbox.y1))
                ratio = overlap / denom
                if ratio > best_overlap:
                    best_overlap = ratio
                    best = line
            if best is not None and best_overlap >= 0.5:
                best.append(token)
            else:
                lines.append([token])
        return tuple(tuple(line) for line in lines)

    @staticmethod
    def _normalize(value: str) -> str:
        return " ".join(value.strip().casefold().split())
