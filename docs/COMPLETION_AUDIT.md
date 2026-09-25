# Auto_ROK completion audit

Updated 2026-09-24 (Asia/Ho_Chi_Minh). This audit maps the historical G1–G6
gates to their bounded evidence and identifies what FIRST DONE still requires.
It is evidence-led: `PASS` means the named artifact
proves the exact claim, `PARTIAL` means a promotion or scope edge remains, and
`BLOCKED` means the evidence is insufficient for the next irreversible step.
The G1–G5 pass entries below describe September 18–19 artifacts and their
bounded occurrences. They do not establish readiness of the currently open
game window. The offline audit computed on September 22 at HEAD `7855c616`
still reports G6 blocked. The current FIRST DONE five-march objective remains
`UNIMPLEMENTED` in `runtime-status.yaml`; daily continuity is a later milestone.

FIRST DONE now means one character autonomously dispatching five farm marches
under one startup job authorization, preserving the commander pair auto-filled
by each fresh New Troop screen, and verifying queue 0→5/5. Return/refill, buff continuity and
24-hour operation are later milestones. This is a product
acceptance target in [GOAL](GOAL.md) and [PRD](PRD.md), not a claim established
by the historical gate artifacts below.

## Scope invariants

- Product target: one physical Windows host, one signed-in user and one visible
  ROK client; Docker, VM, Hyper-V, process memory and GPU execution are out of
  scope.
- Active vertical slice: one-character `GATHER_RESOURCE`.
- The harness owns capture, OCR/CV, state, policy, grounding, input guard,
  checkpoint, verification and evidence. The local model can only select one
  already-grounded `ActionChoice` or abstain as `NEEDS_DECISION`.
- A dispatch receipt is never completion. Completion requires a fresh visible
  Queue-used increase bound to the same character and occurrence.

## Requirement audit

| Requirement | Status | Authoritative evidence | Remaining boundary |
|---|---|---|---|
| Field reconnaissance before E2E | PARTIAL | `config/game_field_reconnaissance_plan.json`, `docs/GAME_FIELD_RECONNAISSANCE.md`, `workspace/evidence/recon/recon-goal-20260919-02/index.json` | The safe pass captures CITY_VIEW ↔ WORLD_MAP → SEARCH → node detail → troop drawer → safe close; launch/login, march-confirmation and recovery states remain explicitly `not_observed`. |
| PRD → design brief → local-LLM user story | PASS | `docs/reference/LOCAL_HARNESS_PRD.md`, `docs/AGENTIC_HARNESS_ARCHITECTURE.md`, `docs/reference/LOCAL_LLM_USER_STORIES.md` | PRD R1b promotion still needs independent reviewer acceptance. |
| State/mission matrix for GATHER and planned branches | PASS / PARTIAL | `docs/GAME_STATE_MISSION_MATRIX.md`, `config/mission_flows.yaml`, `tests/test_game_state_mission_matrix.py` | Non-GATHER branches remain training-only or not-covered by design. |
| Fixed CPU ROI and coordinate/performance map | PASS | `config/cpu_rois.yaml`, `docs/CPU_ROI.md`, `config/resource_level_profile.json`, `tests/test_resource_level_control.py` | Trained geometry is valid only for the 1366×768 profile and is never permission to click. |
| Capture, OCR and state projection on CPU/RAM | PASS / PARTIAL | `workspace/evidence/corpus/ocr-quality-rapidocr-overlay-20260919-independent.json`, `workspace/evidence/corpus/cpu-observation-corpus-rapidocr-overlay-20260919-independent.json`, `workspace/evidence/cpu/live-followup-20260918-04.json` | Windows OCR remains canonical; optional RapidOCR runtime promotion still needs a fresh live remeasurement. |
| Candidate/action surface and deterministic policy | PASS | `config/mission_flows.yaml`, `harness/state_adapter.py`, `harness/mission_engine.py`, `tests/test_gather_runtime_contracts.py`, `tests/test_typed_action_contracts.py` | Unknown policy remains `NEEDS_DECISION`; no branch is inferred. |
| Occurrence-bound B003 approval | PASS for 2026-09-19 occurrence | `workspace/evidence/gather/approvals/gather-goal-20260919-04.json`, `workspace/evidence/gather/R3_PREFLIGHT-gather-goal-20260919-04-final.json` | Historical benchmark/R3 path only; it is not a per-march approval requirement for FIRST DONE. |
| Direct-host input isolation | PASS for 2026-09-19 occurrence | `workspace/evidence/host/gather-goal-20260919-04-20260919T031742734674Z-00.json` | Only the bounded foreground action window is covered; no unattended desktop claim. The current audit includes the trace and lists its derived assessment sidecar only if that file exists. |
| Checkpoint, cancel, resume and tamper blocking | PASS offline | `workspace/evidence/recovery/recovery-matrix-20260919-02.json`, `tests/test_mission_runner.py`, `tests/test_mission_ledger.py` | Matrix is contract-only and intentionally emits no live input. |
| Immutable/append-only runtime evidence | PASS | `harness/gather_replay_evidence.py`, `tests/test_gather_replay_evidence.py`, `scripts/validate_gather_replay.py` | Evidence is append-only; timestamp collisions fail closed. |
| One live GATHER postcondition | PASS for 2026-09-19 bounded occurrence | `workspace/evidence/gather/gather-596d20bfddd42eb077af/revision-000013-1789787875616850100.json`, `workspace/evidence/audit/goal-readiness-latest.json` | After-state may be `UNKNOWN_STATE`; queue provenance (`1/5 → 2/5`) is the accepted historical completion fact. |
| Local-LLM holdout and 80/20 boundary | PASS measured / PARTIAL promotion | `workspace/evidence/local_llm/needs-decision-gpt-oss-holdout-20260918.json`, `tests/test_local_llm_selector.py`, `config/local-llm.json` | 12/12 bounded choices and zero input; production promotion remains disabled pending review. |
| R3 repetition threshold | BLOCKED | `config/r3_registered_runs.json`, `workspace/evidence/gather/r3-repetition-latest.json` | 2/10 registered and 2/9 minimum successes; 8 additional live occurrences are required. |
| Explicit authorization for additional live runs | BLOCKED / execution gate built | `harness/r3_endurance_authorization.py`, `scripts/run_elevated_gather.py`, `tests/test_r3_endurance_authorization.py`, `scripts/audit_goal_readiness.py` | `workspace/evidence/gather/R3_ENDURANCE_AUTHORIZATION.json` is intentionally absent until the operator authorizes it; no live R3 run has been started by this build. |
| Endurance / longer-run promotion | DEFERRED | `runtime-status.yaml`, G6 in `workspace/evidence/audit/goal-readiness-latest.json` | Must not start before R3 and explicit authorization. |

