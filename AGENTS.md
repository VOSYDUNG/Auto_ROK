# Auto_ROK agent build contract

This repository uses **Graph Engineering** as the default build protocol for every coding/research agent.

Authoritative engineering graph: `config/engineering_graph.yaml`.
Human-readable protocol: `docs/GRAPH_ENGINEERING.md`.

## Before changing code

1. Read the smallest source slice needed for the assigned graph nodes.
2. Name the graph nodes you own and the upstream/downstream nodes you can affect.
3. Trace the acceptance path from evidence/input to the requested outcome.
4. Check existing blockers and authority nodes before inventing a new abstraction.
5. Prefer extending the canonical node that already owns a responsibility over creating a parallel runtime.

An assignment is incomplete unless it states:

```text
owned_nodes
upstream_dependencies
downstream_consumers
acceptance_evidence
known_blockers
graph_delta_expected
```

## While building

- Work inside the assigned subgraph. Do not expand scope merely because adjacent files are visible.
- A new module must either replace an existing authority node or connect to at least one producer and one consumer. Isolated helper/framework nodes are rejected unless they are explicit leaf adapters.
- Treat data provenance as graph edges: current frame -> evidence -> classification/fact -> action eligibility -> dispatch -> fresh observation -> verification.
- Do not collapse `DISPATCHED` into `VERIFIED`.
- Do not turn unknown gameplay policy into inferred policy.
- If a discovered interface contradicts the graph, update the graph before building around the contradiction.
- Parallel agents should own disjoint subgraphs whenever possible. Cross-subgraph changes require an explicit integration edge and handoff.

## Graph delta handoff

Agent completion should be compact and graph-shaped:

```text
status: PASS | BLOCKED | NEEDS_DECISION
changed_nodes: [...]
added_edges: [...]
removed_edges: [...]
changed_files: [...]
evidence: tests/artifacts
new_blockers: [...]
resolved_blockers: [...]
next_unblocked_nodes: [...]
```

Do not send progress chatter. Report only hard blockers or the completion delta.

## Acceptance rules

A package is accepted only when all of these are true:

- its graph node has one clear responsibility/authority;
- required incoming/outgoing edges are explicit;
- focused tests or runtime artifacts support the claimed status;
- no unresolved blocker is silently bypassed;
- the engineering graph validates with `python scripts/validate_engineering_graph.py`;
- deterministic behavior remains deterministic; model calls are reserved for real bounded ambiguity.

## Current vertical slice

The active product path is `GATHER_RESOURCE` on one character. Other missions remain separate graph branches and must not be treated as covered merely because shared harness infrastructure exists.
