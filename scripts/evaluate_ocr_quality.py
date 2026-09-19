"""Measure critical-field OCR quality on the persisted ROK corpus.

This is a bounded screening metric, not a label generator.  The label
manifest must bind every frame by capture id and image hash.  Critical-field
CER/WER are computed over the declared field labels (rather than unrelated
resource counters or prose), while precision/recall count exact field
occurrences and duplicate matches.  A second diagnostic pass also reports
bounded one/two-edit OCR normalization, but it never changes the exact
acceptance gate or runtime grounding.  A separate independent reviewer is still required
before the report can satisfy the R1a acceptance gate.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class OcrQualityError(ValueError):
    """Raised when a quality manifest is malformed or not frame-bound."""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OcrQualityError(f"cannot read JSON: {path}") from exc


def _mapping(path: Path, label: str) -> Mapping[str, Any]:
    value = _read_json(path)
    if not isinstance(value, Mapping):
        raise OcrQualityError(f"{label} must be a JSON object: {path}")
    return value


def _normalize(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(_normalize(value).split())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise OcrQualityError(f"cannot hash image: {path}") from exc
    return digest.hexdigest()


def _levenshtein(left: Sequence[Any], right: Sequence[Any]) -> int:
    """Return the standard insertion/deletion/substitution edit distance."""
    previous = list(range(len(right) + 1))
    for row, left_value in enumerate(left, 1):
        current = [row]
        for column, right_value in enumerate(right, 1):
            current.append(min(
                current[-1] + 1,
                previous[column] + 1,
                previous[column - 1] + (left_value != right_value),
            ))
        previous = current
    return previous[-1]


def _repo_path(value: str, root: Path, label: str) -> Path:
    path = (ROOT / value).resolve() if not Path(value).is_absolute() else Path(value).resolve()
    if not path.is_relative_to(root) or path == root:
        raise OcrQualityError(f"{label} must stay under {root}: {value}")
    return path


def _target_specs(path: Path) -> dict[str, tuple[str, ...]]:
    raw = _read_json(path)
    if not isinstance(raw, list):
        raise OcrQualityError(f"OCR target config must be a JSON list: {path}")
    specs: dict[str, tuple[str, ...]] = {}
    for item in raw:
        if not isinstance(item, Mapping):
            raise OcrQualityError("OCR target entries must be objects")
        target_id = item.get("target_id")
        labels = item.get("labels")
        if not isinstance(target_id, str) or not target_id:
            raise OcrQualityError("OCR target id must be a non-empty string")
        if (not isinstance(labels, list) or not labels
                or any(not isinstance(label, str) or not label.strip() for label in labels)):
            raise OcrQualityError(f"OCR target labels are invalid: {target_id}")
        specs[target_id] = tuple(labels)
    return specs


def _flatten_elements(elements: Sequence[Any]) -> tuple[dict[str, Any], ...]:
    """Flatten OCR words while retaining element indices and provenance."""
    flattened: list[dict[str, Any]] = []
    for index, item in enumerate(elements):
        if not isinstance(item, Mapping) or not isinstance(item.get("text"), str):
            raise OcrQualityError(f"OCR element {index} is malformed")
        raw_tokens = _tokens(item["text"])
        if not raw_tokens:
            continue
        bbox = item.get("bbox")
        x = None
        y = None
        if isinstance(bbox, list) and len(bbox) == 4 and type(bbox[0]) is int and type(bbox[1]) is int:
            x = bbox[0]
            y = bbox[1]
        compiled = item.get("grounding_authority") == "compiled_ui_layout"
        for token in raw_tokens:
            flattened.append({
                "token": token,
                "element_index": index,
                "x": x,
                "y": y,
                "compiled": compiled,
                "excluded": item.get("semantic_excluded") is True,
            })
    return tuple(flattened)


def _label_matches(
    flattened: Sequence[Mapping[str, Any]],
    label: str,
    *,
    include_excluded: bool = False,
    allow_bounded_ocr_normalization: bool = False,
) -> tuple[dict[str, Any], ...]:
    """Find bounded contiguous label spans in visible row/column order."""
    wanted = _tokens(label)
    if not wanted:
        return ()
    visible = (item for item in flattened if include_excluded or item.get("excluded") is not True)
    if allow_bounded_ocr_normalization:
        # OCR words on one visual row can differ by a pixel or two.  Cluster
        # only this diagnostic pass into ten-pixel rows; exact matching keeps
        # the historical strict ordering.
        order_key = lambda item: (
            (item["y"] // 10) if type(item.get("y")) is int else 10**9,
            item["x"] if type(item.get("x")) is int else 10**9,
            item["element_index"],
        )
    else:
        order_key = lambda item: (
            item["y"] if type(item.get("y")) is int else 10**9,
            item["x"] if type(item.get("x")) is int else 10**9,
            item["element_index"],
        )
    ordered = sorted(visible, key=order_key)
    matches: list[dict[str, Any]] = []
    for start in range(0, len(ordered) - len(wanted) + 1):
        chunk = ordered[start:start + len(wanted)]
        observed = tuple(item["token"] for item in chunk)
        exact = observed == wanted
        distances = tuple(
            _levenshtein(tuple(item), tuple(expected))
            for item, expected in zip(observed, wanted)
        )
        normalized = False
        if allow_bounded_ocr_normalization and not exact:
            normalized = all(
                min(len(item), len(expected)) >= 4
                and distance <= (2 if min(len(item), len(expected)) >= 6 else 1)
                for item, expected, distance in zip(observed, wanted, distances)
            )
        if not exact and not normalized:
            continue
        ys = [item["y"] for item in chunk if type(item.get("y")) is int]
        # A multi-word field must be on one visible row.  This prevents a
        # top-bar resource counter and a bottom-row compiled word from being
        # joined into a false phrase.
        if len(ys) > 1 and max(ys) - min(ys) > 60:
            continue
        element_indices = tuple(dict.fromkeys(int(item["element_index"]) for item in chunk))
        key = (element_indices, wanted)
        if any(existing["key"] == key for existing in matches):
            continue
        matches.append({
            "key": key,
            "label": label,
            "tokens": tuple(item["token"] for item in chunk),
            "element_indices": element_indices,
            "compiled": any(bool(item.get("compiled")) for item in chunk),
            "match_mode": "exact" if exact else "bounded_edit_distance_1_or_2",
            "token_edit_distances": distances,
        })
    return tuple(matches)


def _lock_summary(manifest: Mapping[str, Any], entries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    requirements = manifest.get("lock_requirements")
    if not isinstance(requirements, Mapping):
        requirements = {}
    minimum = requirements.get("minimum_reviewers", 2)
    if type(minimum) is not int or minimum < 2:
        minimum = 2
    reviewers = manifest.get("reviewers")
    if not isinstance(reviewers, list):
        reviewers = []
    valid_reviewers = [
        reviewer for reviewer in reviewers
        if isinstance(reviewer, Mapping)
        and isinstance(reviewer.get("reviewer_id"), str)
        and reviewer.get("reviewer_id")
        and isinstance(reviewer.get("reviewed_at"), str)
    ]
    independent = [reviewer for reviewer in valid_reviewers if reviewer.get("independent") is True]
    entry_locked = sum(1 for entry in entries if entry.get("review_status") == "independently_locked")
    reasons: list[str] = []
    if len(valid_reviewers) < minimum:
        reasons.append(f"requires at least {minimum} dated reviewers")
    if not independent:
        reasons.append("no independently identified reviewer is recorded")
    if entry_locked != len(entries):
        reasons.append(f"{len(entries) - entry_locked} corpus labels are not independently locked")
    ready = not reasons
    return {
        "status": "locked" if ready else "pending_independent_review",
        "ready": ready,
        "minimum_reviewers": minimum,
        "reviewer_count": len(valid_reviewers),
        "independent_reviewer_count": len(independent),
        "entries": len(entries),
        "independently_locked_entries": entry_locked,
        "reasons": reasons,
    }


def _run_entry(
    entry: Mapping[str, Any],
    corpus_by_id: Mapping[str, Mapping[str, Any]],
    target_labels: Mapping[str, tuple[str, ...]],
) -> dict[str, Any]:
    entry_id = entry.get("id")
    if not isinstance(entry_id, str) or not entry_id:
        raise OcrQualityError("quality entry id is required")
    corpus = corpus_by_id.get(entry_id)
    if corpus is None:
        raise OcrQualityError(f"quality entry is not present in corpus: {entry_id}")
    capture_dir = corpus.get("capture_dir")
    if not isinstance(capture_dir, str):
        raise OcrQualityError(f"corpus capture_dir is missing: {entry_id}")
    run_dir = _repo_path(capture_dir, (ROOT / "workspace" / "runs").resolve(), "capture_dir")
    capture_path = run_dir / "capture.json"
    image_path = run_dir / "rok-client.png"
    ocr_name = corpus.get("ocr_file", "ocr.json")
    if not isinstance(ocr_name, str) or Path(ocr_name).name != ocr_name:
        raise OcrQualityError(f"corpus OCR file is invalid: {entry_id}")
    ocr_path = run_dir / ocr_name
    capture = _mapping(capture_path, "capture")
    frame = capture.get("frame")
    if not isinstance(frame, Mapping) or not isinstance(frame.get("id"), str):
        raise OcrQualityError(f"capture frame id is missing: {entry_id}")
    digest = _sha256(image_path)
    if entry.get("capture_frame_id") != frame["id"]:
        raise OcrQualityError(f"quality manifest frame id does not match capture: {entry_id}")
    if entry.get("image_sha256") != digest:
        raise OcrQualityError(f"quality manifest image hash does not match capture: {entry_id}")
    expected_state = entry.get("expected_state")
    if expected_state != corpus.get("expected_state"):
        raise OcrQualityError(f"quality manifest state does not match corpus: {entry_id}")
    critical_ids = entry.get("critical_target_ids")
    if (not isinstance(critical_ids, list) or not critical_ids
            or any(not isinstance(target_id, str) or target_id not in target_labels for target_id in critical_ids)):
        raise OcrQualityError(f"critical_target_ids are invalid: {entry_id}")
    ocr = _mapping(ocr_path, "OCR")
    if ocr.get("frame_id") != frame["id"] or ocr.get("image_sha256") != digest:
        raise OcrQualityError(f"OCR is not bound to capture image/frame: {entry_id}")
    elements = ocr.get("elements")
    if not isinstance(elements, list):
        raise OcrQualityError(f"OCR elements are missing: {entry_id}")
    flattened = _flatten_elements(elements)
    raw_flattened = tuple(item for item in flattened if not item["compiled"])
    fields: list[dict[str, Any]] = []
    tp = fp = fn = 0
    raw_tp = raw_fp = raw_fn = 0
    normalized_tp = normalized_fp = normalized_fn = 0
    expected_words: list[str] = []
    observed_words: list[str] = []
    expected_chars: list[str] = []
    observed_chars: list[str] = []
    raw_observed_words: list[str] = []
    raw_observed_chars: list[str] = []
    normalized_observed_words: list[str] = []
    normalized_observed_chars: list[str] = []
    compiled_hits = 0
    ocr_hits = 0
    for target_id in critical_ids:
        labels = target_labels[target_id]
        expected_label = labels[0]
        expected_tokens = list(_tokens(expected_label))
        expected_words.extend(expected_tokens)
        expected_chars.extend(list(_normalize(expected_label)))
        matches: list[dict[str, Any]] = []
        for label in labels:
            matches.extend(_label_matches(flattened, label))
        # Same field can be listed through equivalent label alternatives; the
        # element-index key makes those alternatives one observed occurrence.
        unique: dict[Any, dict[str, Any]] = {match["key"]: match for match in matches}
        matches = list(unique.values())
        raw_matches: list[dict[str, Any]] = []
        for label in labels:
            raw_matches.extend(_label_matches(raw_flattened, label, include_excluded=True))
        unique_raw: dict[Any, dict[str, Any]] = {match["key"]: match for match in raw_matches}
        raw_matches = [match for match in unique_raw.values() if not match["compiled"]]
        normalized_matches: list[dict[str, Any]] = []
        for label in labels:
            normalized_matches.extend(
                _label_matches(
                    raw_flattened,
                    label,
                    include_excluded=True,
                    allow_bounded_ocr_normalization=True,
                )
            )
        unique_normalized: dict[Any, dict[str, Any]] = {
            match["key"]: match for match in normalized_matches
        }
        normalized_matches = [
            match for match in unique_normalized.values() if not match["compiled"]
        ]
        hit = bool(matches)
        if hit:
            tp += 1
            fp += max(0, len(matches) - 1)
            chosen = matches[0]
            observed_words.extend(chosen["tokens"])
            observed_chars.extend(list(" ".join(chosen["tokens"])))
            if chosen["compiled"]:
                compiled_hits += 1
            else:
                ocr_hits += 1
        else:
            fn += 1
        if raw_matches:
            raw_tp += 1
            raw_fp += max(0, len(raw_matches) - 1)
            raw_observed_words.extend(raw_matches[0]["tokens"])
            raw_observed_chars.extend(list(" ".join(raw_matches[0]["tokens"])))
        else:
            raw_fn += 1
        if normalized_matches:
            normalized_tp += 1
            normalized_fp += max(0, len(normalized_matches) - 1)
            normalized_observed_words.extend(normalized_matches[0]["tokens"])
            normalized_observed_chars.extend(list(" ".join(normalized_matches[0]["tokens"])))
        else:
            normalized_fn += 1
        fields.append({
            "target_id": target_id,
            "expected_label": expected_label,
            "match_count": len(matches),
            "raw_match_count": len(raw_matches),
            "normalized_ocr_match_count": len(normalized_matches),
            "normalized_ocr_match_mode": (
                normalized_matches[0]["match_mode"] if normalized_matches else None
            ),
            "compiled_match_count": len(matches) - len(raw_matches),
            "status": "hit" if hit else "miss",
            "source": "compiled_ui_layout" if hit and matches[0]["compiled"] else "ocr_backend" if hit else None,
        })
    return {
        "id": entry_id,
        "status": "ok",
        "split": corpus.get("split"),
        "expected_state": expected_state,
        "critical_fields": fields,
        "true_positive_fields": tp,
        "false_positive_fields": fp,
        "false_negative_fields": fn,
        "ocr_true_positive_fields": raw_tp,
        "ocr_false_positive_fields": raw_fp,
        "ocr_false_negative_fields": raw_fn,
        "normalized_ocr_true_positive_fields": normalized_tp,
        "normalized_ocr_false_positive_fields": normalized_fp,
        "normalized_ocr_false_negative_fields": normalized_fn,
        "reference_word_count": len(expected_words),
        "reference_character_count": len(expected_chars),
        "word_errors": _levenshtein(expected_words, observed_words),
        "character_errors": _levenshtein(expected_chars, observed_chars),
        "ocr_word_errors": _levenshtein(expected_words, raw_observed_words),
        "ocr_character_errors": _levenshtein(expected_chars, raw_observed_chars),
        "normalized_ocr_word_errors": _levenshtein(expected_words, normalized_observed_words),
        "normalized_ocr_character_errors": _levenshtein(expected_chars, normalized_observed_chars),
        "compiled_ui_layout_hits": compiled_hits,
        "ocr_backend_hits": ocr_hits,
        "input_emitted": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-manifest", default=str(ROOT / "config" / "observation_corpus.json"))
    parser.add_argument("--label-manifest", default=str(ROOT / "config" / "observation_label_lock.json"))
    parser.add_argument("--ocr-targets", default=str(ROOT / "config" / "gather_ocr_targets.json"))
    parser.add_argument("--evidence-root", default=str(ROOT / "workspace" / "evidence" / "corpus"))
    parser.add_argument("--report-id", default="ocr-quality-20260918-01")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        corpus = _mapping(Path(args.corpus_manifest).resolve(), "corpus manifest")
        label_manifest = _mapping(Path(args.label_manifest).resolve(), "label manifest")
        target_labels = _target_specs(Path(args.ocr_targets).resolve())
        raw_corpus_entries = corpus.get("entries")
        raw_quality_entries = label_manifest.get("entries")
        if not isinstance(raw_corpus_entries, list) or not raw_corpus_entries:
            raise OcrQualityError("corpus manifest entries must be a non-empty list")
        if not isinstance(raw_quality_entries, list) or not raw_quality_entries:
            raise OcrQualityError("label manifest entries must be a non-empty list")
        corpus_by_id = {
            entry["id"]: entry for entry in raw_corpus_entries
            if isinstance(entry, Mapping) and isinstance(entry.get("id"), str)
        }
        results: list[dict[str, Any]] = []
        for entry in raw_quality_entries:
            if not isinstance(entry, Mapping):
                raise OcrQualityError("label manifest entries must be objects")
            try:
                results.append(_run_entry(entry, corpus_by_id, target_labels))
            except OcrQualityError as exc:
                results.append({
                    "id": entry.get("id"),
                    "status": "error",
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                    "input_emitted": False,
                })
        successful = [item for item in results if item.get("status") == "ok"]
        labelled = [item for item in successful if item.get("split") == "labelled"]
        holdout = [item for item in successful if item.get("split") == "holdout"]
        tp = sum(int(item.get("true_positive_fields", 0)) for item in successful)
        fp = sum(int(item.get("false_positive_fields", 0)) for item in successful)
        fn = sum(int(item.get("false_negative_fields", 0)) for item in successful)
        raw_tp = sum(int(item.get("ocr_true_positive_fields", 0)) for item in successful)
        raw_fp = sum(int(item.get("ocr_false_positive_fields", 0)) for item in successful)
        raw_fn = sum(int(item.get("ocr_false_negative_fields", 0)) for item in successful)
        normalized_tp = sum(int(item.get("normalized_ocr_true_positive_fields", 0)) for item in successful)
        normalized_fp = sum(int(item.get("normalized_ocr_false_positive_fields", 0)) for item in successful)
        normalized_fn = sum(int(item.get("normalized_ocr_false_negative_fields", 0)) for item in successful)
        word_errors = sum(int(item.get("word_errors", 0)) for item in successful)
        character_errors = sum(int(item.get("character_errors", 0)) for item in successful)
        raw_word_errors = sum(int(item.get("ocr_word_errors", 0)) for item in successful)
        raw_character_errors = sum(int(item.get("ocr_character_errors", 0)) for item in successful)
        normalized_word_errors = sum(int(item.get("normalized_ocr_word_errors", 0)) for item in successful)
        normalized_character_errors = sum(int(item.get("normalized_ocr_character_errors", 0)) for item in successful)
        reference_words = sum(int(item.get("reference_word_count", 0)) for item in successful)
        reference_characters = sum(int(item.get("reference_character_count", 0)) for item in successful)
        precision = tp / (tp + fp) if tp + fp else None
        recall = tp / (tp + fn) if tp + fn else None
        raw_precision = raw_tp / (raw_tp + raw_fp) if raw_tp + raw_fp else None
        raw_recall = raw_tp / (raw_tp + raw_fn) if raw_tp + raw_fn else None
        normalized_precision = normalized_tp / (normalized_tp + normalized_fp) if normalized_tp + normalized_fp else None
        normalized_recall = normalized_tp / (normalized_tp + normalized_fn) if normalized_tp + normalized_fn else None
        lock = _lock_summary(label_manifest, raw_quality_entries)
        acceptance_reasons = list(lock["reasons"])
        if raw_precision is None or raw_precision < 0.95:
            acceptance_reasons.append("OCR-only critical-field precision is below 95% or unavailable")
        if raw_recall is None or raw_recall < 0.90:
            acceptance_reasons.append("OCR-only critical-field recall is below 90% or unavailable")
        report = {
            "schema_version": 1,
            "report_id": args.report_id,
            "status": "screening_only",
            "measurement_class": "critical_field_ocr_screening",
            "label_status": label_manifest.get("status"),
            "acceptance": {
                "prd_r1a": "ready" if not acceptance_reasons else "not_ready",
                "reason": acceptance_reasons,
                "precision_target": 0.95,
                "recall_target": 0.90,
            },
            "label_lock": lock,
            "counts": {
                "manifest_entries": len(raw_quality_entries),
                "successful": len(successful),
                "errors": len(results) - len(successful),
                "labelled": len(labelled),
                "holdout": len(holdout),
                "reference_fields": tp + fn,
                "true_positive_fields": tp,
                "false_positive_fields": fp,
                "false_negative_fields": fn,
                "ocr_true_positive_fields": raw_tp,
                "ocr_false_positive_fields": raw_fp,
                "ocr_false_negative_fields": raw_fn,
                "normalized_ocr_true_positive_fields": normalized_tp,
                "normalized_ocr_false_positive_fields": normalized_fp,
                "normalized_ocr_false_negative_fields": normalized_fn,
            },
            "metrics": {
                "scope": "declared critical field labels only; not a full-frame OCR transcript",
                "critical_field_precision_with_layout": precision,
                "critical_field_recall_with_layout": recall,
                "critical_field_character_error_rate_with_layout": character_errors / reference_characters if reference_characters else None,
                "critical_field_word_error_rate_with_layout": word_errors / reference_words if reference_words else None,
                "critical_field_precision_ocr_only": raw_precision,
                "critical_field_recall_ocr_only": raw_recall,
                "critical_field_character_error_rate_ocr_only": raw_character_errors / reference_characters if reference_characters else None,
                "critical_field_word_error_rate_ocr_only": raw_word_errors / reference_words if reference_words else None,
                "critical_field_precision_ocr_bounded_normalized": normalized_precision,
                "critical_field_recall_ocr_bounded_normalized": normalized_recall,
                "critical_field_character_error_rate_ocr_bounded_normalized": normalized_character_errors / reference_characters if reference_characters else None,
                "critical_field_word_error_rate_ocr_bounded_normalized": normalized_word_errors / reference_words if reference_words else None,
                "character_errors": character_errors,
                "word_errors": word_errors,
                "ocr_character_errors": raw_character_errors,
                "ocr_word_errors": raw_word_errors,
                "normalized_ocr_character_errors": normalized_character_errors,
                "normalized_ocr_word_errors": normalized_word_errors,
                "reference_character_count": reference_characters,
                "reference_word_count": reference_words,
                "ocr_normalization": {
                    "mode": "bounded_edit_distance_1_or_2_per_token",
                    "minimum_token_length": 4,
                    "acceptance_uses_exact_metrics": True,
                    "runtime_grounding_changed": False,
                },
                "grounding_source_totals": {
                    "compiled_ui_layout": sum(int(item.get("compiled_ui_layout_hits", 0)) for item in successful),
                    "ocr_backend": sum(int(item.get("ocr_backend_hits", 0)) for item in successful),
                },
            },
            "input_emitted_any": any(bool(item.get("input_emitted")) for item in results),
            "results": results,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        evidence_root = Path(args.evidence_root).resolve()
        if not evidence_root.is_relative_to((ROOT / "workspace" / "evidence").resolve()):
            raise OcrQualityError("evidence-root must stay under workspace/evidence")
        evidence_root.mkdir(parents=True, exist_ok=True)
        output_path = evidence_root / f"{args.report_id}.json"
        temporary = output_path.with_name(output_path.name + ".tmp")
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(output_path)
        printed = dict(report)
        printed["evidence_path"] = str(output_path)
        print(json.dumps(printed, ensure_ascii=False))
        return 0 if not results or all(item.get("status") == "ok" for item in results) else 2
    except (OSError, OcrQualityError) as exc:
        print(json.dumps({
            "schema_version": 1,
            "status": "invalid",
            "error": {"type": type(exc).__name__, "message": str(exc)},
            "input_emitted": False,
        }, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
