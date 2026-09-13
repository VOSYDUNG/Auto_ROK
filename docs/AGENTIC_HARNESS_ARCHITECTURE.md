# Auto_ROK Agentic Harness V1

## Purpose

Auto_ROK is an Agentic OS that operates Rise of Kingdoms only through the same visible/input surface available to a human player.

The game is an external visual UI environment. The harness:

- sees visible screen pixels;
- interprets them with OCR/CV/visual grounding;
- acts through ordinary mouse and keyboard input;
- learns procedures, layouts and transitions from operator training;
- verifies outcomes from visible feedback.

It does not read game process memory, call private game APIs, inspect engine objects or manipulate network traffic.

The local GPT-OSS model is a bounded semantic decision service. It is not the visual detector, coordinate finder or long-horizon gameplay planner.

## Human-interface boundary

Authoritative boundary: `config/human_io_boundary.yaml`.

### Sensory surface

Only visible screen pixels are game sensing.

### Motor surface

Only ordinary OS mouse and keyboard input are game actuation.

### Compiled knowledge is allowed

Once the operator has taught a stable behavior, the harness should not rediscover it from scratch every run.

Compiled knowledge may include:

- game rules and procedures;
- native shortcuts;
- known UI transitions;
- canonical screen layouts;
- expected target regions;
- learned cursor destinations;
- expected transition timing;
- task graphs and completion signatures.

This is procedural knowledge in the harness, not hidden access to current game state.

### Old observations are not current truth

A previous screen or previous counter value must not be reused as proof of the current screen state.

The distinction is:

```text
TRAINED PROCEDURE / PRIOR       allowed
"after A, button B normally appears here"

STALE EPISODIC OBSERVATION      not current truth
"button B was here yesterday, therefore it exists now"
```

## Belief State

The harness does not possess authoritative internal game state. It maintains a current **Belief State** inferred from visible evidence plus compiled rules.

```text
BELIEF_STATE
├── ui.*
├── player.*
├── march.*
├── alliance.*
├── event.*
└── task.*
```

Each current-game claim carries confidence/provenance.

## Architecture is not a sequential pipeline

The system is reactive and concurrent. Perception, mission control, action eligibility and motor preparation can run in parallel around the current Belief State and compiled procedural knowledge.

```text
                         ┌────────────────────┐
                         │      GPT-OSS       │
                         │ bounded selector   │
                         └─────────▲──────────┘
                                   │ only when a real
                                   │ choice is required
                                   │
             ┌─────────────────────┴──────────────────────┐
             │                                            │
     ┌───────▼────────┐                          ┌────────▼────────┐
     │ MISSION/TASK   │                          │ POLICY /       │
     │ CONTROL        │                          │ CAPABILITIES   │
     └───────┬────────┘                          └────────┬────────┘
             │                                            │
             └──────────────┬─────────────────────────────┘
                            │
                            ▼
                   ┌───────────────────┐
                   │   BELIEF STATE    │
                   └──────▲─────┬──────┘
                          │     │
          visible updates │     │ semantic intent
                          │     │
                ┌─────────┘     └────────────┐
                │                            │
       ┌────────▼────────┐          ┌────────▼──────────┐
       │ VISUAL          │          │ ANTICIPATORY      │
       │ PERCEPTION      │          │ MOTOR CONTROL     │
       │ OCR/CV/ground   │          │ stage/click/drag  │
       └────────▲────────┘          └────────▲──────────┘
                │                            │
                │ pixels                     │ mouse/keyboard
                │                            │
                └─────────────┬──────────────┘
                              ▼
                    ┌──────────────────┐
                    │ GAME UI         │
                    │ ENVIRONMENT     │
                    └──────────────────┘

            ┌──────────────────────────────────┐
            │ COMPILED PROCEDURAL KNOWLEDGE    │
            │ rules / transitions / shortcuts  │
            │ motor priors / task graphs       │
            └──────────────┬───────────────────┘
                           │ feeds every loop
                           └─────────────────────►
```

No subsystem has a privileged path into hidden game internals.

## Concurrent loops

### Visual perception loop

Continuously samples the visible screen and publishes current evidence:

```text
screen pixels
→ OCR/CV/templates/grounding
→ current visual facts
→ belief update
```

