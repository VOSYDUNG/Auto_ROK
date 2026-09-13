# Auto_ROK Agentic Harness V1

## Purpose

Auto_ROK is a support-oriented Agentic OS that operates a visually presented game through ordinary computer-use interaction.

The game is an **external UI environment**. The harness does not read or mutate hidden game state. It only:

- sees visible screen pixels;
- interprets those pixels with OCR/CV/visual grounding;
- acts through ordinary mouse and keyboard input;
- observes the visible result;
- stores its own memory derived from those observations and actions.

The local GPT-OSS model is not asked to invent gameplay logic, reason spatially about raw pixels, or construct long action chains. Its role is a bounded semantic decision service when the harness exposes more than one valid next action.

## Human-interface boundary

Authoritative boundary: `config/human_io_boundary.yaml`.

### Allowed sensing

- visible screen pixels only.

### Allowed actuation

- mouse;
- keyboard.

### Internal support that is not game sensing

- wall/monotonic clock for scheduling;
- harness-owned memory and task ledger;
- operator-trained knowledge;
- facts derived from prior visible observations.

### Outside the architecture

- process/game memory reads;
- process or DLL injection;
- private/internal game APIs;
- engine object access;
- packet sniffing/forging;
- hidden telemetry channels;
- anti-cheat interfaces/evasion.

The harness therefore behaves at the same interaction boundary as a human seated at the computer.

## Belief State, not World State

The harness never possesses authoritative internal game state.

It maintains a **Belief State**:

```text
BELIEF_STATE
├── ui.*
├── player.*
├── march.*
├── alliance.*
├── event.*
├── task.*
└── system.*
```

Every field must have provenance such as:

- visible OCR/CV evidence;
- a previously observed visible fact;
- operator-trained rule;
- official in-game guide knowledge;
- a deterministic derivation from those sources.

A belief may be stale, uncertain, or wrong. Confidence and provenance are therefore first-class data.

## Architecture is not a sequential pipeline

The runtime is event-driven/reactive. Multiple loops operate around a shared Belief State and task/memory stores.

```text
                              ┌─────────────────────┐
                              │      GPT-OSS        │
                              │ semantic selector   │
                              └─────────▲───────────┘
                                        │ only when
                                        │ selection is needed
                                        │
                    ┌───────────────────┴───────────────────┐
                    │                                       │
          ┌─────────▼─────────┐                   ┌─────────▼─────────┐
          │  MISSION CONTROL  │                   │ CAPABILITY/POLICY │
          │ due/priority/task │◄─────────────────►│ action eligibility │
          └─────────▲─────────┘                   └─────────▲─────────┘
                    │                                       │
                    └────────────────┬──────────────────────┘
                                     │ reads/writes
                                     ▼
                         ┌─────────────────────────┐
                         │      BELIEF STATE       │
                         │ + memory + task ledger  │
                         └──────▲─────────▲────────┘
                                │         │
                    observations│         │visible feedback
                                │         │
                      ┌─────────┘         └─────────┐
                      │                             │
             ┌────────▼─────────┐          ┌────────▼─────────┐
             │ VISUAL PERCEPTION│          │ HUMAN INPUT      │
             │ OCR/CV/grounding │          │ ACTUATION        │
             └────────▲─────────┘          │ mouse/keyboard   │
                      │                    └────────▲─────────┘
                      │ visible pixels              │ OS input
                      │                             │
                      └──────────────┬──────────────┘
                                     ▼
                           ┌──────────────────┐
                           │ GAME UI ENVIRONMENT│
                           └──────────────────┘
```

There is no privileged connection from Belief State to the game internals.

## Concurrent loops

### 1. Visual perception loop

```text
capture visible frame
→ detect/OCR/ground
→ update belief candidates
→ attach confidence/provenance
→ publish visible changes
```

This loop does not need to know which mission is active.

### 2. Mission/task loop

```text
read clock + memory + belief
→ determine READY/BLOCKED/WAITING/COMPLETE tasks
→ compute current task priorities
→ request eligible semantic actions
```

A mission may contain independent tasks rather than one fixed sequence.

### 3. Capability/policy loop

```text
trained task graph
+ current belief
+ role facts
+ operator policy
+ guide constraints
→ eligible actions
```

Game-supported capability does not automatically mean autonomous permission.

### 4. Decision loop

If the eligible action set has:

- `0` actions: wait/reobserve/block;
- `1` action: deterministic execution may proceed without GPT-OSS;
- `N > 1` meaningful actions: GPT-OSS may select among the exposed actions.

GPT-OSS is therefore a decision node, not the central controller.

### 5. Motor/feedback loop

```text
semantic action
→ shortcut or grounded target
→ mouse/keyboard input
→ visible environment changes
→ perception observes result
```

Success is defined by visible postconditions, not by "input was sent".

## Semantic Action Surface

The model should not normally see coordinates.

Resolution order:

```text
semantic action
  → native keyboard shortcut when available
  → current-frame visual target
  → unresolved/reobserve
```

Examples:

- `OPEN_MAIL` may resolve to `M`;
- `OPEN_ALLIANCE` may resolve to `O`;
- `OPEN_SEARCH` may resolve to `F`;
- a button inside a modal may require visual grounding.

