# Auto_ROK — Agentic Harness branch

Branch objective: evolve the old proof-of-concept into a mission-driven support runtime that turns a fixed game environment into structured tools for a local GPT-OSS decision model.

## Current stage: M0 / training-first

No gameplay mission is autonomous yet.

The key design correction is:

> GPT-OSS does not invent how to play and does not visually hunt for coordinates. The harness observes the game, exposes a structured state plus a bounded action set, and GPT-OSS selects the next semantic action.

```text
Mission / Task
    ↓
Harness observe
    ↓
state + facts + allowed_actions + last_feedback
    ↓
GPT-OSS: select one allowed action
    ↓
Semantic Action Surface
    ├─ native shortcut when available
    └─ current-frame visual target when needed
    ↓
OS input
    ↓
reobserve + feedback
```

## Why the old V0 still matters

The original code already contains useful domain discoveries:

- EasyOCR and OpenCV experiments;
- character-list and current-character detection;
- Territory text detection;
- game-native keyboard actions such as `F`, `O`, `V`, and `Space`;
- mouse/keyboard trajectory capture experiments.

The supplied in-game Settings screenshots now confirm that several historical keys were native semantic shortcuts, not arbitrary macro constants. V1 therefore promotes them into a shortcut-first action surface rather than discarding them.

## Implemented foundation

- mission/task runtime with constrained action selection;
- typed observation/state/action contracts;
- frame-scoped visual scene graph;
- semantic action resolver with native-shortcut-first policy;
- game-rule / mission training schema;
- trained UI-state vocabulary from operator screenshots;
- trained shortcut map from Settings > Controls;
- operator-training knowledge for Daily and Event Coordination mission patterns;
- conservative rule/policy layer for actions not yet trained.

## Human -> Harness distillation loop

For each mission/task:

1. Human explains **why** the task exists and how they think about it.
2. Record the durable game/business insight separately from UI mechanics.
3. Record observable entry state(s) and facts.
4. Record the semantic actions that are valid at that state.
5. Prefer a native game shortcut when it represents the semantic action directly.
6. Otherwise ground a visual target in the current frame.
7. Execute one bounded action.
8. Reobserve and return structured feedback.
9. Persist task/memory facts that matter across runs.
10. Promote uncertain rules only after repeated observation/validation.

## Local GPT-OSS role

GPT-OSS is a **constrained decision selector**.

It receives:

- current mission;
- current task;
- symbolic state;
- structured facts;
- last tool feedback;
- allowed semantic actions.

It returns:

- one action id;
- optional bounded arguments.

It should not require:

- raw screen coordinates;
- frame-by-frame visual reasoning for known targets;
- long-horizon gameplay planning;
- rediscovering known game rules every day.

Unknown actions are rejected by the runtime rather than executed speculatively.

## Visual grounding rule

Coordinates are execution data, not knowledge.

A visual target belongs to one captured frame. After a UI transition, scroll, resize, or other invalidating change, the target must be re-grounded before use.

Resolution order:

```text
semantic action
  → native shortcut
  → semantic visual target
  → reobserve / unresolved
```

## Mission examples learned so far

### DAILY

`CLAIM_ALLIANCE_TERRITORY_RSS` belongs to the Daily mission because the operator reports that the reward accumulates and is operationally full at roughly 24 hours. The important knowledge is the temporal rule; the exact claim-screen path is still being trained.

### EVENT_COORDINATION

Some event participation decisions require combining event UI facts with clan communication. A mission may therefore:

```text
inspect event
→ read clan mail
→ extract clan-selected participation day
→ persist fact
→ schedule later participation task
```

That cross-feature workflow is an Agentic-OS capability layered above what the game itself exposes.

## Next training/code

Priority is no longer to add more blind `click()` sequences. The next useful training batches are:

- Alliance/Territory claim path and its success evidence;
- Mail / clan-mail navigation and message structure;
- Event list/calendar semantics;
- Search/resource workflow and march-state feedback;
- character switching transitions and loading completion evidence.

Only after those states/actions are trained should the corresponding mission tools become executable.
