# CHARACTER_SYSTEM — reusable, consistent, deterministic

## 1. Why this exists

Generating a fresh character image per frame or per scene produces a different person in every
shot. That is the single most common failure of AI animation. The fix is a rig: one asset,
many poses, deterministic transforms.

## 2. Model

```jsonc
{
  "id": "maya",
  "style": "flat-vector",
  "rig": { "version": 1, "skeleton": ["hips","spine","chest","neck","head","armL","armR","legL","legR"] },
  "parts": [{ "id": "head", "svg": "head.svg", "anchor": [0, 0], "z": 10 }],
  "palette": { "skin": "#e8b48c", "hair": "#2b2118", "shirt": "#2f6f6a" },
  "palette_hash": "…",
  "poses": ["stand", "walk", "sit", "point", "reach", "shrug", "lookUp"],
  "expressions": ["neutral", "happy", "sad", "surprised", "angry", "thinking", "curious", "concerned", "determined"],
  "motion": ["idle", "talk", "walk", "gesture", "react", "enter", "poseChange"],
  "mouth": { "shapes": ["closed","open","wide","round"], "viseme_map": {} },
  "clothing": [{ "id": "default" }, { "id": "jacket" }],
  "license": "original",
  "metadata": { "created_at": "…", "author": "operator" }
}
```

## 3. Consistency guarantees

- `palette_hash` and `rig_hash` are stored per scene in `assets.json`. A scene referencing a
  character whose hash differs from the storyboard's declaration fails validation. You cannot
  silently get a different Maya in scene 3.
- Poses are data (`angles` per joint), not images. Interpolation between poses is deterministic.
- Expressions are multipliers on neutral facial parameters (`mouthOpen`, `mouthWidth`,
  `browLift`, `eyeOpen`, `blush`), so blending two expressions is arithmetic, not a new asset.
- No per-frame image generation anywhere in the pipeline. The only generated images are
  optional backgrounds, and those are cached by prompt hash with a licence record.

## 4. Required animation capability → implementation

| Capability | Implementation |
| --- | --- |
| Idle | breathing + weight shift, seeded |
| Walking | pose cycle between `stand`/`walk` with contact timing |
| Talking | `talk` preset: mouth open/close driven by word-boundary timings from TTS |
| Blinking | procedural, 2–6 s randomized, never on a beat boundary |
| Thinking | `lookUp` pose + `thinking` expression + hand to chin |
| Pointing | `point` pose, arm angle targetable |
| Surprised / Happy / Sad / Angry | expression presets + a reactive pose |
| Object interaction | prop anchored to a hand joint (`Prop` with `fit="box"`) |
| Basic gestures | `gesture` preset with amplitude |

## 5. Mouth sync

TTS word boundaries give `(word, start, end)`. For each word the mouth cycles
`closed → open → closed` across the word's duration, with amplitude from word length. Visemes
are a Phase 3 refinement; amplitude-only sync is honest and reads correctly at 1080×1920.

## 6. Adding a character

1. Draw parts as SVG, one file per part, consistent viewBox.
2. Declare anchors and z-order in `manifest.ts`.
3. Provide the seven poses and nine expressions as data.
4. Add palette; run `npm run character:validate` (hash stability, missing anchors, palette
   contrast ≥ 4.5:1 against background).
5. Render the contact sheet (all poses × all expressions) and inspect it.

A character that fails contrast or has a missing anchor cannot be selected in the UI.

## 7. Current state

One character (`maya`) with 7 poses, 9 expressions, 7 motion presets, 4 mouth shapes. Adding a
second character is asset work, not engine work — that is the point of the rig.
