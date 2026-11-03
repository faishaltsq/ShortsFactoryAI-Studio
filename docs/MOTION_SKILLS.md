# MOTION_SKILLS — registry and the Bang Motion integration

## 1. Registry

```python
@dataclass(frozen=True)
class MotionSkill:
    id: str                     # "bang-motion"
    version: str                # "1.19.0"
    description: str
    styles: tuple[str, ...]     # ("explainer", "opener", "kinetic", "kartun", "sketsa")
    renderer: str               # "bang-motion"
    requires: frozenset[str]    # {"gsap", "browser"}
    input_contract: type        # MotionBrief
    output_contract: type       # FrameSequence
    validate: Callable[[Path], list[str]]
    license: str                # "MIT"
    source: str                 # upstream URL + commit
```

`MotionSkillRegistry` lists installed skills, their capabilities, and which templates can use
them. The Skills page in the dashboard shows: id, version, styles, renderer, required
capabilities, install path, license, and last validation result.

## 2. Bang Motion — verified facts

Inspected at commit `c1aa65e` (v1.19.0), MIT, © 2026 Bang Tutorial.

| Item | Finding |
| --- | --- |
| Size | 45 files; `SKILL.md` 551 lines; `references/` 2 540 lines |
| Contract | `window.OPENER = { W, H, DURATION, tl, ready, seek(t), seekFrame(t), clipsReady(), play() }` |
| Frame export | `scripts/export-frames.mjs` — set time, await 2× rAF, screenshot. Not screen recording. |
| Snapshot tool | `scripts/snap.mjs` — freeze at key seconds for visual verification |
| Starters | 7 HTML files, 1920×1080 stage |
| 9:16 recipe | `references/explainer.md`: stage 1080×1920, title 88–168 px, `.safe` at scale .78, per-word spans |
| External deps | GSAP 3.12.5 (cdnjs), Google Fonts, three.js 0.161 (jsdelivr) — **all CDN** |
| Licence | MIT; GSAP is free for commercial use since 3.13 (Webflow relicensed 2025) |

## 3. What we take, and what we do not

**Take:** the design law. `references/anti-ppt.md` is a table of concrete failure modes with
concrete fixes — "kicker + 2-line title + 2-line body + 4 chips" is a slide, not a shot; every
opener ending in a period reads as a template; a static background with text fading in and out
is a presentation. These become validation rules in `packages/core/motion/rules.py`, applied to
every storyboard regardless of renderer.

**Take:** the frame-export technique and the `OPENER` contract as the secondary renderer's
interface.

**Do not take:** the CDN dependency (breaks offline and reproducibility), the 1920×1080 default
(we are 1080×1920), and the assumption that the skill generates Remotion components — it does
not, and pretending otherwise would mean executing generated HTML inside the dashboard.

---

### 3.1 Remotion skill reference — selection, budget, provenance

The Remotion skills in `.agents/skills/` are a different thing from the Bang Motion registry: they
are prompt reference for `MotionCoderAgent`, loaded by `packages/core/agents/skill_loader.py`.

| Concern | Behaviour |
| --- | --- |
| Selection | `MotionSkillLoader.rank(needs, limit)` — weighted term overlap over each skill's name (×5), its declared frontmatter `description` (×3), its markdown headings (×2) and its body (×1); ties broken by name so two runs select identically |
| Needs | `MotionCoderAgent._shot_needs` builds the free text from what the *shots* declare (scene type, purpose, action, environment, camera move/framing, continuity, subjects, primitives) plus the brief's motion/camera/typography language — never from the narration topic, because a skill that teaches an SVG path reveal is not chosen by the word "submarine" |
| Always | `remotion-best-practices` is the router that names every other skill, so it is always included |
| Budget | `studio.json` → `motion.skill_tokens` (default 3000) and `motion.skill_limit` (default 4), passed to the agent as prompt kwargs from `AppState.motion_policy`. A fixed budget for every request, applied to every installed skill, is what this replaces |
| Provenance | `SkillBundle.skill_hashes` maps each sent skill to the sha256 of the **portion actually sent**, and `MotionCoderAgent.sanitize_payload` writes `<skill>:<sha256>` into `motion-code.json`. A skill truncated to fit the budget is recorded as the truncated version |
| Not from the model | The model's own `skill_hashes` list is discarded. A list echoed by the model is a claim about its context; a digest computed here is a record of it |

Section-level retrieval inside a skill is deliberately not implemented: every `SKILL.md` here is
1–13 KB, so the whole file fits a normal budget and splitting it would add a parser without changing
what the model reads. Revisit if a skill outgrows the per-request budget.

## 4. Ingest procedure

1. Clone at a pinned tag into `vendor/bang-motion/<version>/` (git submodule-free: a script
   copies and records the commit).
2. Rewrite every `https://cdn…` and `https://fonts…` reference to `./vendor/…`, downloading
   GSAP and the required font subsets once into the skill directory.
3. Verify: no remaining `http://` or `https://` reference in any `assets/*.html`
   (`grep -c` must be 0 except in comments and the license header).
4. Record `manifest.json`: version, commit, file hashes, licence text hash.
5. Run the skill's own `snap.mjs` equivalent against one starter at 1080×1920 and inspect the
   stills. If the vertical stage does not lay out correctly, the skill is marked
   `vertical: unsupported` and cannot be selected for Shorts — an honest limitation, not a
   silent stretch.

## 5. Style brief

Before any motion code is written, the `AnimationAgent` emits a style brief: palette (derived
from the topic, not from a template), two fonts with different character, a signature move, a
background language, and a transition vocabulary (≥ 2 kinds, ≥ 1 with depth). The brief is
validated: a palette of one colour, or a signature move identical to the previous video's,
fails. This is the mechanism that stops "every video looks the same".
