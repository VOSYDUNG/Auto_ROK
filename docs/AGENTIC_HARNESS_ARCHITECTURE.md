# Auto_ROK Agentic Harness V1

## Purpose

Auto_ROK is a support-oriented Agentic OS for a mostly fixed visual environment.
The local GPT-OSS model is **not asked to invent gameplay logic, reason spatially about pixels, or plan long action chains**.

Its job is intentionally narrow:

> receive structured feedback from mission tools and select the next valid action.

The harness owns perception, UI grounding, execution, verification, timing, persistence, and the distilled rules learned from the human operator.

## Core model

```text
Mission Scheduler
      |
      v
Mission / Task
      |
      v
Harness Tool.observe()
      |
      +--> OCR / CV / visual grounding / memory / timers
      |
      v
Structured Tool Snapshot
(state + facts + targets + allowed_actions + feedback)
      |
      v
Local GPT-OSS Decision Selector
(choose one allowed action; no spatial reasoning required)
      |
      v
Policy / Preconditions
      |
      v
Harness Tool.execute(action)
      |
      v
Re-observe + Verify + Persist
      |
      +----> next decision
```

The model does not need to know screen coordinates. It should normally never receive raw `(x, y)` values.

## Mission -> Task -> Tool

### Mission

A mission is a user-level objective with a lifecycle and trigger, for example:

- `DAILY`
- `EVENT_COORDINATION`
- `ACCOUNT_MAINTENANCE`

A mission may contain multiple tasks and may remain active across game sessions.

### Task

A task is a concrete responsibility inside a mission. It has:

- trigger / due condition;
- known facts;
- completion condition;
- retry / recovery policy;
- persistent status.

Example of **user-trained knowledge**:

`DAILY -> CLAIM_ALLIANCE_TERRITORY_RSS`

The operator has explained that alliance-territory RSS accumulates and becomes full at about a 24-hour interval, therefore claiming it belongs to the daily mission. The exact timing/reset semantics remain training data and must not be guessed.

### Tool

A tool turns the visual game into a small deterministic interface.

Instead of asking GPT-OSS:

> Where should I click on this screenshot?

The tool should return something like:

```json
{
  "mission": "DAILY",
  "task": "CLAIM_ALLIANCE_TERRITORY_RSS",
  "state": "CITY",
  "facts": {
    "task_due": true,
    "last_success_known": true
  },
  "allowed_actions": [
    "OPEN_ALLIANCE_TERRITORY",
    "REOBSERVE",
    "STOP_TASK"
  ]
}
```

GPT-OSS only selects one allowed action. The harness resolves that symbolic action to the current visual target, performs it, then returns feedback.

## Visual grounding: coordinates are output, not knowledge

V0 used fixed coordinates because a better grounding mechanism was not yet available. V1 treats coordinates as ephemeral execution data.

```text
Screenshot
   |
   v
Perception
(OCR + template + color/shape + optional visual model)
   |
   v
Visual Scene Graph
   |
   +-- element_id
   +-- semantic label
   +-- bounding box
   +-- confidence
   +-- evidence source
   +-- frame_id
   |
   v
Target Handle
   |
   v
Executor clicks the resolved target
```

A target handle is bound to the frame from which it was detected. After UI transition, scroll, window resize, or uncertain movement, the handle expires and must be grounded again.

This is analogous to computer-use/browser-use systems: **capture -> ground -> act -> capture again**. The local decision model should not perform the grounding itself.

## Fast visual stack

Use the cheapest reliable detector first:

1. deterministic anchors / templates;
2. OCR text boxes;
3. color / contour / geometry detectors;
4. local visual grounding model when deterministic detection is insufficient;
5. human training for genuinely unknown UI/rules.

The result is normalized into the same scene-graph/target-handle contract regardless of detector source.

## Local GPT-OSS contract

GPT-OSS is a constrained decision selector, not an open-ended planner.

Input should contain only what is needed to choose the next action:

```json
{
  "mission": "...",
  "task": "...",
  "state": "...",
  "facts": {},
  "last_feedback": {},
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

No rationale is required in the hot path. If an action is not in `allowed_actions`, the runtime rejects it.

This lets a slow local model operate acceptably because:

- screenshots are not repeatedly interpreted by the LLM;
- known game rules are already distilled into tools/missions;
- the action space at each step is small;
- routine visual work stays inside the harness.

A deterministic selector may later replace GPT-OSS for tasks whose next action is fully fixed.

## Temporal insight layer

The harness must model **why a task becomes due**, not merely reproduce clicks.

Example pattern learned from the operator:

```text
resource accumulates over time
        -> has an effective/full interval
        -> collection has value when due
        -> task belongs to DAILY mission
        -> ledger stores last verified claim
        -> scheduler exposes task_due to GPT-OSS
```

The executor does not decide whether it is time to claim. The mission scheduler/tool computes that fact from trained rules + persistent memory.

## Information missions beyond built-in game support

The OS may create useful workflows that the game itself does not provide.

User-trained example:

```text
season/event day reaches the configured race-information point
        -> activate EVENT_COORDINATION mission
        -> open mail
        -> locate clan mail
        -> OCR/extract clan-selected event day
        -> validate extraction
        -> persist selected day as a fact
        -> scheduler activates the participation task on that day
```

The important abstraction is not the exact event name. It is:

```text
GAME INFORMATION SOURCE
        -> EXTRACT STRUCTURED FACT
        -> PERSIST
        -> CHANGE FUTURE MISSION SCHEDULE
```

This is a first-class Agentic OS capability.

## Runtime invariants

1. GPT-OSS chooses from tool-provided actions; it does not invent coordinates.
2. UI coordinates are ephemeral and generated by grounding for the current frame.
3. Every mutating action is followed by observation/verification.
4. A task is complete only after its completion condition is observed, not after a click was sent.
5. Timing rules are stored as trained knowledge + persistent task ledger.
6. Unknown game rules are training gaps, not invitations for the model to guess.
7. Long workflows are represented as missions/tasks, not long macros.

## Migration from V0

Reusable assets:

- `Avatar.py`: OCR/CV experiments, ROI transforms, visual feature work;
- `Human.py`: seed for human demonstration capture;
- `Mouse_key.py`: historical action primitives and coordinates;
- `Position.txt`: historical UI geometry;
- `LOG_WORKS.txt`: early decomposition of repeated activities.

Historical coordinates are useful as bootstrap/fallback calibration data, not as semantic game knowledge.

## V1 milestones

### M0 — Mission vocabulary + training
- identify missions;
- identify tasks inside each mission;
- record due/completion rules;
- record visual evidence and exceptions.

### M1 — Visual grounding
- bounded game-window capture;
- visual scene graph;
- OCR/CV target handles;
- target expiry after state transitions.

### M2 — Passive tool feedback
- tools expose state/facts/allowed actions;
- GPT-OSS selects next action;
- no autonomous execution yet.

### M3 — One verified daily task
- one low-risk task from `DAILY`;
- symbolic action -> target handle -> execution;
- post-action verifier;
- persistent ledger.

### M4 — Mission scheduler
- due rules;
- daily/idempotent behavior;
- cross-session resume;
- future tasks created from extracted game information.

### M5 — Local runtime
- constrained GPT-OSS action selector;
- bounded context;
- deterministic fallback for fully fixed paths;
- telemetry for decision/tool latency.

## Non-goals

- anti-cheat evasion;
- CAPTCHA bypass;
- process/memory injection;
- hiding automation from the game or operating system.
