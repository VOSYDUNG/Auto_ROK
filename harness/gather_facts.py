"""Visible-evidence fact enrichment for the one-character GATHER_RESOURCE slice."""
from __future__ import annotations

from dataclasses import replace
import re
from typing import Iterable

from harness.mission_runtime import MissionContext
from harness.mission_tool import ObservationBundle, ObservationProvider


_QUEUE = re.compile(r"\bqueue\s*(\d{1,2})\s*/\s*(\d{1,2})\b", re.IGNORECASE)
_QUEUE_RATIO = re.compile(r"(?<!\d)(\d{1,2})\s*/\s*(\d{1,2})(?!\d)")
_LEVEL = re.compile(r"\b(?:level|lvl|lv\.?)\s*[:\-]?\s*(\d{1,2})\b", re.IGNORECASE)
_QUEUE_ROI_ACQUISITIONS = frozenset({"ocr_march_queue_region"})


def _texts(bundle: ObservationBundle) -> Iterable[str]:
    for item in bundle.observation.evidence:
        if isinstance(item.value, str) and item.value.strip():
            yield item.value
        if isinstance(item.label, str) and item.label.strip():
            yield item.label
    raw = bundle.scene.facts.get("raw_text")
    if isinstance(raw, str) and raw.strip():
        yield raw


def extract_march_queue(bundle: ObservationBundle) -> tuple[int, int] | None:
    """Return one unambiguous visible ``used/capacity`` pair, else fail closed."""
    pairs: set[tuple[int, int]] = set()
    for evidence in bundle.observation.evidence:
        text = evidence.value if isinstance(evidence.value, str) else evidence.label
        if not isinstance(text, str):
            continue
        explicit = _QUEUE.findall(text)
        ratios = explicit
        if not explicit and evidence.metadata.get("acquisition") in _QUEUE_ROI_ACQUISITIONS:
            ratios = _QUEUE_RATIO.findall(text)
            if not ratios:
                # Windows.Media.Ocr can render the thin slash in the fixed
                # queue glyph as a middle ``1`` (for example ``1/5`` ->
                # ``115``).  This normalization is permitted only for the
                # dedicated queue ROI and only for the exact three-digit
                # shape; it never applies to full-frame OCR or date-like text.
                compact = re.fullmatch(r"([0-9])1([0-9])", text.strip())
                if compact:
                    ratios = [(compact.group(1), compact.group(2))]
        for used_raw, capacity_raw in ratios:
            used, capacity = int(used_raw), int(capacity_raw)
            if 0 <= used <= capacity <= 20:
                pairs.add((used, capacity))
    if len(pairs) != 1:
        return None
    return next(iter(pairs))


def march_queue_source(bundle: ObservationBundle) -> str | None:
    """Return provenance for the unique queue fact, never for a bare ratio."""
    pair = extract_march_queue(bundle)
    if pair is None:
        return None
    for evidence in bundle.observation.evidence:
        text = evidence.value if isinstance(evidence.value, str) else evidence.label
        if not isinstance(text, str):
            continue
        if evidence.metadata.get("acquisition") not in _QUEUE_ROI_ACQUISITIONS:
            continue
        ratios = _QUEUE_RATIO.findall(text)
        if not ratios:
            compact = re.fullmatch(r"([0-9])1([0-9])", text.strip())
            if compact:
                ratios = [(compact.group(1), compact.group(2))]
        for used_raw, capacity_raw in ratios:
            if (int(used_raw), int(capacity_raw)) == pair:
                return "visible_ocr_march_queue_region"
    return "visible_ocr_queue_anchor"


def extract_visible_resource_level(bundle: ObservationBundle) -> int | None:
    """Return one unambiguous visible ``Level N`` value, else fail closed.

    This fact is evidence only.  It does not prove which widget produced the
    text until the state classifier independently proves RESOURCE_SEARCH_PANEL.
    """
    levels: set[int] = set()
    for text in _texts(bundle):
        for raw in _LEVEL.findall(text):
            value = int(raw)
            if 1 <= value <= 30:
                levels.add(value)
    if len(levels) != 1:
        return None
    return next(iter(levels))


class GatherFactObservationProvider:
    """Wrap an observation provider with deterministic facts needed by completion.

    ``character_id`` is an operator-scoped invariant for the initial
    single-character slice; it is not inferred from pixels. The source is
    explicitly recorded so a later multi-character runtime cannot mistake it
    for OCR evidence.
    """

    def __init__(self, inner: ObservationProvider, *, character_id: str) -> None:
        if not isinstance(character_id, str) or not character_id.strip():
            raise ValueError("character_id is required for the one-character gather slice")
        self.inner = inner
        self.character_id = character_id.strip()

    def observe(self, context: MissionContext) -> ObservationBundle:
        bundle = self.inner.observe(context)
        if bundle.observation.frame_id != bundle.scene.frame_id:
            raise ValueError("observation and scene must share one frame")
        facts = dict(bundle.scene.facts)
        facts["character_id"] = self.character_id
        facts["character_id_source"] = "configured_single_character_scope"
        queue = extract_march_queue(bundle)
        if queue is not None:
            facts["march_queue_used"], facts["march_queue_capacity"] = queue
            facts["march_queue_source"] = march_queue_source(bundle) or "visible_ocr_queue_anchor"
        level = extract_visible_resource_level(bundle)
        if level is not None:
            facts["selected_search_level"] = level
            facts["selected_search_level_source"] = "visible_ocr_level_text"
        return ObservationBundle(
            bundle.observation,
            replace(bundle.scene, facts=facts),
        )
