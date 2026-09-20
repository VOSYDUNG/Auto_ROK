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
- focused tests or runtime artifacts support the claimed status, **at the level
  those artifacts actually establish** — see "Completion status levels" below;
- no unresolved blocker is silently bypassed;
- the engineering graph validates with `python scripts/validate_engineering_graph.py`;
- deterministic behavior remains deterministic; model calls are reserved for real bounded ambiguity.

## Completion status levels

Every capability claim must name the highest level it has actually evidenced.
This applies to Claude and Codex alike: both operate as the same Engineering
Agent and are bound by the same ladder.

```text
UNIMPLEMENTED      the capability does not exist in the canonical runtime
IMPLEMENTED        the code exists and focused tests may pass
WIRED              the canonical runtime imports and constructs the component,
                   and a downstream consumer actually uses its output
LIVE_PROVEN_ONCE   one fresh live occurrence proves the required postcondition
REPEATABLE         the same capability succeeds across the required repeated
                   occurrences with no code or tuning change between runs
STABLE             the current milestone's acceptance criteria hold over the
                   required operating window
```

### Invariants

```text
IMPLEMENTED      != WIRED
WIRED            != LIVE_PROVEN_ONCE
LIVE_PROVEN_ONCE != REPEATABLE
REPEATABLE       != STABLE
```

### What is and is not evidence

`docs/GOAL.md`, `docs/PRD.md`, `docs/BUILD_PLAN.md` and
`config/engineering_graph.yaml` define **intended behaviour and scope**. They
are not evidence that runtime behaviour is complete. A node marked
`implemented` in the graph is a statement of intent, not of reach.

Tests prove the code under test. They do **not** prove that the live
entrypoint calls that code, unless a structural or runtime wiring test
establishes that path — see `tests/test_live_tick_wiring.py`.

This is not a hypothetical. Two components in this repository passed their own
tests, were recorded as implemented, and were called by nothing:
`QueueIndicatorObservationProvider` was imported by no module, and
`--ocr-backend` defaulted to the PowerShell path while the comment beside that
branch said it was not for live ticks.

### Stating a claim

A completion claim states the highest status actually evidenced, and what
remains unevidenced. The words "done", "complete", "finished" and "all
passing" are not used for an objective whose acceptance criteria are not met.

Current runtime truth is tracked in `runtime-status.yaml`, which is committed
so the state is visible on GitHub while heavy raw evidence stays under the
gitignored `workspace/`. It records what has been verified, never what is
intended.

## Current vertical slice

The active product path is `GATHER_RESOURCE` on one character. Other missions remain separate graph branches and must not be treated as covered merely because shared harness infrastructure exists.
