# AUTO_ROK Operator Layer V1

## Purpose

The Operator Layer builds an operational profile of the human/player from information that is already visible inside the game, plus only the personalization that the game cannot provide.

It must not ask the operator to manually re-enter facts that AUTO_ROK can obtain by navigating the visible UI.

The layer has two outputs:

1. **Observed Operator Facts** — facts read from visible game UI with evidence/provenance.
2. **Derived Operator Profile** — cautious interpretations computed from multiple observed facts over time.

The workflow/harness branch owns *how to navigate and perceive the UI*. This branch owns *what operator data means, how it is normalized, and what may be derived from it*.

## Core model

```text
VISIBLE GAME UI
   │
   ├── Governor Profile
   ├── More Info
   ├── Alliance
   ├── Alliance Members
   ├── event / KVK history surfaces
   └── other profile/statistic surfaces
   │
   ▼
OBSERVED OPERATOR FACTS
   │
   ├── identity
   ├── progression
   ├── alliance position
   ├── combat statistics
   ├── economy/resource statistics
   └── historical performance
   │
   ▼
DERIVATION LAYER
   │
   ├── role/authority context
   ├── progression shape
   ├── activity tendencies
   ├── combat/economy balance
   └── historical playstyle signals
   │
   ▼
OPERATOR PROFILE
```

The derived profile is not game truth. Every derived field must retain the facts and evidence it was derived from.

## Source priority

For operator facts:

```text
direct visible game observation
> repeated visible observation
> operator explanation
> derived inference
```

The official gameplay guide explains game mechanics, but personal/operator facts should preferably come from the player's actual visible profile/statistics.

## Acquisition surfaces trained so far

### Governor Profile

Visible fields include:

- governor name;
- character suffix/name used by operator (example training observation: `F15`);
- governor ID;
- civilization;
- alliance;
- current power;
- kill points;
- acclaim;
- highest acclaim;
- action points;
- achievement/event-history entry points visible on the profile.

### More Info

The More Info panel exposes more granular progression and behavioral statistics:

- overall power;
- relative kingdom percentile shown by UI;
- category ratings;
- building power;
- technology power;
- troop power;
- commander power;
- battle statistics such as highest power, victory, defeat, dead and scout times;
- resource statistics such as resources gathered, resource assistance and alliance help times.

These values are far more useful than asking the operator to describe their playstyle manually.

### Alliance Home

Visible alliance context includes:

- alliance name/tag;
- alliance power;
- leader;
- territory count;
- alliance gift level;
- member count/capacity.

### Alliance Members

The two-person/member button opens the member hierarchy surface.

The current training observation shows rank groups such as:

- Rank 4 (Officer);
- Rank 3;
- Rank 2;
- Rank 1;
- leader banner.

The acquisition goal is not merely to count ranks. AUTO_ROK should locate the current governor in this hierarchy (search or rank expansion through visible UI) and record the operator's actual alliance role/rank.

This role is important because it changes the operator's real position in the server/alliance and can later influence mission relevance and capability exposure.

## Personalization boundary

AUTO_ROK should collect game-provided information first.

Human input is reserved for information such as:

- personal objectives that are not represented by the game;
- subjective preferences;
- strategic priorities the statistics cannot establish safely;
- explicit approval/policy choices.

The system should not ask questions like "what is your power?" or "which alliance are you in?" when those facts are directly visible in the game.

## Derived profile examples

Derived dimensions may include:

```text
alliance_position
progression_distribution
combat_activity_signal
economy_support_signal
gathering_activity_signal
alliance_contribution_signal
historical_event_signal
```

Example: a high `resources_gathered` value is an observed fact. `gathering_activity_signal = high` is a derivation and must cite the observed statistic, comparison baseline, and derivation version.

Do not turn one statistic into a personality label.

## KVK / historical profile

KVK/event history should be treated as a temporal dataset rather than one static field.

Target model:

```text
operator_history
├── season/event id
├── kingdom/context
├── role/rank at that time (when observable)
├── power/progression snapshot
├── combat outcomes/statistics
├── resource/support statistics
└── derived behavioral signals
```

With enough periods, AUTO_ROK can infer a much stronger operating style than from the current profile alone.

The exact UI path for historical KVK data is still a training gap and must be learned from visible navigation rather than guessed.

## Relationship to the Harness branch

`agentic-harness-v1` continues to build:

- computer-use perception;
- mouse/keyboard actuation;
- task/workflow runtime;
- visual grounding;
- mission execution.

`operator-layer-v1` builds:

- operator fact schema;
- acquisition-source map;
- provenance;
- normalization;
- profile derivation contracts;
- historical snapshots.

After both branches stabilize, the harness will populate the Operator Layer through visible UI observations.

## V1 success criteria

Operator Layer V1 is successful when AUTO_ROK can construct a normalized operator snapshot from visible UI containing at minimum:

```text
identity
current progression
alliance identity
alliance role/rank
power breakdown
battle statistics
resource/support statistics
```

without asking the user to manually provide those game-visible facts.