### Mission/task loop

Determines which responsibilities are active and what they need. It does not need to wait for GPT when the next semantic action is deterministic.

### Capability/policy loop

Filters actions from trained procedures according to the current belief, mission and operator policy.

### Decision loop

- zero eligible actions: wait/recover/reobserve;
- one eligible action: execute deterministically;
- multiple meaningful actions: GPT-OSS may select among them.

### Anticipatory motor loop

This loop is deliberately predictive.

A trained human does not wait for every target to finish rendering before moving the mouse. The harness should behave similarly.

Example:

```text
known transition starts
      │
      ├── visual perception keeps watching
      │
      └── motor prior predicts next target region
                 │
                 ▼
          move pointer there early
                 │
        target/transition becomes ready
                 │
                 ▼
        click immediately or confirm first
                 │
                 ▼
           verify visible result
```

The pointer can therefore move before the next target is visually complete.

## Motor priors

A `MotorPrior` is learned procedural knowledge tied to a known screen profile/transition.

Typical fields:

```text
from_state
expected_next_state
action_id
screen_profile
normalized target point
confidence
motor mode
```

Three motor modes are supported conceptually:

### PREPOSITION

Move the cursor to the expected point early, but wait for an appropriate trigger before clicking.

### OPTIMISTIC_ACTUATE

For highly trained, stable, low-risk transitions, act at the learned point without waiting for fresh target grounding, then verify the visible postcondition.

### CONFIRM_THEN_ACTUATE

For variable or higher-risk actions, pre-position if useful but require current-frame visual confirmation before committing the click.

Implementation: `harness/anticipatory_motor.py`.

## Coordinates: motor knowledge, not game state

The previous rule "coordinates are always ephemeral" was too strict.

Correct rule:

- current grounded bounding boxes are ephemeral;
- learned coordinates/regions may persist as procedural motor priors;
- a coordinate never proves current game state by itself.

Useful forms:

```text
normalized_point_by_screen_profile
canonical_region_by_ui_state
frame_scoped_grounded_bbox
```

V0 coordinates are therefore useful training data rather than something to discard.

A prior is invalidated when its screen/layout profile no longer matches or repeated visible verification fails.

## Semantic Action Surface

GPT-OSS should normally see semantic actions, not coordinates.

Resolution can use:

```text
semantic action
  ├─ native shortcut
  ├─ compiled motor prior
  ├─ current-frame grounded target
  └─ unresolved/reobserve
```

These are not strictly sequential. For example, the motor controller may stage a prior while the visual system is still confirming the next state.

Examples:

- `OPEN_MAIL` → native `M`;
- `OPEN_ALLIANCE` → native `O`;
- `OPEN_SEARCH` → native `F`;
- `CONFIRM_CHARACTER_LOGIN` → learned stable region or freshly grounded YES button;
- `CLAIM_ALLIANCE_TERRITORY_RSS` → learned region plus optional current-frame confirmation.

## Success and verification

Sending an input is never the same as proving success.

```text
input sent
≠
task action succeeded
```

Success comes from a visible postcondition.

Examples:

- `MARCH`: queue indicator visibly changes;
- character switch: normal main game view returns;
- modal navigation: expected next screen visibly appears.

Optimistic actuation is compatible with this rule: act early, verify afterward.

## Runtime information vs memory

The architecture should not depend on episodic game memory as a substitute for sensing.

However, two persistent categories are legitimate control-plane data:

1. **compiled knowledge** — what the operator already taught the harness;
2. **mission commitments** — e.g. a future task created from an explicitly extracted clan event date.

Neither category is evidence that a current hidden game condition is true.

For daily tasks, whenever the current UI can reveal availability directly, prefer checking visible availability over remembering a previous game-state value.

## Example: Character switch

Trained procedure:

```text
ACCOUNT_CHARACTER_LIST
→ choose a different character
→ CHARACTER_LOGIN_CONFIRM
→ YES
→ asynchronous load
→ MAIN_GAME_VIEW
→ COMPLETE
```

The motor controller can predict and stage the pointer over the YES region while the confirmation modal is appearing. Completion still requires the visible main game view to return.

## Example: Gather resource

