"""Visible-evidence fact enrichment for the one-character GATHER_RESOURCE slice."""
from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path
import re
from typing import Iterable

from harness.contracts import BoundingBox
from harness.mission_runtime import MissionContext
from harness.mission_tool import ObservationBundle, ObservationProvider


_QUEUE = re.compile(r"\bqueue\s*(\d{1,2})\s*/\s*(\d{1,2})\b", re.IGNORECASE)
_QUEUE_RATIO = re.compile(r"(?<!\d)(\d{1,2})\s*/\s*(\d{1,2})(?!\d)")
_LEVEL = re.compile(r"\b(?:level|lvl|lv\.?)\s*[:\-]?\s*(\d{1,2})\b", re.IGNORECASE)
_QUEUE_ROI_ACQUISITIONS = frozenset({"ocr_march_queue_region"})
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_TROOPS_HEADER = ("Troops", "Unrestricted", "Troop", "Movement", "Guide")
_POSITIVE_NUMBER = re.compile(r"[1-9]\d{0,2}(?:,\d{3})*\Z")
_NEW_TROOP_SOURCE = "same_frame_new_troop_ocr_and_pixels_1366x768"


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
            # A "115" normalization used to live here, because
            # Windows.Media.Ocr renders the thin queue slash as a middle 1.
            # It was removed on 2026-09-20 with the OCR path that produced it:
            # the queue now comes from harness/queue_indicator.py, which reads
            # the glyphs directly and refuses rather than emitting a shape that
            # needs repairing downstream.
            #
            # The pattern was also unsafe on its own terms - ([0-9])1([0-9])
            # turns 213 into 2/3 and 919 into 9/9.
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
        # The "115 means 1/5" workaround was removed from extract_march_queue
        # above, and a second copy survived here until 2026-09-20. It is gone
        # for the same reason: ([0-9])1([0-9]) also reads 213 as 2/3 and 919
        # as 9/9. Here it could only mislabel PROVENANCE rather than a value,
        # which is worse in its own way - it would claim a reading came from
        # the queue region on the strength of a pattern known to be unsafe.
        ratios = _QUEUE_RATIO.findall(text)
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


def _ocr_box(evidence: object, width: int, height: int) -> tuple[int, int, int, int] | None:
    box = getattr(evidence, "bbox", None)
    if not isinstance(box, BoundingBox):
        return None
    values = (box.x1, box.y1, box.x2, box.y2)
    if not all(type(value) is int for value in values):
        return None
    x1, y1, x2, y2 = values
    if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        return None
    return values


def extract_visible_troops_status(bundle: ObservationBundle) -> str | None:
    """Read only a panel-anchored Gathering token; never assign a troop row.

    The relative layout is supported by one saved 1366x768 Troops frame. It is
    deliberately narrow and must be revalidated before use on other layouts.
    """
    frame = bundle.scene.frame_id
    image_hash = bundle.scene.facts.get("image_sha256")
    size = bundle.observation.window_size
    if (bundle.observation.frame_id != frame or not isinstance(image_hash, str)
            or _SHA256.fullmatch(image_hash) is None
            or size != (1366, 768)):
        return None
    width, height = size
    matched: dict[str, list[tuple[int, int, int, int]]] = {}
    for evidence in bundle.observation.evidence:
        if (evidence.source != "ocr" or evidence.metadata.get("frame_id") != frame
                or evidence.metadata.get("image_sha256") != image_hash):
            continue
        value = evidence.value if isinstance(evidence.value, str) else evidence.label
        if not isinstance(value, str) or (isinstance(evidence.value, str)
                and isinstance(evidence.label, str) and evidence.value != evidence.label):
            continue
        if value not in (*_TROOPS_HEADER, "Gathering", "Returning", "Home"):
            continue
        box = _ocr_box(evidence, width, height)
        if box is None:
            return None
        matched.setdefault(value, []).append(box)
    if (any(len(matched.get(word, [])) != 1 for word in (*_TROOPS_HEADER, "Gathering"))
            or "Returning" in matched or "Home" in matched):
        return None
    title = matched["Troops"][0]
    subtitle = [matched[word][0] for word in _TROOPS_HEADER[1:]]
    status = matched["Gathering"][0]
    if not (title[3] < min(box[1] for box in subtitle)
            and max(box[1] for box in subtitle) - min(box[1] for box in subtitle)
            <= max(box[3] - box[1] for box in subtitle)
            and all(left[2] <= right[0] <= left[2] + max(left[2] - left[0], right[2] - right[0])
                    for left, right in zip(subtitle, subtitle[1:]))):
        return None
    subtitle_left, subtitle_right = subtitle[0][0], subtitle[-1][2]
    if not (subtitle_left <= (title[0] + title[2]) / 2 <= subtitle_right
            and subtitle_left <= status[0] < status[2] <= subtitle_right):
        return None
    # Bounds are relative to the observed title/subtitle separation, not screen coordinates.
    title_gap = min(box[1] for box in subtitle) - title[3]
    if not (0 < title_gap and max(box[3] for box in subtitle) < status[1]
            <= max(box[3] for box in subtitle) + 3 * title_gap):
        return None
    return "Gathering"


