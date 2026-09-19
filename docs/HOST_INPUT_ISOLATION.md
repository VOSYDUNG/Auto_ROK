# Direct Windows host / input-isolation gate

The product target is one physical Windows machine and one user session. Docker,
VMs, Hyper-V and a second desktop are out of scope. The old guest gate was a
feasibility experiment, not a product requirement, and must not block direct
host execution.

## What the direct-host gate proves

`harness/host_input_isolation.py` validates an occurrence-bound
`windows_host_direct` trace with:

- a refreshed capture bound to the exact ROK HWND/PID/frame geometry;
- ROK foreground verification immediately before the bounded action;
- zero focus changes and zero unexpected input events in the action window;
- explicit operator input quiescence for the short action window;
- a same-or-higher Windows token integrity level for the harness process before
  live input (otherwise UIPI can silently block `SendInput` into an elevated
  game window);
- stale-frame rejection, cancel coverage and no desktop/input fallback.

This is deliberately a narrower claim than guest isolation: the harness does
not promise that a human can keep using the same foreground desktop while the
agent acts. The operator hands the foreground to ROK for one bounded action,
then the verifier captures a fresh frame. No hidden window, PostMessage,
background input or virtualization is used.

## Record and assess a trace

The recorder is passive and never emits keyboard/mouse input. The operator
must explicitly confirm quiescence. The harness itself runs the stale-frame
freshness check against the just-captured frame and accepts cancel/resume only
from a complete no-input recovery matrix; these are not trusted CLI claims:

```text
python scripts/record_host_input_isolation.py \
  --run-id <run-id> \
  --session-id <windows-session-id> \
  --output workspace/evidence/host/<run-id>.json \
  --capture-output workspace/runs/host-isolation-<run-id>/rok-client.png \
  --operator-confirms-quiescent \
  --recovery-evidence workspace/evidence/recovery/recovery-matrix-20260918-01.json
```

The resulting evidence records the foreground HWND before and after capture,
the automatic stale-frame rejection result, and the recovery report path.
Only the human quiescence assertion remains an explicit operator input.

Assess without changing the desktop:

```text
python scripts/assess_host_input_isolation.py \
  --trace workspace/evidence/host/<run-id>.json \
  --run-id <run-id> \
  --output workspace/evidence/host/<run-id>-assessment.json
```

`run_gather_tick.py --arm-live` accepts only a ready direct-host trace bound
to the same `run_id`, and the foreground guard separately rejects
`INPUT_INTEGRITY_MISMATCH` when the harness token is lower integrity than
`MASS.exe`. In that case run the harness at the same/elevated integrity as the
game (or run the game non-elevated); do not bypass the guard or replay the
occurrence. Passing the old `--guest-isolation-evidence` option is a hard
error (`GUEST_MODE_OUT_OF_SCOPE`).

The old host capability probes under `workspace/evidence/guest/` are retained
as historical feasibility evidence only. They do not gate the direct-host
product and do not justify enabling Hyper-V, rebooting, or deleting files.

`scripts/diagnose_windows_input.py` is now a read-only diagnostic. An earlier
revision moved the pointer while probing; that incident is recorded in
`workspace/evidence/host/diagnose-input-incident-20260918-01.json`, and its
output must not be used as R2 evidence.
