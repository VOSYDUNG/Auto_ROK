# Auto_ROK / local-LLM harness roadmap status

Updated 2026-09-19 (Asia/Ho_Chi_Minh).  The implementation is a useful
observation and decision-edge prototype; it is not yet an unattended live
Computer Use release.

## Evidence-backed status

| Gate | Current result | Meaning |
|---|---|---|
| Field reconnaissance before E2E | **Partial / GATHER boundary frozen** | Native Sky binding is verified on the real elevated `MASS.exe`; safe pass `recon-goal-20260919-02` captures CITY_VIEW ↔ WORLD_MAP → SEARCH → node detail → troop drawer → safe close with frame/hash provenance and zero MARCH input. Launch/login, march-confirmation and recovery/unknown remain explicitly `not_observed`; the bounded GATHER E2E path is now separately proven. |
| Computer Use native RPC binding | **Repair applied; reload verification pending** | The 2026-09-19 incident was a launcher split: `cua_repl` started with `browser` only and no trusted `sky` service even though the independent Sky RPC and ROK process were healthy. The launcher cache now enables `browser,computer` and registers `@oai/sky/service`; a post-restart `cua.getState()` containing the exact ROK window is still required before input is armed. See `docs/COMPUTER_USE_NATIVE_RPC.md` and `workspace/evidence/host/computer-use-native-rpc-incident-20260919-01.json`. |
| PRD → design brief → local-LLM user stories | **Ready** | The local model is a bounded semantic chooser; capture/OCR/ROI/policy/actuation/verification remain harness-owned. |
| CPU ROI + main-view detector | **Screening** | Fixed client ROI, OpenCV CPU, OpenCL/CUDA disabled. The latest corpus report evaluates 20 labelled + 10 holdout captures; CITY/WORLD and search-panel state matches are 100% exact after a bounded fixed-panel anchor repair. Fresh CPU signature runs remain ~42 ms median/frame. |
| OCR/state corpus (R1a) | **Pass for the derived CPU corpus; runtime promotion pending** | The canonical Windows OCR-only path remains a 22/60 diagnostic baseline, but the fixed-ROI RapidOCR overlay is now independently visually reviewed and locked across 12 frames. It reaches **56/60 OCR-only** (precision 1.0, recall 0.9333) and **58/60 with compiled layout** (recall 0.9667), while the observation bridge records 30/30 projections and 30/30 exact state classifications with zero input. The 120 recognizer samples remain capture/hash-bound at 15.9 ms median and 18.7 ms p95. The optional runtime flag is wired and fail-closed, but a fresh live runtime remeasurement is still required before promoting it over Windows.Media.Ocr. Tesseract remains a lower-performing comparison (18/100 exact on one frame). |
| Local GPT-OSS decision edge | **Holdout measured; promotion pending** | The frame-disjoint holdout passes **12/12** across 3 real ROK search frames × FOOD/WOOD/STONE/GOLD, accuracy **1.0**, complete usage telemetry, median **20.6s**, p95 **29.0s**, and zero input. A fresh one-case loopback probe showed the 256-token cap can exhaust on reasoning and fail closed; a separate 512-token experiment profile returned the bounded candidate in **44.0s** with request digest/bytes and zero input. The aggregate remains `holdout_multi_frame_real_replay` with `prd_r1b=measured_pending_reviewer`; independent reviewer acceptance and live postcondition evidence are still required for promotion. The no-intent guard remains **4/4 abstain before endpoint request**. |
| Harness-tax comparison protocol | **Offline screening measured; promotion pending** | `config/harness_benchmark_matrix.json` fixes the model/case/frame factors, and `scripts/run_harness_tax_benchmark.py` now replays the 12-case frame-disjoint holdout without contacting a model or desktop. H0 safely abstains on 12/12 ambiguous cases with zero invented choices; H1 reproduces the recorded bounded choices 12/12. The result is screening-only because historical CPU/RAM, request-byte/fingerprint and verified-completion telemetry are unavailable, and independent review/live evidence are still pending. |
| B003 troop approval | **Pass for current occurrence** | `gather-admin-20260919-03` has explicit operator approval bound to `GATHER_RESOURCE` / `one-character` / run / `char-direct-01`; the approval, B003 review and R3 preflight are persisted. A new occurrence still requires a new approval. |
| Direct-host input isolation (R2) | **Pass for current occurrence** | The `gather-admin-20260919-03` elevated trace proves target binding, foreground stability, explicit quiescence, automatic stale-frame rejection, cancellation and zero unintended input on the direct Windows host. |
| Cancel/resume/recovery contract | **Offline pass** | Fresh report `recovery-matrix-20260919-02` passes 10/10 cancel and 10/10 restart/idempotence/tamper-block cases with no input. The direct-host trace adds an explicit cancel/stale-frame check before arming. |
| One-character GATHER + Queue used +1 (R3) | **Current bounded E2E pass; R3 endurance still 2/10** | Fresh occurrence `gather-goal-20260919-04` dispatched exactly one MARCH after a new host trace and occurrence-bound approval; queue increased `1/5 → 2/5` and `MissionEngine` produced `COMPLETE`. The registered R3 threshold remains `2/10`; eight authorized repetitions remain. A live OCR holdout was repaired with the bounded New Troop summary crop and dedup. |
| Endurance 1h → 15h (R4) | **Deferred** | It is gated by R3 and must not run early. |