## FIRST DONE evidence gap

This map links the new product contract to the evidence owner without copying
capability statuses into a second current-state table. The precise level and
limitations of measured capabilities remain in [runtime-status](../runtime-status.yaml).

| Required edge | Evidence owner and required demonstration |
|---|---|
| Fresh New Troop → game-populated formation → March | [F1-C formation](../workspace/agents/f1c-formation-fact/tho_dung/HANDOFF.md) is wired offline from current-frame OCR/pixels and four positive archive frames; no real empty formation negative or live job yet. Harness must not send commander-selection input. Commander names and the game’s internal ranking are not separate acceptance gates. |
| Startup job authorization → guarded automatic marches | PRD F06, SRS `MIS-FD-005`, and [SESSION_AUTHORITY](SESSION_AUTHORITY.md) define one local GATHER job and one operator confirmation of the open character bound to job/frame/client/time, with no approval per march. The offline `create_gather_job.py` command issues one non-overwriting artifact from the compiled catalog plus a separate non-authoritative launch spec. [F4-A1](../workspace/agents/f4a-startup-attestation/root/VALIDATION.md) implements one per-job character attestation artifact with native capture and sourced queue 0/5 checks, but the driver/tick does not consume it and no real startup artifact has been issued. F1-B/C wired the guard and bound client offline. Historical G4/B003 only covers its named occurrence. |
| Fresh queue observation → five verified transitions → 5/5 | [F2-A journal](../workspace/agents/f2a-verification-journal/tho_dung/HANDOFF.md) resolved the three [review](../workspace/agents/f2a-verification-journal/kiem_luat/HANDOFF.md) findings and is WIRED offline; ROOT's full suite passed. The [Q0 trainer](../workspace/agents/q0-training-safety/root/VALIDATION.md) now accepts native capture metadata and verifies an operator-labelled candidate before an atomic profile update, at IMPLEMENTED offline. It did not train `0`: no supported archived 0/5 march-queue frame exists, and the older 5/5 occurrence includes manual intervention. A new autonomous job must show 0→1→2→3→4→5 for the same character. |
| One startup job → five autonomous occurrences | [F2-B coordinator](../workspace/agents/f2b-five-march/tho_dung/HANDOFF.md) is WIRED offline as a caller-driven one-tick implementation with journal-validated closeout. [F2-C driver](../workspace/agents/f2c-job-driver/root/HANDOFF.md) is WIRED offline after [independent re-review](../workspace/agents/f2c-driver-review/kiem_luat/HANDOFF.md): 20 focused tests cover canonical CLI/MissionRunner/coordinator/journal, launch-spec failure, false terminal report and safe already-closed recovery. The current host-isolation trace is bound to one run ID; no per-march operator reconfirmation is intended. |
| Same job → write-once close report | [F3-B closeout](../workspace/agents/f3b-resumable-closeout/root/VALIDATION.md) is WIRED offline at `314fb2c`: the canonical driver checks an ordered attempt chain before another tick, accepts only a uniquely proven orphan VERIFIED slot in its own time window, recovers a terminal report without a sixth tick, and automatically writes an `OFFLINE_REPLAY_PASS`/`BLOCKED` verdict. Forty-seven focused tests and full pytest pass; no fresh live close report exists. Historical replay without an attempt chain is explicitly non-authoritative. Exclusive-create files are not protected from later edits by another local process. Estimated mining/return time remains optional sourced metadata. |
| Daily continuity after FIRST DONE | `troops_panel_sensor`, `return_detection`, `automatic_refill`, `buff_sensor` and `buff_top_up` remain separate later capabilities. The [inventory](../workspace/agents/p1-continuity-evidence/nghien_cuu/HANDOFF.md) found no positive Returning/Home or buff-timer evidence. |
| Local LLM benchmark | PRD F05 and SRS local-LLM contract; holdout is historical evidence of bounded selection. B003 review/training and model participation measurement do not grant farm input or add per-march approval. |

