# B003 — occurrence-bound troop/commander approval

B003 is closed for the current live occurrence, but remains a per-occurrence
gate.  The harness does not infer a safe commander or troop composition from
OCR, and opening ROK does not authorize host input.  Before each live
one-character `GATHER_RESOURCE` run, the operator must approve the *currently
visible* selection for one exact tuple:

`mission_id + task_id + run_id + character_id`.

The existing `TroopSelectionApproval` contract rejects a missing, negative or
cross-occurrence approval.  A durable JSON artifact can be supplied with
`--troop-policy-approval`; for a one-shot run the explicit
`--approve-current-troop-selection` flag creates an occurrence-bound approval.
Neither route arms live input by itself: the direct-host input-isolation gate and
the foreground/geometry guard still have to pass.

For `gather-admin-20260919-03`, the operator explicitly approved the visible
selection. The approval, B003 review, R3 preflight, direct-host assessment and
final `VERIFIED` completion record are persisted at:

- `workspace/evidence/gather/approvals/gather-admin-20260919-03.json`
- `workspace/evidence/gather/B003_CURRENT_OCCURRENCE_REVIEW-20260919-03.json`
- `workspace/evidence/gather/R3_PREFLIGHT-20260919-03.json`
- `workspace/evidence/host/gather-admin-20260919-03-20260919T011737622239Z-04-assessment.json`
- `workspace/evidence/gather/gather-e9f395858e63a2dcb7d0/revision-000005-1789780669952972900.json`

The approval is not reusable: another run must create and validate a new
occurrence-bound artifact.

## Next occurrence handoff

After the operator has launched the elevated ROK client and left it in the
foreground, use a new run id and a new session id. The helper waits for the
foreground gate, records a passive direct-host trace, and only then invokes
the guarded runner:

```text
python scripts/run_elevated_gather.py \
  --run-id <new-run-id> \
  --character-id char-direct-01 \
  --resource-type FOOD \
  --resource-level 6 \
  --session-id <windows-session-id> \
  --recovery-evidence workspace/evidence/recovery/recovery-matrix-20260918-01.json \
  --approve-current-troop-selection \
  --operator-confirms-quiescent \
  --output workspace/evidence/gather/<new-run-id>-elevated.json
```

The command intentionally does not launch or activate ROK, does not reuse the
previous approval, and cannot proceed while `MASS.exe` is absent or not
foreground. A non-zero result remains evidence of a blocked/failed occurrence;
it must not be counted as Queue +1.

When the operator has separately authorized the R3 repetition set, add
`--r3-endurance-authorization workspace/evidence/gather/R3_ENDURANCE_AUTHORIZATION.json`.
The helper then validates the exact manifest identity and reserves the run in
the append-only `R3_RUN_RESERVATIONS.jsonl` ledger immediately after the
passive host preflight. A reservation is consumed even if the later live
attempt fails; it is never reused or overwritten. This flag is optional for a
single non-R3 occurrence and does not create the authorization artifact. The
guarded tick also verifies that the exact fresh reservation exists before it
can arm live input.

## R3 repetition authorization

The first bounded live occurrence and the registered R3 repetition set are
separate permissions. Before running the remaining repetitions, create
`workspace/evidence/gather/R3_ENDURANCE_AUTHORIZATION.json` only after an
explicit operator decision. A non-authorizing template is kept at
`config/r3_endurance_authorization.example.json`; copy/fill it only when the
operator actually approves the bounded run set. The readiness audit accepts it only when it has
`scope: r3_live_gather_repetition`, `approved: true`, the exact
`GATHER_RESOURCE` / `one-character` / `char-direct-01` identity, an ISO-8601
`approved_at`, and `max_additional_runs >= 8`. This authorization does not
replace per-occurrence B003 approval or direct-host preflight.
