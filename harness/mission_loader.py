"""Safe compiler for the trained mission YAML into the runtime graph types."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping

from harness.task_graph import FlowRegistry, TaskFlow, Transition


class MissionCompileError(ValueError):
    """Raised when mission data cannot be compiled safely."""


@dataclass(frozen=True)
class CompletionCriterion:
    predicate_id: str
    canonical_counter_fact: str
    source_text: str
    supporting_evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class CompiledMission:
    flow: TaskFlow
    parameters: Mapping[str, Any]
    source: str
    completion: CompletionCriterion | None = None
    transition_preconditions: Mapping[str, tuple[str, ...]] = field(default_factory=dict)


def _yaml(path: Path) -> Mapping[str, Any]:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise MissionCompileError("PyYAML is required to load mission YAML") from exc
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise MissionCompileError(f"cannot load mission YAML {path}: {exc}") from exc
    if not isinstance(data, Mapping):
        raise MissionCompileError("mission YAML root must be a mapping")
    return data


def _catalog(states: Mapping[str, Any]) -> tuple[set[str], set[str], set[str]]:
    state_ids: set[str] = set(states.get("state_families", []) and
                               (x.get("id") for x in states["state_families"] if isinstance(x, Mapping)))
    target_ids: set[str] = set()
    for item in states.get("states", []):
        if not isinstance(item, Mapping) or not isinstance(item.get("id"), str):
            continue
        state_ids.add(item["id"])
        for target in item.get("entities", []) or []:
            if isinstance(target, str):
                target_ids.add(target)
    families = {x for x in state_ids if any(
        isinstance(s, Mapping) and s.get("id") == x for s in states.get("state_families", []) or []
    )}
    return state_ids, families, target_ids


def _parameter_specs(raw: Any) -> dict[str, Mapping[str, Any]]:
    if raw is None:
        return {}
    if not isinstance(raw, list):
        raise MissionCompileError("parameters must be a list")
    result: dict[str, Mapping[str, Any]] = {}
    for item in raw:
        if isinstance(item, str):
            inferred = "integer" if item == "resource_level" else "string"
            name, spec = item, {"name": item, "type": inferred, "nullable": item == "resource_level"}
        elif isinstance(item, Mapping):
            name, spec = item.get("name"), item
        else:
            raise MissionCompileError("parameter declarations must be names or mappings")
        if not isinstance(name, str) or not name or name in result:
            raise MissionCompileError(f"invalid or duplicate parameter name: {name!r}")
        typ = spec.get("type", "string")
        if typ not in {"string", "integer", "number", "boolean", "null", "any"}:
            raise MissionCompileError(f"unsupported type for parameter {name!r}: {typ!r}")
        result[name] = spec
    return result


def _transition_arguments(
    edge: Mapping[str, Any],
    specs: Mapping[str, Mapping[str, Any]],
    supplied: Mapping[str, Any],
    index: int,
) -> dict[str, Any]:
    names = edge.get("arguments_from_parameters", []) or []
    if not isinstance(names, list) or any(not isinstance(name, str) or not name for name in names):
        raise MissionCompileError(f"invalid arguments_from_parameters in transition {index}")
    unknown = [name for name in names if name not in specs]
    if unknown:
        raise MissionCompileError(
            f"unknown parameter(s) in transition {index} arguments: {unknown!r}"
        )
    return {name: supplied[name] for name in names if name in supplied and supplied[name] is not None}


def compile_mission(mission_path: str | Path, states_path: str | Path,
                    flow_id: str, parameters: Mapping[str, Any] | None = None) -> CompiledMission:
    """Compile one flow; output is directly consumable by ``MissionRuntime``."""
    mission_file, states_file = Path(mission_path), Path(states_path)
    data, states = _yaml(mission_file), _yaml(states_file)
    state_ids, families, target_ids = _catalog(states)
    flows = data.get("flows")
    if not isinstance(flows, list):
        raise MissionCompileError("flows must be a list")
    raw_flow = next((f for f in flows if isinstance(f, Mapping) and f.get("id") == flow_id), None)
    if raw_flow is None:
        raise MissionCompileError(f"unknown flow {flow_id!r}")
    specs = _parameter_specs(raw_flow.get("parameters"))
    supplied = dict(parameters or {})
    unknown = set(supplied) - set(specs)
    if unknown:
        raise MissionCompileError(f"unknown parameter(s): {sorted(unknown)!r}")
    for name, value in supplied.items():
        typ = specs[name].get("type", "string")
        valid = (typ == "any" or value is None and (typ == "null" or specs[name].get("nullable", False)) or
                 typ == "string" and isinstance(value, str) or
                 typ == "integer" and type(value) is int or
                 typ == "number" and isinstance(value, (int, float)) and not isinstance(value, bool) or
                 typ == "boolean" and type(value) is bool)
        if not valid:
            raise MissionCompileError(f"parameter {name!r} does not match type {typ!r}")
    transitions: list[Transition] = []
    preconditions: dict[str, tuple[str, ...]] = {}
    for index, edge in enumerate(raw_flow.get("transitions", []) or []):
        if not isinstance(edge, Mapping):
            raise MissionCompileError(f"transition {index} must be a mapping")
        source = edge.get("from")
        if source not in state_ids:
            raise MissionCompileError(f"unknown state {source!r}")
        expects = tuple(edge.get("expect", []) or [])
        if any(x not in state_ids for x in expects):
            raise MissionCompileError(f"unknown expected state in transition {index}")
        family = edge.get("expect_family")
        if family is not None and family not in families:
            raise MissionCompileError(f"unknown expected state family {family!r}")
        if edge.get("optional") and parameters is not None and parameters.get("resource_level") is None:
            continue
        targets: tuple[str, ...] = ()
        requires = False
        if "target" in edge:
            targets = (edge["target"],)
            requires = True
        elif "target_by_parameter" in edge:
            mapping = edge["target_by_parameter"]
            if not isinstance(mapping, Mapping):
                raise MissionCompileError(f"invalid target_by_parameter in transition {index}")
            if any(key in specs for key in mapping):
                raise MissionCompileError(f"invalid parameter mapping in transition {index}")
            param = "resource_type" if "resource_type" in specs else None
            if param is None:
                raise MissionCompileError("target_by_parameter has no resolvable parameter")
            if parameters is not None and param in parameters:
                if parameters[param] not in mapping:
                    raise MissionCompileError(f"no target mapping for parameter {param!r} value")
                targets = (mapping[parameters[param]],)
            else:
                targets = tuple(mapping.values())
            requires = True
        if any(not isinstance(t, str) or t not in target_ids for t in targets):
            raise MissionCompileError(f"unknown target in transition {index}")
        args = _transition_arguments(edge, specs, supplied, index)
        transitions.append(Transition(source, edge.get("action"), expects, family, requires, targets, args))
        listed_preconditions = edge.get("preconditions", []) or []
        if not isinstance(listed_preconditions, list) or any(not isinstance(x, str) or not x for x in listed_preconditions):
            raise MissionCompileError(f"invalid preconditions in transition {index}")
        if listed_preconditions:
            preconditions[f"{source}:{edge.get('action')}"] = tuple(listed_preconditions)
    completion = raw_flow.get("completion", {}) or {}
    if not isinstance(completion, Mapping):
        raise MissionCompileError("completion must be a mapping")
    complete_states = tuple(x for x in completion.get("success_when", []) if isinstance(x, Mapping) and x.get("state") in state_ids)
    complete_families = tuple(x["state_family"] for x in completion.get("success_when", []) if isinstance(x, Mapping) and x.get("state_family") in families)
    criterion = None
    textual = [x for x in completion.get("success_when", []) if isinstance(x, str)]
    if textual:
        known = "march queue used count increased relative to pre-dispatch observation"
        for item in textual:
            if item != known:
                raise MissionCompileError(f"unsupported completion criterion: {item!r}")
        supporting = tuple(x for x in completion.get("supporting_evidence", []) if isinstance(x, str))
        criterion = CompletionCriterion("march_queue_used_increased", "march_queue_used", known, supporting)
        if transitions:
            transitions[-1] = replace(transitions[-1], completion_edge=True)
    return CompiledMission(TaskFlow(flow_id, tuple(transitions), complete_states, complete_families), supplied, str(mission_file), criterion, preconditions)


def load_mission(mission_path: str | Path, states_path: str | Path, flow_id: str,
                 parameters: Mapping[str, Any] | None = None) -> CompiledMission:
    return compile_mission(mission_path, states_path, flow_id, parameters)
