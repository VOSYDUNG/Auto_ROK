# G002 — Plan / Design brief / SRS / Spec / User stories

> **Current scope override (2026-09-18):** Auto_ROK runs directly on one
> physical Windows machine with one user. Docker, VM and Hyper-V are not
> product prerequisites or acceptance targets. The guest references below are
> historical feasibility material only; the active input gate is
> `docs/HOST_INPUT_ISOLATION.md`.

Source of truth: GOAL.md + PRD.md. This is an execution handoff, not evidence that later stages are implemented. Root/user decide scope and acceptance; agents implement. Max2 children; local1 slot; each package at most2 diagnosed repair attempts.

## Design brief

First interface is a Vietnamese CLI assistant: receive a task and image, describe evidence, show uncertainty and propose next steps; save the conversation as a session so later questions can refer to the same observation with its known age. Future localhost chat adds image overlays and pause/status controls. Never present “ready for Computer Use” when only OCR/model transport is ready.

The main distinction shown to the user is observation vs suggestion vs verified action. An OCR word is not a game object; a valid JSON proposal is not a successful workflow. If game state cannot be identified, ask for a fresh target image or clarification instead of inventing a click.

## SRS contracts

| Contract | Required semantics |
|---|---|
| Task | goal, source, target identity, allowed workflow, deadline/budgets, permission version |
| Observation | frame ID/hash, source path, captured_at nullable, ingested_at, dimensions, OCR text+bbox, detector observations, confidence nullable |
| Model allocation | requested/effective model/effort, context cap, endpoint capability evidence, autonomy, permission scope |
| Proposal | answer/ask/observe/action intent, rationale, evidence IDs, expected postcondition; schema valid does not grant execution |
| Action | direct-host binding, observation version, allowlist, expiry, idempotency key, pre/post evidence |
| Session | ordered events, task/session/run IDs, failures, bounded history, usage fields nullable, independent verification result |

Images and source content cannot set policy or invoke tools. Direct-host control must reject unknown session, stale/ambiguous frames, unsupported operations and cancellation. Reobserving a disk image must not refresh its original capture time.

## Implementation packages

**P1 — OCR/observer.** Builder owns src/rok_lite.py, scripts/rok_lite.py, scripts/windows_ocr.ps1, config/rok-lite.json and focused tests. Output: actual native OCR image read, local reasoning request with explicit schema, conversational answer/ask mode, bounded retry/session and telemetry. No guest input. Verify native OCR on real input when available; synthetic smoke separately labelled. Reviewer checks failure paths and honest readiness.

**P2 — DSH extraction.** Official source is pinned at c291e7961a515f6d7af9304e7fd1d257929aef26. Builder maps retained session/loop/token mechanisms to source paths and actual implementation. Root preserves provenance/license/hash. Acceptance: distinguish source download, ported mechanism, linked SDK and unimplemented features. No runtime npx dependency or arbitrary plugin installation in lite.

**P3 — Local canary.** After P1 review, builder runs one no-action observation session against the existing loopback endpoint, with budget/reasoning configuration and full failure record. Capture input class: ROK real / non-ROK real / synthetic. Only ROK real contributes to R1 acceptance. No account quota attribution from shared snapshots.

**P4 — Windows guest feasibility (historical, out of product scope).** Retained only as archived feasibility material. It must not trigger host feature changes, reboot, VM setup or a product gate. The active builder path is direct-host capture/control with `windows_host_direct` evidence.

**P5 — Workflow.** Builder replaces legacy fixed-coordinate assumptions with frame-bound state machine for one resource workflow. Reuse algorithm intent, not import-time legacy input code. Stages detect → choose → act → verify, unknown state → ask/recover. Reviewer checks postconditions and restart/cancel. Account switching is separate scope after one-character workflow acceptance.

**P6 — Endurance/economics.** Builder runs permitted batches only after P5. Reviewer compares accepted workflow/hour, local/cloud token totals without double count, repair/escalation and user minutes, then 1h/15h resource contention. Energy/money remain null until measured. Root approves capability promotion only with evidence; old allocation retained for rollback.

## User stories and acceptance examples

The local-worker-specific contract is defined in
[`LOCAL_LLM_USER_STORIES.md`](LOCAL_LLM_USER_STORIES.md).  These stories keep
the model as a bounded decision edge while the harness owns evidence,
grounding, policy, input and verification.

- As owner, I ask what is visible in an image: answer cites OCR/vision evidence and distinguishes uncertainty; non-ROK image is not fabricated into a ROK screen.
- As owner, I ask a follow-up: session refers to the same frame, does not invent fresher capture; missing target blocks action.
- As desktop user, I hand the foreground to ROK for one bounded action window: no unapproved pointer movement, focus change or injected keys are accepted, and the harness stops on stale or ambiguous evidence.
- As operator, I cancel and later resume: no new action after cancel, fresh observation before resume, no duplicate action from an ambiguous prior result.
- As budget owner, I see failed runs and reasoning tokens where provided: no invented zero costs, no cloud call on timeout without allocated permission.

## Production gate

PRD R1–R4 and reviewer evidence must pass before calling tier1 production-ready. A missing direct-host trace or ROK image corpus means useful observer prototype only. Robotics remains tier2 after tier1 acceptance.
# Superseded scope note

The historical G002 feasibility plan below mentions a Windows guest. The
current Auto_ROK product scope is direct execution on one physical Windows
machine with one user; Docker/VM/Hyper-V are not prerequisites or acceptance
targets. Use `docs/HOST_INPUT_ISOLATION.md` and the direct-host R2 artifacts for
the current action gate.
