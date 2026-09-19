# Auto_ROK completion audit

Updated 2026-09-19 (Asia/Ho_Chi_Minh). This is a requirement-by-requirement
audit of the active Goal. It is evidence-led: `PASS` means the named artifact
proves the exact claim, `PARTIAL` means a promotion or scope edge remains, and
`BLOCKED` means the evidence is insufficient for the next irreversible step.

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
| Occurrence-bound B003 approval | PASS for current occurrence | `workspace/evidence/gather/approvals/gather-goal-20260919-04.json`, `workspace/evidence/gather/R3_PREFLIGHT-gather-goal-20260919-04-final.json` | Every new occurrence requires a new approval. |
| Direct-host input isolation | PASS for current occurrence | `workspace/evidence/host/gather-goal-20260919-04-20260919T031742734674Z-00.json` | Only the bounded foreground action window is covered; no unattended desktop claim. |
| Checkpoint, cancel, resume and tamper blocking | PASS offline | `workspace/evidence/recovery/recovery-matrix-20260919-02.json`, `tests/test_mission_runner.py`, `tests/test_mission_ledger.py` | Matrix is contract-only and intentionally emits no live input. |
| Immutable/append-only runtime evidence | PASS | `harness/gather_replay_evidence.py`, `tests/test_gather_replay_evidence.py`, `scripts/validate_gather_replay.py` | Evidence is append-only; timestamp collisions fail closed. |
| One live GATHER postcondition | PASS for current bounded occurrence | `workspace/evidence/gather/gather-596d20bfddd42eb077af/revision-000013-1789787875616850100.json`, `workspace/evidence/audit/goal-readiness-latest.json` | After-state may be `UNKNOWN_STATE`; fresh queue provenance (`1/5 → 2/5`) is the accepted completion fact. |
| Local-LLM holdout and 80/20 boundary | PASS measured / PARTIAL promotion | `workspace/evidence/local_llm/needs-decision-gpt-oss-holdout-20260918.json`, `tests/test_local_llm_selector.py`, `config/local-llm.json` | 12/12 bounded choices and zero input; production promotion remains disabled pending review. |
| R3 repetition threshold | BLOCKED | `config/r3_registered_runs.json`, `workspace/evidence/gather/r3-repetition-latest.json` | 2/10 registered and 2/9 minimum successes; 8 additional live occurrences are required. |
| Explicit authorization for additional live runs | BLOCKED / execution gate built | `harness/r3_endurance_authorization.py`, `scripts/run_elevated_gather.py`, `tests/test_r3_endurance_authorization.py`, `scripts/audit_goal_readiness.py` | `workspace/evidence/gather/R3_ENDURANCE_AUTHORIZATION.json` is intentionally absent until the operator authorizes it; no live R3 run has been started by this build. |
| Endurance / longer-run promotion | DEFERRED | `docs/ROADMAP_STATUS.md`, G6 in `workspace/evidence/audit/goal-readiness-latest.json` | Must not start before R3 and explicit authorization. |

## Current gate snapshot

The latest read-only audit reports:

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
python scripts/audit_goal_readiness.py --output workspace/evidence/audit/goal-readiness-latest.json
python scripts/validate_engineering_graph.py
python scripts/validate_gather_replay.py workspace/evidence/gather/gather-e9f395858e63a2dcb7d0
```

## Required next transition

The next transition is operator-authorized R3 repetition, not an inferred
endurance run. The execution gate is now wired: when the authorization flag is
supplied, the elevated helper validates the active manifest and appends one
unique reservation ticket after host preflight, before live dispatch. The
authorization artifact must be scoped to
`GATHER_RESOURCE` / `one-character` / `char-direct-01`, use scope
`r3_live_gather_repetition`, set `approved: true`, contain an ISO-8601
`approved_at`, and set `max_additional_runs` to at least 8. Each live run must
still receive its own approval, direct-host trace, fresh Queue verification and
immutable evidence record. Until that artifact and the remaining evidence exist,
the Goal must remain active and G6 must remain blocked.

## Graph handoff

```text
status: PARTIAL (field reconnaissance in progress; operational R3 remains gated)
changed_nodes: [game_state_mission_matrix, r3_endurance_authorization, r3_repetition_evidence, goal_readiness_audit]
added_edges: [r3_endurance_authorization -> goal_readiness_audit, r3_endurance_authorization -> gather_cli]
removed_edges: []
acceptance_evidence: docs/COMPLETION_AUDIT.md, docs/COMPUTER_USE_NATIVE_RPC.md, config/game_field_reconnaissance_plan.json, workspace/evidence/recon/recon-preflight-20260919-01/index.json, workspace/evidence/recon/recon-goal-20260919-02/index.json, workspace/evidence/gather/gather-12f5ed13d5f356c220f8/revision-000001-1789786749383245600.json, workspace/evidence/host/computer-use-native-rpc-incident-20260919-01.json, workspace/evidence/audit/goal-readiness-latest.json, python scripts/validate_engineering_graph.py
known_blockers: [cua_repl wrapper transport is still closed but direct Sky binding is verified, three reconnaissance states are not_observed, R3 2/10, explicit endurance authorization artifact missing, local-LLM/RapidOCR promotion review]
next_unblocked_nodes: [operator-authorized R3 repetition, then endurance gate]
```