The learned procedure is represented as task knowledge:

```text
WORLD_MAP_VIEW
→ OPEN_SEARCH
→ choose resource/level
→ SEARCH
→ RESOURCE_POINT_DETAIL
→ GATHER
→ NEW_TROOP
→ MARCH
```

At each trained transition, motor priors may reduce latency. The verifier still checks visible progression such as march queue change.

## Example: Daily Alliance Territory RSS

The mission-level rule says this is a daily responsibility. Current availability should be determined from what the UI exposes when the task is inspected.

```text
DAILY mission activates
→ navigate using trained procedure
→ visible Territory screen
→ if CLAIM is visibly/operationally available, claim
→ verify visible postcondition
```

The task does not need stale remembered game state to know whether CLAIM exists now.

## Example: Event coordination

A clan-mail-selected event date can create a future mission commitment:

```text
visible clan mail
→ semantic extraction
→ explicit structured date
→ scheduler commitment
→ on that date, inspect current visible game UI again
```

The stored date is workflow data, not remembered hidden game state.

## Knowledge provenance

For game mechanics:

```text
official in-game guide
> direct visible observation
> repeated operator observation
> operator explanation
> derived heuristic
```

For operator procedure/policy:

```text
operator instruction
> trained repeated procedure
> derived preference
```

## GPT-OSS contract

Input may include:

```json
{
  "mission": "...",
  "task": "...",
  "belief_state": "...",
  "visible_facts": {},
  "compiled_rules": {},
  "last_visible_feedback": {},
  "allowed_actions": []
}
```

Output:

```json
{
  "action": "ONE_ALLOWED_ACTION",
  "arguments": {}
}
```

The runtime rejects actions outside `allowed_actions`.

GPT-OSS should not need raw coordinates, hidden state, frame-by-frame spatial reasoning for trained targets or rediscovery of known procedures.

## Runtime invariants

1. Game sensing is screen-pixel-only.
2. Game actuation is mouse/keyboard-only.
3. Hidden game state is never read directly.
4. Current Belief State is inferred from current visible evidence plus compiled rules.
5. Stale episodic observations are not current truth.
6. Trained procedures, layouts and motor priors may persist.
7. Cursor movement may anticipate a target before it fully appears.
8. Stable low-risk transitions may use optimistic actuation when explicitly trained.
9. Success requires visible postcondition verification.
10. GPT-OSS selects only among eligible semantic actions.
11. Zero/one-action states need no LLM inference.
12. Unknown rules are training gaps, not invitations to guess.

## Migration from V0

Reusable V0 assets:

- `Avatar.py`: OCR/CV and visual feature experiments;
- `Human.py`: demonstration/trajectory capture seed;
- `Mouse_key.py`: historical motor procedures;
- `Position.txt`: valuable motor-prior/bootstrap geometry;
- `LOG_WORKS.txt`: early decomposition of repeated behavior.

V0 fixed coordinates are no longer classified simply as brittle legacy data. Where the UI is stable, they can seed normalized motor priors that are verified and calibrated against the current screen profile.

## V1 milestones

### M0 — Knowledge + Human I/O boundary
- mission/task vocabulary;
- operator/guide knowledge;
- human-only sensor/actuator boundary;
- trained procedures.

### M1 — Visual perception + motor priors
- screen capture;
- OCR/CV/grounding;
- Belief State;
- canonical target regions;
- anticipatory cursor staging.

### M2 — Passive/assisted runtime
- action eligibility;
- predicted next targets;
- visible feedback;
- no requirement for full autonomy.

### M3 — One verified daily task
- human-input-only execution;
- predictive motor control where trained;
- visible completion verifier.

### M4 — Mission scheduling
- recurring responsibilities;
- interruption/resume;
- explicit future commitments from visible information;
- no stale game-state memory dependency.

### M5 — Local GPT-OSS
- constrained action selection;
- model invoked only for meaningful choices;
- latency telemetry;
- deterministic fast path for fully trained behavior.

## Non-goals

- reading game process memory;
- process/DLL injection;
- private/internal game APIs;
- packet inspection/manipulation;
- anti-cheat interaction/evasion;
- CAPTCHA bypass;
- hidden-state shortcuts unavailable through the normal UI.
