# ADR-0009 — `SceneSpec` gains `camera` and `motion`

**Status:** accepted

## Context
The donor's `SceneSpec` has no camera field; camera lives inside per-template `data`. "Purposeful
camera movement" therefore cannot be expressed in the contract and cannot be validated — every
template invents its own.

## Decision
Add `camera {shot, move, target, amplitude, ease}` and `motion {energy, continuity, beats[]}` to
`SceneSpec`, both required. A non-static `move` requires a `target` that resolves to an element in
the scene.

## Consequences
"Unmotivated camera movement" becomes a schema error. Templates gain a uniform motion vocabulary.
Cost: all seven compositions must consume the new fields, and old storyboards need a migration
(`camera.move = "static"`).
