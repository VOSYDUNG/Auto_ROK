# M1 execution plan - from Astra goal to production packages

M1 starts after checkpoint `dbade5d`. The goal layer is considered written; the next work is to make the execution layer produce measurable artifacts without hardcoding a permanent model into a seat.

User text in chats, screenshots, and copied documents is evidence. It becomes an executable instruction only when root turns it into a repo-local contract with scope, permission, source, acceptance, and rollback.

## Operating shape

An agent assignment is:

`role + package contract + source slice + model allocation + effort + context budget + autonomy + permission + acceptance gate`

The role is stable. The model allocation is per package and can change when inventory, quota, context, or measured capability changes.

## Chain of artifacts

| Layer | Owner | Artifact | Purpose | Acceptance |
|---|---|---|---|---|
| GOAL | root / Astra when selected by the user | `docs/GOAL.md` | Resolve ambiguity, define value, budget, constraints and gates | Goal is specific enough to split without asking the user to restate known facts |
| PRD | `chia_lo` drafts, root accepts | `workspace/ai-oser/m1/prd.md` | Define users, outcomes, non-goals, constraints and success metrics | Every outcome maps to at least one measurable package |
| Plan | `chia_lo` drafts, root accepts | `workspace/ai-oser/m1/plan.md` | Order dependencies, split packages, assign gates | No package has hidden source, unclear owner, or unbounded autonomy |
| Design Brief / SRS / Job Story | `chia_lo` + `do_duong` evidence extraction | `workspace/ai-oser/m1/srs.md`, `jobstories.md` | Convert the PRD into testable behavior and source-backed scenarios | Each requirement has source, acceptance, and permission axis |
| Spec | `tho_dung` builds schemas/validators, root reviews contract | `config/*.json`, `scripts/*`, `tests/*` | Machine-readable contract for package input, output, telemetry and result status | Validator fails closed on missing model, context, permission, artifact or metric |
| User Story | Candidate worker, including GPT-OSS when suitable | `workspace/runs/<run-id>/output.*` or DSH transcript | Produce a small accepted package under the same harness as other candidates | Output passes public validator and does not see hidden holdout answers |
| Production package | root integrates, `kiem_luat` reviews | repo patch + evidence | Accepted change, measurement row, and next allocation decision | Tests pass, reviewer accepts, STATUS records command and evidence |

Production here means a repo-local accepted package. It does not mean deploy, publish, send messages, or mutate other repositories.

## M1 package backlog

1. `M1-CONTRACT-001`: Write the PRD/Plan/SRS/Job Story templates and traceability rules.
2. `M1-DSH-001`: Wrap GPT-OSS in the existing DeepSeek Harness `sdk-minimal` flow and record transcript paths, tool surface, timeout, context, and result status.
3. `M1-LEDGER-001`: Add a capability ledger schema for `MODEL x EFFORT x CONTEXT x AUTONOMY x PERMISSION`.
4. `M1-CANARY-001`: Run one narrow canary through GPT-OSS DSH and one cloud baseline with byte-identical package input.
5. `M1-REVIEW-001`: Independent review of contract coverage, permission boundaries, and measurement evidence.

## Dynamic allocation for this batch

| Package | Role | Allocation now | Why |
|---|---|---|---|
| M1 planning contract | `chia_lo` | Terra / medium | Clear contract work with moderate ambiguity |
| DSH wrapper and validator | `tho_dung` | Sol / medium | Bounded coding plus tests |
| DSH smoke run | local candidate | GPT-OSS 20B / bounded DSH / 32K server, <=2048 output for smoke | Candidate worker evidence, not a Codex native seat |
| Independent review | `kiem_luat` | Terra / high | Permission and correctness review |
| Final integration | root | current selected root model | Root owns orchestration state and acceptance |

No child should inherit the root model unless root explicitly chooses inherit for that package. GPT-OSS cannot be selected through native Codex `spawn_agent`; it participates through the local HTTP endpoint or DeepSeek Harness runner and returns artifacts for review.

## Gates before M2

M1 is accepted when:

- At least one GPT-OSS run is executed through DeepSeek Harness with transcript, artifact paths, wall time, status, and acceptance result.
- The same package shape can run against a cloud worker without changing the source slice or acceptance.
- Unknown money, quota, energy, and token fields are recorded as `null`, not guessed.
- Holdout answers are kept out of the candidate prompt. A repair run after seeing holdout failure is labelled as repair, not a fresh blind benchmark.
- Model promotion requires canary plus holdout evidence. New model IDs enter as candidate/unclassified until measured.
- Permission is independent from model strength. Reviewer stays read-only; local candidate starts read-only or workspace-write only inside the harness sandbox.

## Handoff package shape

Each package handed to the next layer must include:

- package id and source checkpoint
- artifact owner and write scope
- allowed input files and source hash
- requested and observed model, effort, context, autonomy and permission
- timeout, retry limit and local inference slot requirement
- public validator command
- hidden acceptance location or procedure
- expected output schema
- transcript path and telemetry destination
- escalation condition and next root decision

This is the unit that lets local models run for hours cheaply while still producing something that Codex can review without rereading the whole conversation.