No first-done row is promoted by a planned requirement, a passing isolated test,
or a historical live receipt. An unknown state, missing item or expired session
authority blocks the affected action and must appear in the final evidence.

## Current gate snapshot

The September 23 offline recomputation on the working tree based on HEAD
`7855c616` reports these gate statuses from persisted artifacts:

```text
G1_HOST_INPUT_ISOLATION       PASS
G2_CPU_OCR_STATE              PASS
G3_LOCAL_LLM_HOLDOUT          PASS (promotion pending reviewer)
G4_B003_OCCURRENCE_APPROVAL   PASS
G5_LIVE_GATHER_POSTCONDITION  PASS
G6_ENDURANCE                  BLOCKED (R3 2/10; authorization missing)
```

Commands that do not touch ROK or emit input:

```powershell
python -B -c "from scripts.audit_goal_readiness import audit; import json; print(json.dumps(audit(), ensure_ascii=False))"
python scripts/validate_engineering_graph.py
python scripts/validate_gather_replay.py workspace/evidence/gather/gather-e9f395858e63a2dcb7d0
```

## Required next transition

The offline G1–G6 audit correction was accepted after independent review and
focused tests; all 10 referenced historical artifacts exist and G6 remains
blocked. G6 is the later endurance track, not the five-march criterion.
[ROOT](ROOT.md) links current verification. The next FIRST DONE dependency is
F4-A2 consumption of the one-time startup attestation in driver and direct
tick, followed by F4-B job-scoped host trace in [BUILD_PLAN](BUILD_PLAN.md).
F3-B is wired offline; its live evidence gap remains. These offline results
do not authorize a live run.

The existing R3 execution gate remains a separate historical contract:
`harness/r3_endurance_authorization.py` and `scripts/run_elevated_gather.py`
require fresh scoped authorization, preflight, per-occurrence approval, host
trace, queue verification and immutable evidence for those legacy repetition
runs. That approval mechanism is separate from the one-job FIRST DONE path.
G6 stays blocked; the FIRST DONE autonomous five-march claim is also unproven.

## Historical graph handoff (2026-09-19)

The record below documents the September 19 source change. The September 22
GATHER-EVIDENCE package changed no graph node or edge.

```text
status: PARTIAL (field reconnaissance in progress; operational R3 remains gated)
changed_nodes: [game_state_mission_matrix, r3_endurance_authorization, r3_repetition_evidence, goal_readiness_audit]
added_edges: [r3_endurance_authorization -> goal_readiness_audit, r3_endurance_authorization -> gather_cli]
removed_edges: []
acceptance_evidence: docs/COMPLETION_AUDIT.md, docs/COMPUTER_USE_NATIVE_RPC.md, config/game_field_reconnaissance_plan.json, workspace/evidence/recon/recon-preflight-20260919-01/index.json, workspace/evidence/recon/recon-goal-20260919-02/index.json, workspace/evidence/gather/gather-12f5ed13d5f356c220f8/revision-000001-1789786749383245600.json, workspace/evidence/host/computer-use-native-rpc-incident-20260919-01.json, workspace/evidence/audit/goal-readiness-latest.json, python scripts/validate_engineering_graph.py
known_blockers: [cua_repl wrapper transport is still closed but direct Sky binding is verified, three reconnaissance states are not_observed, R3 2/10, explicit endurance authorization artifact missing, local-LLM/RapidOCR promotion review]
next_unblocked_nodes: [operator-authorized R3 repetition, then endurance gate]
```
