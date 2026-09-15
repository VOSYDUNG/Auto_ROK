"""Validate the machine-readable Auto_ROK engineering graph.

This is intentionally dependency-light except for PyYAML, which is already a
mission compiler dependency. The validator fails closed on stale file/evidence
references and malformed graph relationships.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
import sys

ROOT = Path(__file__).resolve().parents[1]
GRAPH = ROOT / "config" / "engineering_graph.yaml"

VALID_STATUSES = {"implemented", "partial", "blocked", "needs_decision", "deferred"}
VALID_AUTHORITIES = {"canonical", "missing", "operator", "evidence"}
VALID_COVERAGE = {
    "covered",
    "partial",
    "missing",
    "needs_decision",
    "not_covered_end_to_end",
    "training_only",
    "deferred",
}


class GraphValidationError(ValueError):
    pass


def need(condition: bool, message: str) -> None:
    if not condition:
        raise GraphValidationError(message)


def load_graph(path: Path = GRAPH) -> Mapping[str, Any]:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise GraphValidationError("PyYAML is required") from exc
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise GraphValidationError(f"cannot read graph: {exc}") from exc
    except yaml.YAMLError as exc:
        raise GraphValidationError(f"invalid graph YAML: {exc}") from exc
    need(isinstance(value, Mapping), "graph root must be a mapping")
    return value


def validate_graph(graph: Mapping[str, Any]) -> None:
    need(graph.get("schema_version") == 1, "unsupported engineering graph schema")
    need(isinstance(graph.get("graph_id"), str) and graph["graph_id"], "graph_id is required")

    raw_nodes = graph.get("nodes")
    need(isinstance(raw_nodes, list) and raw_nodes, "nodes must be a non-empty list")
    nodes: dict[str, Mapping[str, Any]] = {}
    for index, raw in enumerate(raw_nodes):
        need(isinstance(raw, Mapping), f"node {index} must be a mapping")
        node_id = raw.get("id")
        need(isinstance(node_id, str) and node_id, f"node {index} needs id")
        need(node_id not in nodes, f"duplicate node id: {node_id}")
        nodes[node_id] = raw
        need(raw.get("status") in VALID_STATUSES, f"node {node_id} has invalid status")
        need(raw.get("authority") in VALID_AUTHORITIES, f"node {node_id} has invalid authority")
        need(isinstance(raw.get("responsibility"), str) and raw["responsibility"],
             f"node {node_id} needs responsibility")

        if raw.get("status") == "implemented":
            path = raw.get("path")
            need(isinstance(path, str) and path, f"implemented node {node_id} needs path")
            need((ROOT / path).is_file(), f"implemented node {node_id} path does not exist: {path}")
            evidence = raw.get("evidence")
            need(isinstance(evidence, list) and evidence,
                 f"implemented node {node_id} needs acceptance evidence")
            for evidence_path in evidence:
                need(isinstance(evidence_path, str) and evidence_path,
                     f"node {node_id} has invalid evidence path")
                need((ROOT / evidence_path).exists(),
                     f"node {node_id} evidence does not exist: {evidence_path}")

    raw_edges = graph.get("edges")
    need(isinstance(raw_edges, list) and raw_edges, "edges must be a non-empty list")
    seen_edges: set[tuple[str, str, str]] = set()
    connected: set[str] = set()
    for index, edge in enumerate(raw_edges):
        need(isinstance(edge, Mapping), f"edge {index} must be a mapping")
        source, target, relation = edge.get("from"), edge.get("to"), edge.get("relation")
        need(source in nodes, f"edge {index} source is unknown: {source!r}")
        need(target in nodes, f"edge {index} target is unknown: {target!r}")
        need(source != target, f"edge {index} cannot self-reference")
        need(isinstance(relation, str) and relation, f"edge {index} needs relation")
        key = (source, target, relation)
        need(key not in seen_edges, f"duplicate edge: {key}")
        seen_edges.add(key)
        connected.update((source, target))

    for node_id, node in nodes.items():
        # Explicit blockers/policy leaves may still be graph-connected; an isolated
        # implementation is always suspicious and is rejected.
        if node.get("status") == "implemented":
            need(node_id in connected, f"implemented node is isolated: {node_id}")

    roots = graph.get("roots")
    need(isinstance(roots, list) and roots, "roots must be a non-empty list")
    for root in roots:
        need(root in nodes, f"unknown root node: {root!r}")

    required_path = graph.get("required_runtime_path")
    need(isinstance(required_path, list) and required_path,
         "required_runtime_path must be a non-empty list")
    need(len(required_path) == len(set(required_path)), "required_runtime_path contains duplicates")
    for node_id in required_path:
        need(node_id in nodes, f"runtime path references unknown node: {node_id!r}")

    raw_blockers = graph.get("blockers")
    need(isinstance(raw_blockers, list), "blockers must be a list")
    blockers: dict[str, Mapping[str, Any]] = {}
    for index, blocker in enumerate(raw_blockers):
        need(isinstance(blocker, Mapping), f"blocker {index} must be a mapping")
        blocker_id = blocker.get("id")
        need(isinstance(blocker_id, str) and blocker_id, f"blocker {index} needs id")
        need(blocker_id not in blockers, f"duplicate blocker id: {blocker_id}")
        blockers[blocker_id] = blocker
        blocked_nodes = blocker.get("blocks")
        need(isinstance(blocked_nodes, list) and blocked_nodes, f"blocker {blocker_id} needs blocked nodes")
        for node_id in blocked_nodes:
            need(node_id in nodes, f"blocker {blocker_id} references unknown node {node_id!r}")
        need(isinstance(blocker.get("falsification"), str) and blocker["falsification"],
             f"blocker {blocker_id} needs falsification evidence")

    for node_id, node in nodes.items():
        blocker_id = node.get("blocker")
        if node.get("status") in {"blocked", "needs_decision"}:
            need(blocker_id in blockers, f"{node_id} must reference a declared blocker")
            need(node_id in blockers[blocker_id].get("blocks", []),
                 f"blocker {blocker_id} does not list node {node_id}")
        elif blocker_id is not None:
            need(blocker_id in blockers, f"node {node_id} references unknown blocker")

    coverage = graph.get("coverage")
    need(isinstance(coverage, Mapping), "coverage mapping is required")
    dimensions = coverage.get("dimensions")
    need(isinstance(dimensions, Mapping) and dimensions, "coverage dimensions are required")
    for name, value in dimensions.items():
        need(value in VALID_COVERAGE, f"coverage {name} has invalid value {value!r}")
    branches = coverage.get("other_mission_branches")
    need(isinstance(branches, Mapping), "other_mission_branches must be a mapping")
    for name, value in branches.items():
        need(value in VALID_COVERAGE, f"mission coverage {name} has invalid value {value!r}")


def main() -> int:
    try:
        validate_graph(load_graph())
    except GraphValidationError as exc:
        print(f"engineering-graph: FAIL: {exc}", file=sys.stderr)
        return 2
    print("engineering-graph: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
