# Auto_ROK — Agentic Harness branch

Branch objective: evolve the old proof-of-concept into a mission-driven support runtime that controls the game strictly through **human-visible pixels + ordinary mouse/keyboard input**.

## Current stage: M0 / training-first

No gameplay mission is autonomous yet.

The key architecture rules are now:

> The game is an external visual UI environment. The harness does not read hidden game state or modify the game internally.

> GPT-OSS does not invent how to play and does not visually hunt for coordinates. The harness infers a Belief State from visible pixels, exposes bounded semantic actions, and GPT-OSS selects only when a meaningful choice exists.

## Human-interface-only boundary

Allowed game sensing:

- visible screen pixels.

Allowed game actuation:

- mouse;
- keyboard.

Explicitly outside the architecture:

- process/game memory reads;
- process or DLL injection;
- game-internal/private APIs;
- engine objects;
- packet sniffing/forging;
- hidden telemetry;
- anti-cheat interfaces/evasion.

The authoritative policy is in `config/human_io_boundary.yaml`, with typed contracts in `harness/human_io.py`.

## Belief State instead of World State

The harness never claims to know the game's true internal state. It keeps a **Belief State** inferred from:

- OCR/CV/visual grounding over visible frames;
- previous visible observations;
- operator-trained rules;
- official in-game guide knowledge;
- harness-owned memory derived from those sources.

Every belief should carry confidence/provenance where useful.

## Runtime is reactive, not one linear pipeline

Several loops cooperate around Belief State, task memory, and policy:

```text
Visual Perception ─────┐
                       │
Scheduler/Missions ────┼──► Belief + Memory + Task Ledger
                       │             ▲
Capability/Policy ─────┘             │
                                     │
GPT-OSS (only if needed) ─► semantic action
                                     │
                                     ▼
                         Human Input Actuation
                         mouse / keyboard only
                                     │
                                     ▼
                            visible game UI
                                     │
                                     └──► Visual Perception
```

A state with one valid action does not need GPT-OSS. A state with no valid action waits/reobserves. GPT-OSS is used only when a bounded selection is genuinely needed.

## Why the old V0 still matters

The original code already contains useful discoveries at the same human-interface boundary:

- EasyOCR and OpenCV experiments;
- character-list and current-character detection;
- Territory text detection;
- native keyboard actions such as `F`, `O`, `V`, and `Space`;
- mouse/keyboard trajectory capture experiments.

The supplied Settings screenshots confirm that several historical keys were native semantic shortcuts rather than arbitrary macro constants. V1 promotes them into a shortcut-first action surface.

## Implemented foundation

- strict human-interface-only contract;
- reactive mission/task runtime with constrained action selection;
- typed visual observation/action contracts;
- frame-scoped visual scene graph;
- semantic action resolver with native-shortcut-first policy;
- capability gate and operator policy separation;
- game-rule / mission training schema with provenance;
- trained UI-state vocabulary from operator screenshots;
- trained shortcut map from Settings > Controls;
- official Gameplay Guide knowledge layer;
- operator-training knowledge for Daily, Event Coordination, character switching, and resource gathering patterns.

## Human → Harness distillation loop

For each mission/task:

1. Human explains **why** the task exists and how they think about it.
2. Record durable game/business insight separately from UI mechanics.
3. Record visible entry state(s), evidence, and confidence.
4. Record semantic actions valid from that belief state.
5. Prefer a native shortcut when it expresses the semantic action directly.
6. Otherwise ground a visible target in the current frame.
7. Perform one bounded mouse/keyboard action.
8. Reobserve the visible result.
9. Update Belief State and persistent task memory.
10. Promote uncertain rules only after validation.

## Local GPT-OSS role

GPT-OSS is a **constrained decision selector**, not a central brain.

It may receive:

- current mission/task;
- Belief State;
- visible/memory facts;
- last visible feedback;
- allowed semantic actions.

It returns:

- one allowed action id;
- optional bounded arguments.

It should not require:

- raw screen coordinates;
- hidden game state;
- frame-by-frame visual reasoning for known targets;
- long-horizon gameplay planning;
- rediscovery of known game rules.

## Visual grounding rule

Coordinates are motor-control output, not knowledge.

```text
semantic action
  → native shortcut when available
  → semantic visual target in current frame
  → mouse/keyboard action
  → reobserve visible feedback
```

Target geometry expires when the visible scene changes enough to make it unreliable.

## Trained mission examples so far

### DAILY

`CLAIM_ALLIANCE_TERRITORY_RSS` belongs to Daily because the operator reports that Territory RSS accumulates over time and is operationally worth claiming each day. The temporal insight is stored separately from the visual path.

### EVENT_COORDINATION

Visible event information plus visible clan mail can be converted into structured facts and future schedules without any hidden game integration.

### SWITCH_CHARACTER

Select another visible character card → confirm `YES` → wait until the normal main-game shell is visibly back → complete.

### GATHER_RESOURCE

The trained visible flow is Search → resource category/level → node detail → Gather → New Troop → March, with queue-count change used as visible completion evidence.

## Next code

Priority is to build reliable **visual perception + human-input execution**, not additional hidden integrations or blind click sequences:

- bounded game-window capture;
- OCR/template/CV target detectors;
- Belief State updater with confidence/provenance;
- verified target-handle execution;
- visible postcondition checks;
- scheduler/task ledger;
- local GPT-OSS selector only after the deterministic tool surface is stable.