## Visual grounding

Coordinates are transient motor-control output, not game knowledge.

```text
visible screenshot
→ OCR/template/color/visual model
→ semantic target
→ frame-scoped bbox
→ click/drag point
```

A target becomes invalid after conditions such as:

- UI transition;
- scroll;
- camera movement;
- window resize;
- insufficient confidence;
- any change that makes the old geometry unreliable.

This preserves human-like closed-loop operation: **look again before acting again when the scene has changed**.

## Missions and tasks

### Mission

A mission is an operator-level objective with lifecycle and triggers, for example:

- `DAILY`;
- `EVENT_COORDINATION`;
- `CHARACTER_MAINTENANCE`;
- `RESOURCE_GATHERING`.

### Task

A task contains:

- due condition;
- observable entry states;
- required facts;
- completion condition;
- retry/recovery policy;
- persistent status;
- allowed semantic actions.

Tasks may be paused/resumed when the visible UI diverges or an interrupting popup appears.

## Example: Daily Alliance Territory RSS

Operator-trained insight:

- Alliance Territory RSS accumulates over time;
- it is operationally worth claiming daily;
- the task belongs to `DAILY`.

The architecture stores the temporal insight separately from UI mechanics.

```text
clock/memory says task_due
      │
      ▼
DAILY task becomes READY
      │
      ▼
current belief determines which action is eligible
      │
      ├─ main game view → OPEN_ALLIANCE
      ├─ alliance home → OPEN_ALLIANCE_TERRITORY
      └─ territory + claim visible → CLAIM
```

Each action is resolved to keyboard/mouse and verified visually.

## Example: Event coordination from mail

This is a cross-feature OS workflow that the game does not provide directly.

```text
visible event information ─────┐
                               ├─► belief/memory facts
visible clan mail ─────────────┘
                                      │
                                      ▼
                            selected event day
                                      │
                                      ▼
                               future scheduler
```

The harness does not read hidden event state; it extracts visible information and turns it into future mission triggers.

## Knowledge provenance

Different knowledge types have different authorities.

For game mechanics:

```text
official in-game guide
> direct visible observation
> repeated operator observation
> operator explanation
> derived heuristic
```

For operator policy:

```text
operator instruction
> validated operator memory
> derived preference
```

A fact can be authoritative about a mechanic without granting autonomous permission to use that capability.

## Local GPT-OSS contract

Input:

```json
{
  "mission": "...",
  "task": "...",
  "belief_state": "...",
  "facts": {},
  "last_visible_feedback": {},
  "allowed_actions": []
}
```

Output:

```json
{
  "action": "ONE_ALLOWED_ACTION",
  "arguments": {}
}
```

The runtime rejects actions outside `allowed_actions`.

GPT-OSS should not require:

- raw screen coordinates;
- hidden game state;
- frame-by-frame spatial reasoning for known targets;
- rediscovery of trained game rules;
- long-horizon free-form gameplay planning.

## Runtime invariants

1. Game sensing is screen-pixel-only.
2. Game actuation is mouse/keyboard-only.
3. Belief State is inferred, never treated as privileged truth.
4. Every game fact must have visible/trained/derived provenance.
5. Coordinates are ephemeral motor data.
6. Visible scene changes invalidate stale target handles when appropriate.
7. A task completes only after a visible completion condition is observed.
8. GPT-OSS chooses only among eligible semantic actions.
9. Zero/one-action states do not require LLM inference.
10. Unknown rules remain training gaps rather than guesses.

## Migration from V0

Reusable V0 assets:

- `Avatar.py`: OCR/CV experiments and visual feature work;
- `Human.py`: seed for human demonstration/trajectory capture;
- `Mouse_key.py`: historical mouse/keyboard action primitives;
- `Position.txt`: historical geometry useful for calibration;
- `LOG_WORKS.txt`: early decomposition of visible game tasks.

The old code remains useful because it already worked at the visible-input boundary. V1 replaces brittle recognition/execution logic without changing that fundamental interaction philosophy.

## V1 milestones

### M0 — Knowledge + interaction boundary
- missions/tasks;
- official/operator knowledge provenance;
- Human Interface Boundary;
- visible-state vocabulary.

### M1 — Visual perception
- bounded screen capture;
- OCR/CV/grounding;
- Belief State updates;
- frame-scoped targets.

### M2 — Passive mission runtime
- task readiness;
- capability/policy filtering;
- allowed actions;
- no autonomous actuation required yet.

### M3 — Verified human-input task
- one low-risk daily task;
- semantic action resolution;
- mouse/keyboard only;
- visible postcondition verifier;
- persistent ledger.

### M4 — Scheduler + interruption/resume
- due rules;
- idempotency;
- pause/resume;
- cross-session memory;
- future tasks generated from visible information.

### M5 — Local GPT-OSS runtime
- constrained action selection;
- model invoked only when meaningful choice exists;
- telemetry for perception/tool/model latency.

## Non-goals

- reading game process memory;
- process/DLL injection;
- private game/internal APIs;
- packet inspection or manipulation;
- anti-cheat interaction/evasion;
- CAPTCHA bypass;
- hidden-state shortcuts that a normal user cannot perceive through the UI.