## Next path

1. Re-measure the now-locked RapidOCR backend through a visible live ROK
   observation window; keep the default Windows OCR path unchanged until that
   runtime evidence is accepted.
2. Record one direct-host trace while the operator hands the foreground to ROK
   for a bounded action window; no guest, VM, Docker or reboot is required.
   Run the live runner at the same/elevated Windows integrity as ROK so UIPI
   cannot block ordinary mouse/keyboard input.
3. Retain the immutable evidence for `gather-goal-20260919-04` and keep using
   the pending-verification path for delayed panel/map transitions. The crop
   repair is now part of the canonical Windows OCR path.
4. After explicit operator authorization, repeat to the R3 threshold (10 runs,
   then the registered scenario set); do not start endurance implicitly.
   The audit accepts only `workspace/evidence/gather/R3_ENDURANCE_AUTHORIZATION.json`
   scoped to `GATHER_RESOURCE` / `one-character` / `char-direct-01`, with an
   explicit `max_additional_runs` covering the remaining repetitions.
5. Only after R3, run the short endurance gate and then consider 15 hours.

## Artifacts

- Local-LLM canary: `workspace/evidence/local_llm/needs-decision-gpt-oss-screening-20260918-01.json`
- Local-LLM usage sample: `workspace/evidence/local_llm/needs-decision-gpt-oss-20260918-usage.json`
- Local-LLM multiframe report: `workspace/evidence/local_llm/needs-decision-gpt-oss-multiframe-256-20260918.json`
- Local-LLM intent matrix: `workspace/evidence/local_llm/needs-decision-gpt-oss-intent-matrix-256-20260918.json`
- Local-LLM no-intent guard: `workspace/evidence/local_llm/needs-decision-gpt-oss-no-intent-guard-20260918.json`
- Local-LLM post-guard visible batch: `workspace/evidence/local_llm/needs-decision-gpt-oss-post-guard-20260918.json`
- Local-LLM reversed-candidate batch: `workspace/evidence/local_llm/needs-decision-gpt-oss-reverse-20260918.json`
- Local-LLM frame-disjoint holdout validation: `workspace/evidence/local_llm/needs-decision-gpt-oss-holdout-manifest-20260918.json`
- Local-LLM frame-disjoint holdout result: `workspace/evidence/local_llm/needs-decision-gpt-oss-holdout-20260918.json`
- Harness-tax adaptation and matched-model protocol: `docs/HARNESS_TAX_ADAPTATION.md`
- Harness-tax benchmark contract: `config/harness_benchmark_matrix.json`
- Harness-tax offline screening runner: `scripts/run_harness_tax_benchmark.py`
- Harness-tax offline screening result: `workspace/evidence/local_llm/harness-tax-benchmark-latest.json`
- Live local-LLM cap-boundary failure (safe abstention, no input): `workspace/evidence/local_llm/local-llm-tax-live-20260919-01.json`
- Live local-LLM bounded-choice probe with 512-token experiment profile: `workspace/evidence/local_llm/local-llm-tax-live-20260919-03b.json`
- CPU-only local-model launch/stop evidence: `workspace/runs/local-llm-holdout-20260918-01/launch.json`
- CPU/OCR/state corpus: `workspace/evidence/corpus/cpu-observation-corpus-20260918-13.json`
- CPU/OCR/state corpus (previous checkpoint): `workspace/evidence/corpus/cpu-observation-corpus-20260918-11.json`
- Critical-field OCR quality screen: `workspace/evidence/corpus/ocr-quality-20260918-06.json`
- Category-label ROI OCR experiment (diagnostic only; runtime unchanged): `workspace/evidence/corpus/ocr-category-experiment-20260918-01.json`
- Tesseract CPU ROI screening (diagnostic only; runtime unchanged): `workspace/evidence/corpus/tesseract-ocr-experiment-20260918-02.json`
- RapidOCR fixed-ROI CPU screening (diagnostic only; runtime unchanged): `workspace/evidence/corpus/rapidocr-corpus-experiment-20260918-01.json`
- RapidOCR fixed-ROI CPU screening with capture/hash binding (diagnostic only; runtime unchanged): `workspace/evidence/corpus/rapidocr-corpus-experiment-20260919-01.json`
- RapidOCR fixed-ROI CPU screening with capture/hash binding and latency (diagnostic only; runtime unchanged): `workspace/evidence/corpus/rapidocr-corpus-experiment-20260919-03.json`
- RapidOCR fixed-ROI derived overlay through the existing R1a evaluator (diagnostic only; canonical OCR unchanged): `workspace/evidence/corpus/ocr-quality-rapidocr-overlay-20260919.json`
- RapidOCR fixed-ROI derived overlay through the existing observation bridge (diagnostic only; canonical OCR unchanged): `workspace/evidence/corpus/cpu-observation-corpus-rapidocr-overlay-20260919.json`
- Independent OCR label review packet: `workspace/evidence/corpus/ocr-independent-review-packet-20260919.json`
- Independent OCR label review result (12 frame/hash-bound confirmations): `workspace/evidence/corpus/ocr-independent-review-result-20260919.json`
- RapidOCR overlay R1a report after independent lock: `workspace/evidence/corpus/ocr-quality-rapidocr-overlay-20260919-independent.json`
- RapidOCR observation bridge report after independent lock: `workspace/evidence/corpus/cpu-observation-corpus-rapidocr-overlay-20260919-independent.json`
- OCR label-lock manifest: `config/observation_label_lock.json`
- CPU signature benchmark (latest five-image, 7-iteration run): `workspace/evidence/cpu/live-followup-20260918-04.json`
- Live stage timing (unarmed): `workspace/runs/live-timing-20260918-01/run.json`
- Fresh passive city holdout: `workspace/runs/live-followup-20260918-01/`
- Recovery matrix: `workspace/evidence/recovery/recovery-matrix-20260918-01.json`
- Historical B003/preflight checks remain archived for audit; the active
  occurrence is `workspace/evidence/gather/R3_PREFLIGHT-20260918-07.json`.
