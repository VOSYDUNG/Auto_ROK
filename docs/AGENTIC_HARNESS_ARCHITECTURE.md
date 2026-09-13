# Auto_ROK Agentic Harness V1

## Purpose

Auto_ROK V1 is a support-oriented agentic runtime for a visually operated game. The harness must understand observable game state before acting. It is not a blind coordinate macro and it must not depend on an LLM for every frame.

The design goal is:

> distill repeated game knowledge into fast deterministic skills; reserve the local LLM for ambiguous states, novel situations, and recovery planning.

## Runtime layers

1. **Capture** — acquire a bounded game-window screenshot.
2. **Perception** — OCR, color/shape detection, templates, anchors, counters.
3. **State** — convert raw detections into a typed `GameState` with confidence and evidence.
4. **Knowledge** — game rules, invariants, preconditions, postconditions, cooldowns, priorities, and reputation-sensitive constraints learned during training.
5. **Planner** — choose a goal/action from the known state.
6. **Policy gate** — reject actions whose preconditions are not proven or which violate a learned rule.
7. **Executor** — mouse/keyboard action primitives.
8. **Verifier** — observe again and prove the expected postcondition.
9. **Recovery** — bounded retry, backtrack, or ask the semantic fallback for a diagnosis.
10. **Memory/telemetry** — persist task outcomes, evidence, failures, and screenshots.

## Fast path vs semantic path

```text
screenshot
   -> deterministic perception
   -> known state?
       yes -> rule/skill planner -> execute -> verify
       no  -> semantic fallback (local GPT-OSS) -> structured proposal
                    -> policy gate -> execute only if accepted -> verify
```

The semantic model is therefore **not in the hot loop**. Known states and routine actions should never wait for local-model inference.

## Core invariant

No gameplay action may be executed only because a coordinate exists.

An action requires:

- an observed state;
- evidence supporting that state;
- action preconditions satisfied;
- a bounded risk classification;
- a verifiable postcondition.

If confidence is insufficient, the runtime must return `WAIT`, `REOBSERVE`, `RECOVER`, or `NEED_SEMANTIC_REVIEW` rather than guessing.

## Training-first rule capture

Before implementing a gameplay skill, record the rule in `config/training_schema.yaml` with:

- human description;
- trigger/goal;
- observable preconditions;
- allowed action(s);
- forbidden action(s);
- expected postconditions;
- exception cases;
- reputation / account-loss risk;
- screenshots or other evidence needed for validation.

Only after a rule is validated should it become a deterministic skill.

## Migration from V0

Reusable V0 assets:

- `Avatar.py`: OCR/CV experiments and ROI-to-screen coordinate conversion;
- `Human.py`: demonstration capture concept;
- `Mouse_key.py`: action primitives and historical screen coordinates;
- `LOG_WORKS.txt`: early decomposition of game perception and account-switching tasks.

V0 coordinates are treated as **historical hints**, not as authoritative selectors.

## V1 milestones

### M0 — Knowledge capture
- game-state vocabulary
- task vocabulary
- rules/invariants
- reputation-sensitive cases
- screenshot corpus

### M1 — Passive observer
- game-window capture
- OCR/UI element extraction
- state classification
- zero autonomous clicks

### M2 — Verified single skill
- one trained low-risk skill
- precondition gate
- postcondition verifier
- bounded retries

### M3 — Daily scheduler
- persistent per-character task state
- idempotency
- resume after crash/restart

### M4 — Local GPT-OSS fallback
- structured state diagnosis only on unknown/ambiguous states
- proposal must pass the same policy gate as deterministic planners

## Non-goals

- anti-cheat evasion;
- CAPTCHA bypass;
- process/memory injection;
- hiding automation from the game or operating system.