def _new_troop_pixels(image_path: str, image_hash: str) -> bool:
    """Check only the hashed current frame against the archived 1366x768 layout.

    Color checks establish two occupied portrait regions, a nonempty troop
    slider and an active orange March button. They do not identify commanders.
    Optional vision dependencies fail closed when the live profile lacks them.
    """
    try:
        import cv2
        import numpy as np

        data = Path(image_path).read_bytes()
        if hashlib.sha256(data).hexdigest() != image_hash:
            return False
        image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None or image.shape[:2] != (768, 1366):
            return False

        def region(x1: int, y1: int, x2: int, y2: int):
            return image[y1:y2, x1:x2]

        def portrait_occupied(rect: tuple[int, int, int, int], minimum: float) -> bool:
            patch = region(*rect)
            blue, green, red = (patch[:, :, channel].astype(np.float32)
                                for channel in range(3))
            # The empty portrait backdrop is cyan. Clothes/skin and facial
            # detail in all four archived pairs depart substantially from it.
            foreground = (red > green * .9) & (red > blue * .8)
            return float(np.mean(foreground)) >= minimum

        button = region(815, 568, 975, 607)
        blue, green, red = (button[:, :, channel].astype(np.float32)
                            for channel in range(3))
        orange = (red > 170) & (green > 75) & (green < 210) & (blue < 70) & (red > green * 1.2)
        slider = region(703, 233, 735, 246)
        blue, green, red = (slider[:, :, channel].astype(np.float32)
                            for channel in range(3))
        # Archived positives used a green selected-row fill.  The current
        # client renders a blue/white fill extending to the right of the
        # slider knob.  Empty rows have only the left knob highlight, so use
        # row-local right-side fill as the distinguishing signal; colour alone
        # is deliberately insufficient.
        selected_green = (green > 100) & (green > red * 1.3) & (green > blue * 1.3)
        blue_pixels = ((blue > 150) & (green > 120)
                       & (blue > green * 1.05) & (blue > red * 1.3))
        selected_blue = (float(np.mean(blue_pixels)) >= .10
                         and float(np.mean(blue_pixels[:, 10:])) >= .05)
        return (float(np.mean(orange)) >= .70
                and (float(np.mean(selected_green)) >= .50
                     or selected_blue)
                and portrait_occupied((380, 245, 500, 465), .25)
                and portrait_occupied((520, 295, 595, 465), .20))
    except (ImportError, OSError, ValueError):
        return False