- Goal readiness audit (G1–G5 pass; G6 is blocked at R3 2/10 and awaits
  explicit endurance authorization):
  `workspace/evidence/audit/goal-readiness-latest.json`
- Requirement-by-requirement completion audit:
  `docs/COMPLETION_AUDIT.md`
- Latest goal readiness audit after the state/mission matrix:
  `workspace/evidence/audit/goal-readiness-20260918-matrix.json`
- Canonical latest audit output (dynamic evidence selection):
  `workspace/evidence/audit/goal-readiness-latest.json`
- Observation-only live tick: `workspace/evidence/gather/live-20260918-01-cpu-criterion/`
- Latest passive integration tick: `workspace/evidence/gather/passive-direct-host-20260918-03/` (`CITY_VIEW`, `LIVE_ACTUATION_NOT_ARMED`, no input)
- Current occurrence approval: `workspace/evidence/gather/approvals/gather-admin-20260919-03.json`
- Current occurrence preflight: `workspace/evidence/gather/R3_PREFLIGHT-20260919-03.json`
- Current live completion: `workspace/evidence/gather/gather-e9f395858e63a2dcb7d0/revision-000005-1789780669952972900.json`
- Latest bounded live E2E completion: `workspace/evidence/gather/gather-596d20bfddd42eb077af/revision-000013-1789787875616850100.json` (`Queue 1/5 → 2/5`, one verified MARCH)
- Latest occurrence approval/preflight: `workspace/evidence/gather/approvals/gather-goal-20260919-04.json`, `workspace/evidence/gather/R3_PREFLIGHT-gather-goal-20260919-04-final.json`
- Latest direct-host trace: `workspace/evidence/host/gather-goal-20260919-04-20260919T031742734674Z-00.json`
- Latest safe field-recon pass: `workspace/evidence/recon/recon-goal-20260919-02/index.json`
- Latest safe field-recon images/observations: `workspace/evidence/recon/recon-goal-20260919-02/`
- Unarmed live E2E guard proof: `workspace/evidence/gather/gather-12f5ed13d5f356c220f8/revision-000001-1789786749383245600.json` (`OPEN_SEARCH` candidate held at `LIVE_ACTUATION_NOT_ARMED`; zero input)
- R3 registered-run contract: `config/r3_registered_runs.json`
- R3 repetition validator/report (2/10 registered, 2/9 minimum successes): `scripts/validate_r3_repetition.py`, `workspace/evidence/gather/r3-repetition-latest.json`
- R3 execution-side authorization and append-only reservation gate: `harness/r3_endurance_authorization.py`, `scripts/run_elevated_gather.py`, `tests/test_r3_endurance_authorization.py`
- Pending-dispatch recovery linkage: `workspace/evidence/gather/pending-recovery-gather-admin-20260918-02.json`
- Post-MARCH passive frame/OCR (queue ROI): `workspace/runs/live-after-march-20260918-01/`
- Historical goal readiness audit after the first occurrence: `workspace/evidence/audit/goal-readiness-20260918-04.json`
- Direct-host contract: `docs/HOST_INPUT_ISOLATION.md`
- State/mission knowledge map: `docs/GAME_STATE_MISSION_MATRIX.md`
- Field reconnaissance plan and first passive packet: `config/game_field_reconnaissance_plan.json`, `docs/GAME_FIELD_RECONNAISSANCE.md`, `workspace/evidence/recon/recon-preflight-20260919-01/observation.json`
- Direct-host recorder: `scripts/record_host_input_isolation.py`
- Direct-host assessor: `scripts/assess_host_input_isolation.py`
- Historical direct-host trace: `workspace/evidence/host/direct-host-r2-20260918-02.json`
- Direct-host assessment (blocked, no input): `workspace/evidence/host/direct-host-r2-20260918-02-assessment.json`
- Current direct-host trace: `workspace/evidence/host/gather-admin-20260919-03-20260919T011737622239Z-04.json`
- Integrity-guard evidence (no input): `workspace/evidence/gather/gather-4558166e0659aa7b84fe/revision-000001-*.json`
- Diagnostic safety incident (old probe moved the host pointer; patched to read-only): `workspace/evidence/host/diagnose-input-incident-20260918-01.json`
- Direct-host environment check (ROK not foreground; loopback endpoint unavailable): `workspace/evidence/host/direct-host-environment-check-20260918-01.json`
- Latest live prerequisite check (MASS.exe absent; no input): `workspace/evidence/host/live-prerequisite-check-20260919.json`
- Host capability probe (read-only, not R2 readiness): `workspace/evidence/guest/host-capability-20260918-01.json`
- Latest host recheck (unchanged, read-only): `workspace/evidence/guest/host-capability-20260918-02.json`

The GPT-OSS server used for the canary was a pre-existing llama.cpp binary,
started only for the bounded experiment with `--device none`, `--gpu-layers 0`,
one slot and 18 CPU threads, then stopped.  The production local-LLM config
remains disabled by default.  No native C/C++ compiler was available on this
host during the check; the current measured vision path is CPU OpenCV, and the
model—not ROI extraction—is the dominant latency.
