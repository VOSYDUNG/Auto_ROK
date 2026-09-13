# Auto_ROK — Agentic Harness branch

Branch objective: evolve the old proof-of-concept into a state-aware support runtime without rewriting useful CV/OCR experiments prematurely.

## Current stage: M0 / training-first

No gameplay skill is autonomous yet.

Implemented foundation:

- typed observation/state/action contracts;
- observe -> classify -> plan -> policy -> execute -> verify runtime;
- knowledge-backed conservative policy gate;
- game-rule training schema;
- architecture separating deterministic fast path from local GPT-OSS semantic fallback.

## Human -> Harness distillation loop

For each game rule/task:

1. Human explains the goal and why it matters.
2. Record entry state(s) and visible evidence.
3. Record valid actions and invalid/risky actions.
4. Record the expected observable result.
5. Record exceptions and reputation/account-risk cases.
6. Collect representative screenshots.
7. Implement passive detector/classifier.
8. Validate detector offline.
9. Implement one bounded skill.
10. Promote the rule from `training` to `validated` only after repeated successful verification.

## Local GPT-OSS role

GPT-OSS is a slow semantic support layer, not the frame-by-frame controller.

Use it for:

- unknown screen diagnosis;
- conflicting OCR/CV evidence;
- novel popup interpretation;
- recovery suggestions after deterministic recovery is exhausted;
- proposing new rules for later human validation.

Do not use it to bypass the policy gate.

## Next code after game training

The next commit should be driven by real game rules and screenshots, not assumptions. Expected modules:

- `perception/capture.py`
- `perception/ocr.py`
- `perception/anchors.py`
- `game/states.py`
- `skills/<first_validated_skill>.py`
- `telemetry/event_store.py`

The first skill should be low-risk, observable end-to-end, and idempotent.
