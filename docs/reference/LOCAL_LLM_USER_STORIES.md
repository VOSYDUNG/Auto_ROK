# Local LLM user stories — GATHER_RESOURCE

This document defines the user story of the local model worker.  It does not
move perception, game knowledge, coordinate grounding, policy, actuation or
verification into the model.  Those remain harness responsibilities.

## US-LLM-01 — choose only an existing bounded action

**As** the local Qwen/GPT-OSS decision worker, **I want** one compact,
frame-bound semantic snapshot, **so that** I can choose one already-valid
action when the deterministic selector reports more than one meaningful
candidate.

The snapshot contains:

- mission/task identity, current frame ID and symbolic state;
- allowlisted visible facts such as queue counts, selected level, detector
  status and explicit policy evidence;
- semantic candidate action IDs, target IDs and bounded non-geometric
  arguments;
- the previous visible feedback, when one exists.

The model does not receive raw pixels, OCR blobs, desktop/client rectangles,
target bounding boxes, file paths, HWND/PID values, process memory or arbitrary
tools.  The selector adapter projects scene facts through an explicit
allowlist and treats model output as untrusted data.

## US-LLM-02 — abstain on ambiguity or failure

**As** the decision worker, **I want** to return no choice when the candidates
or evidence are unsafe, **so that** the harness reobserves or asks instead of
guessing.

Acceptance:

1. The response is one JSON object with `action_id` and optional `target_id`.
2. The pair must match exactly one candidate created by the harness.
3. An invented action, target, coordinate, tool call or malformed response is
   rejected and cannot reach the action surface.
4. A timeout, unavailable loopback endpoint or invalid response fails closed;
   it never falls back to a cloud model.
5. If a category decision has no explicit semantic resource intent, the
   harness abstains before asking the local endpoint; the model cannot turn an
   under-specified candidate set into a guessed category.

## US-LLM-03 — let the harness own the expected result

**As** the harness, **I want** to compile the postcondition and perform fresh
visible verification, **so that** a model selection is never treated as a
successful game action.

The local worker chooses only.  The harness resolves the semantic action to a
native shortcut or a current-frame target, checks the occurrence-bound policy
and interference guard, emits ordinary input only when explicitly armed, then
captures a fresh frame and verifies the declared transition.  `DISPATCHED` is
not `VERIFIED`.

## Current experiment boundary

The CPU-only live experiment has exercised US-LLM-01's upstream signal path:
the current 1366×768 client frame is classified as `CITY_VIEW`, one semantic
`TOGGLE_CITY_MAP` candidate is produced, and the unarmed guard blocks input.
The local endpoint is a separate canary: it must be available on loopback and
run through the bounded adapter before any claim about GPT-OSS capability.

The current GATHER slice therefore uses the deterministic fast path for a
single candidate.  The local model is not required for that state and should
be invoked only after a real `NEEDS_DECISION` branch is grounded.

The no-intent replay probe is a safety check, not a model-accuracy score: an
under-specified resource-category set must be stopped by the harness before a
local request.  Any model guess in that probe is recorded as unsafe rather
than rewarded as a correct category.

## Holdout gate

The model decision edge is not promoted from the 16-case screening matrix.
`config/local_llm_holdout_cases.json` contains 12 cases over three capture
frames that are disjoint from that matrix.  Run
`scripts/validate_local_llm_holdout.py` before a model run; it verifies capture
and OCR hashes plus frame disjointness.  The 2026-09-18 CPU-only loopback run
achieved 12/12 bounded choices, `input_emitted_any=false`, and complete usage
telemetry; the aggregate is now `measured_pending_reviewer`.  Independent
reviewer acceptance and a live postcondition are still required before PRD R1b
promotion.
