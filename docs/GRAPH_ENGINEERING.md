# Graph Engineering protocol

Graph Engineering means agents build against an explicit dependency/evidence graph instead of treating the repository as a flat file set.

The machine-readable source is `config/engineering_graph.yaml`.

## Why this exists

A coding agent can locally produce correct code while globally reducing product value by:

- creating a second authority for a responsibility;
- building a module with no real producer/consumer;
- passing unit tests while leaving the actual end-to-end boundary open;
- solving an already-covered node while the real blocker is elsewhere;
- losing provenance between perception, action and verification;
- silently converting an unknown policy into a guessed rule.

The graph makes those failures visible before code is written.

## Graph layers

The active GATHER_RESOURCE graph is organized around six engineering layers:

```text
CONTRACT
  mission YAML / typed compiler
      |
PERCEPTION
  capture -> OCR -> projection -> semantic evidence -> state/facts
      |
DECISION
  adapter -> deterministic 0/1/N selector -> explicit policy gate
      |
EXECUTION
  MissionEngine -> MissionTool -> semantic surface -> screen mapping
      |
SAFETY
  interference guard -> ordinary mouse/keyboard input
      |
VERIFICATION + DURABILITY
  fresh observation -> typed completion -> atomic checkpoint -> resume
```

These are dependency layers, not permission to build sequentially. Independent graph branches can be assigned to parallel agents.

## Agent package = subgraph

A package is described by graph boundaries rather than only file names.

Example:

```text
owned node: resource_level_control
producer: RESOURCE_SEARCH_PANEL current-frame evidence
consumer: screen_mapping / MissionEngine transition
acceptance edge: requested level -> visible selected level on a fresh frame
blocker: B002
```

That package may touch several files, or only one. File count is not the unit of progress; closing a graph edge or falsifying a blocker is.

## Authority rule

Each responsibility has one canonical authority node.

Before adding a new abstraction, an agent must answer:

1. Which node owns this responsibility now?
2. Is the new component replacing that authority, adapting into it, or duplicating it?
3. What producer feeds it?
4. What consumer depends on it?
5. What evidence proves the edge works?

A duplicate authority is a design regression unless the graph explicitly records a migration/replacement.

## Evidence edges

For this project, an edge is not considered closed merely because objects can be instantiated.

Important edge classes require evidence:

- perception edge: current frame provenance and detector/semantic evidence;
- action edge: grounded target or trained native shortcut;
- host-input edge: foreground/window/geometry guard proof;
- transition edge: fresh post-action observation;
- completion edge: typed completion predicate, not executor assertion;
- persistence edge: atomic revision/occurrence identity and restart test;
- gameplay-policy edge: explicit operator policy, never inference from convenience.

## Build loop

Every agent follows this loop:

```text
1. LOCATE
   find the owned node and blocker

2. TRACE
   producer -> owned node -> consumer -> acceptance gate

3. FALSIFY
   define what evidence would prove the blocker is actually closed

4. BUILD
   implement the smallest coherent graph delta

5. VERIFY
   focused tests + integration edge evidence

6. UPDATE GRAPH
   status / evidence / blocker / edge changes

7. HANDOFF
   changed_nodes + graph_delta + next_unblocked_nodes
```

If step 2 cannot be drawn, the agent is not ready to code.

## Parallel-agent rule

Parallel work is safe when agents own disjoint subgraphs.

Good split:

```text
Agent A: CITY/WORLD perception -> state classifier
Agent B: resource-level typed control -> screen mapping
Agent C: fixture/replay evidence -> live acceptance
```

Bad split:

```text
Agent A rewrites MissionEngine
Agent B also changes MissionEngine
Agent C creates a second runtime to avoid the conflict
```

Cross-subgraph work is allowed only when the integration edge is named in advance.

## What counts as full coverage

"Covered" has three different meanings and they must not be mixed:

- **code covered**: a canonical implementation exists and focused tests support it;
- **integration covered**: producer/consumer edges are exercised together;
- **live covered**: real game evidence satisfies the end-to-end acceptance path.

The current GATHER_RESOURCE branch has broad code/integration coverage but is **not live-complete**. The authoritative missing nodes are recorded in the graph:

- `city_world_visual_detector`;
- `resource_level_control`;
- `troop_selection_policy` decision;
- `live_replay_evidence`.

Shared harness infrastructure also does not imply end-to-end coverage of `SWITCH_CHARACTER`, `CLAIM_ALLIANCE_TERRITORY_RSS`, `BARBARIAN_FORT_RALLY`, event coordination, scheduler, or GPT-OSS decision-provider branches.

## CI gate

Run:

```bash
python scripts/validate_engineering_graph.py
```

The validator checks node/edge/blocker referential integrity, canonical statuses, repository paths for implemented nodes, evidence paths, and declared coverage values. CI runs this check alongside focused runtime tests.
