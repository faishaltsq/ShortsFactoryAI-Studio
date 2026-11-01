# ADR 0013 — Objects explain the story; the character engine is retired

Status: accepted (migration implemented in this change)
Supersedes: ADR 0007 (two renderers), ADR 0012 (bang-motion HTML emission), and the character half of ADR 0009

## Context

The studio produced Shorts by rendering a rigged cartoon presenter (`maya`) in front of a
backdrop. The presenter was the only thing on screen; the narration was the only thing carrying
information. That is the format the brief rejected: "not a cartoon person standing beside text that
repeats the narration".

The product is now an informative short-form engine covering technology, AI, hardware, software,
startups, infrastructure, science and education. A video about a GPU cluster has to show a GPU
cluster.

## Decision

**Objects explain the story. Motion explains the objects. Narration provides the context.**

1. `packages/video/src/character/**` is deleted, together with `art/Figure.tsx` (the procedural
   human), `motion-beats.ts` (pose/gesture/expression performance), `speech.ts` (mouth envelope),
   and the `CharacterSheet` / `CharacterReel` compositions. None of it is kept to make an obsolete
   test pass.

2. `IllustratedStory` is retired. It was character-driven end to end — actors, poses, expressions,
   lip sync — and could not be repurposed. Its replacement is **`ObjectExplainer`**, plus two new
   informative templates: **`ProcessFlow`** (a staged chain whose order is the explanation) and
   **`MetricShift`** (a quantity that grows while its number counts).

3. The visual vocabulary is a library, not a rig: `packages/video/src/art/objects.tsx` draws fifteen
   objects (`gpu`, `wafer`, `serverRack`, `dataCenter`, `neuralNet`, `database`, `satellite`,
   `antenna`, `turbine`, `solarPanel`, `coolingFan`, `phone`, `drone`, `rocket`, `building`). Each
   entry satisfies one contract, `(palette, frame) -> SVG`, and animates its own parts.

4. A storyboard names *things*, not people. `scene.data` for an explainer is
   `{environment, objects[], callouts[], flows[]}`; there is no pose, no expression, no mouth.

5. `scene.motion.beats[]` now drives object highlights in `ObjectExplainer` (`object:<n>` or an
   object's kind/label selects it). Before this, the field was validated and then ignored by every
   renderer — motion in the document, nothing on screen.

6. The second renderer (`bang-motion`, `packages/core/motion/emit.py`) is deleted. It existed to
   capture character SVG frames; keeping it would keep a character engine alive under another name.
   `RENDERERS == ("remotion",)`.

7. `AssetsArtifact.characters` becomes `AssetsArtifact.objects`: one record per object kind the
   storyboard names, each with the library and palette digests that draw it.

## What did not change

The **interactive 3D agent office** (`apps/dashboard/src/three/**`) is untouched. Its characters are
visual representations of *software agents* in a monitoring UI, not presenters in an exported film,
and it imports nothing from `packages/video`. `tests/test_architecture.py` now fails the build if
that ever becomes false, so the office cannot be collaterally retired by video work.

## Consequences

- A topic with no matching keyword still gets a real stage: `fill_explainer` falls back to a
  generic technical trio rather than a blank backdrop, because an empty frame is the failure this
  engine exists to prevent.
- The QC gate's `object_consistency` check replaces `character_consistency`. Its vocabulary is
  imported from `packages/core/contracts/scene.py`, and `tests/test_architecture.py` proves the
  TypeScript library and the Python contract list agree kind-for-kind.
- Adding an object is now a library change plus one line in `OBJECT_KINDS` — no rig, no manifest,
  no per-template vocabulary.
