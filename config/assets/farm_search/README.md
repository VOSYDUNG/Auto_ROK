# Farm Search calibration crops

Six measured UI control crops used by `config/farm_search_visual.json` are
tracked so a Git checkout can load the canonical detector without local capture
history. The profile owns each crop's SHA-256, source frame hash, audit-only crop
bounds, layout and matching policy. Full source frames remain local evidence.

These assets establish surface recognition only. They provide no click authority,
live completion claim or support for an uncalibrated layout. Changing a crop
requires updating its calibration and verifying positives and refusal cases.