def extract_new_troop_formation_ready(bundle: ObservationBundle) -> bool:
    """Conservative current-frame New Troop readiness for the game-filled pair."""
    frame = bundle.scene.frame_id
    facts = bundle.scene.facts
    image_hash = facts.get("image_sha256")
    image_path = facts.get("image_path")
    if (not frame or bundle.observation.frame_id != frame
            or bundle.observation.window_size != (1366, 768)
            or not isinstance(image_hash, str) or _SHA256.fullmatch(image_hash) is None
            or facts.get("image_path_source") != "current_capture_artifact"
            or not isinstance(image_path, str) or not image_path):
        return False

    def current_ocr(item: object) -> bool:
        return (getattr(item, "source", None) == "ocr"
                and getattr(item, "metadata", {}).get("frame_id") == frame
                and getattr(item, "metadata", {}).get("image_sha256") == image_hash)

    ocr = [item for item in bundle.observation.evidence if current_ocr(item)]
    tokens: list[tuple[str, tuple[int, int, int, int]]] = []
    for item in ocr:
        value = item.value if isinstance(item.value, str) else item.label
        if not isinstance(value, str) or not value.strip():
            continue
        box = _ocr_box(item, 1366, 768)
        if box is None:
            return False
        tokens.append((value.strip(), box))

    def unique(label: str, zone: tuple[int, int, int, int]):
        matched = [box for value, box in tokens if value.casefold() == label.casefold()
                   and zone[0] <= box[0] < box[2] <= zone[2]
                   and zone[1] <= box[1] < box[3] <= zone[3]]
        return matched[0] if len(matched) == 1 else None

    title = unique("New Troop", (580, 120, 780, 175))
    if title is None:
        new = unique("New", (580, 120, 700, 175))
        troop = unique("Troop", (650, 120, 780, 175))
        if new is None or troop is None or not (new[2] <= troop[0] <= new[2] + 20):
            return False
    march_box = unique("MARCH", (830, 555, 965, 600))
    if march_box is None:
        return False
    targets = [target for target in bundle.scene.targets if target.target_id == "TROOP_MARCH"]
    if (len(targets) != 1 or targets[0].frame_id != frame
            or targets[0].metadata.get("image_sha256") != image_hash
            or targets[0].source != "ocr" or targets[0].label.casefold() != "march"
            or _ocr_box(targets[0], 1366, 768) != march_box):
        return False

    power = unique("Total Power", (640, 495, 750, 535))
    if power is None:
        total = unique("Total", (640, 495, 710, 535))
        label = unique("Power:", (690, 495, 750, 535))
        if total is None or label is None or not total[2] <= label[0] <= total[2] + 12:
            return False
    positive_power = [box for value, box in tokens if _POSITIVE_NUMBER.fullmatch(value)
                      and 730 <= box[0] < box[2] <= 820 and 505 <= box[1] < box[3] <= 535]
    positive_troops = [box for value, box in tokens if _POSITIVE_NUMBER.fullmatch(value)
                       and 925 <= box[0] < box[2] <= 995 and 225 <= box[1] < box[3] <= 470]
    if len(positive_power) != 1 or not positive_troops:
        return False
    return _new_troop_pixels(image_path, image_hash)


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
        for key in ("troops_visible_status", "troops_visible_status_source",
                    "troops_visible_status_frame_id", "troops_visible_status_image_sha256"):
            facts.pop(key, None)
        for key in ("new_troop_formation_ready", "new_troop_formation_source",
                    "new_troop_formation_frame_id", "new_troop_formation_image_sha256"):
            facts.pop(key, None)
        if extract_new_troop_formation_ready(bundle):
            facts["new_troop_formation_ready"] = True
            facts["new_troop_formation_source"] = _NEW_TROOP_SOURCE
            facts["new_troop_formation_frame_id"] = bundle.scene.frame_id
            facts["new_troop_formation_image_sha256"] = facts["image_sha256"]
        troops_status = extract_visible_troops_status(bundle)
        if troops_status is not None:
            facts["troops_visible_status"] = troops_status
            facts["troops_visible_status_source"] = "same_frame_ocr_troops_layout"
            facts["troops_visible_status_frame_id"] = bundle.scene.frame_id
            facts["troops_visible_status_image_sha256"] = facts["image_sha256"]
        return ObservationBundle(
            bundle.observation,
            replace(bundle.scene, facts=facts),
        )
