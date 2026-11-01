# Remotion Data-Driven Template Architecture & High-Retention Shorts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement data-driven vertical video automation in Remotion and Python orchestrator featuring dynamic metadata duration, word-level spring pop-up TikTok/Reels captions, safe zone enforcement (1080x1920), Ken Burns continuous micro-motion, and distinct visual/overlay layer separation.

**Architecture:** Extend backend audio contracts and TTS synthesis (`packages/core/media/tts.py`) to persist word-level timestamps (`WordTimestamp`) into `audio.json` and `render-props.json`. In the Remotion renderer (`packages/video`), build a high-retention `TiktokCaptions.tsx` component with spring pop-in, active word pill highlight, and strict safe zone padding (top >= 220px, bottom >= 460px, right >= 140px, left >= 60px). Mount captions and audio on a dedicated top `<AbsoluteFill>` overlay in `Short.tsx` above visual scene sequences, with `calculateMetadata` dynamically sizing composition frames.

**Tech Stack:** Python 3.12 (Pydantic v2, pytest), TypeScript 5.6, React 18, Remotion 4.0 (`useCurrentFrame`, `spring`, `interpolate`, `calculateMetadata`, `AbsoluteFill`, `Audio`).

**Spec:** Gemini Argon Video Automation Architecture recommendations (Data-Driven Remotion Template, Word-Level Timestamps with Spring Pop-In, 1080x1920 UI Safe Zones, Multi-Scene Transition Duration Overlap, Layer Separation, Ken Burns Micro-Motion, Headless CLI Render).

## Global Constraints

- **Deterministic Remotion Motion:** All animations must be driven strictly by `useCurrentFrame()`, `spring()`, and `interpolate()`. No CSS transitions, no keyframes, no browser timers (`setTimeout`, `setInterval`, `requestAnimationFrame`).
- **Always Clamp Interpolations:** Every `interpolate()` call must include `{ extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }`.
- **Vertical Safe Zones:** Critical text and interactive elements must observe 1080x1920 boundaries: top >= 220px, bottom >= 460px, right >= 140px, left >= 60px.
- **Contract Integrity & Layering:** Backend changes in `packages/core/**` must adhere to Pydantic v2 validation; `packages/video` remains reached solely through the subprocess boundary in `packages/core/media/render.py`.
- **No Degradation of Existing Compositions:** The 11 existing templates and fallback phrase-level `Subtitles.tsx` must remain valid and operational when word timestamps are absent.

## Review Focus

1. **Missing or Corrupt Word Timestamps:** When TTS provides empty or degraded word boundaries, `TiktokCaptions` must gracefully fall back to sentence cues or render nothing without throwing unhandled exceptions.
2. **Transition Frame Overlaps in Duration:** Total composition frames must strictly equal `sum(scenes.durationInFrames) - sum(transition_overlaps)` so audio tracks and visual transitions never desynchronize.
3. **Safe Zone Clipping on Varied Screen Devices:** Captions must stay within the horizontal bounds (max width ~960px) and bottom padding (460px) so TikTok/Reels/Shorts bottom banners and right action icons never obscure spoken words.
4. **Spring Timing Offset Precision:** Spring animations for word and page pop-in must compute frame offsets relative to the page/word start frame (`frame - startFrame`) clamped to non-negative values.
5. **Memory and Concurrency Safety:** CLI render commands must pass explicit `--port` and absolute `--props` paths to prevent Windows port collisions or blank renders.

---

### Task 1: Backend Data Contracts & Word Timestamp Serialization

**Files:**
- Modify: `packages/core/contracts/scene.py:204-235`
- Modify: `packages/core/contracts/artifacts.py:213-245`
- Modify: `packages/core/media/tts.py:1240-1285`
- Modify: `packages/core/media/render.py:278-320`
- Test: `tests/test_audio_timing.py`

**Interfaces:**
- Consumes: `WordBoundary(text, start_ms, end_ms)` in `packages/core/media/tts.py`.
- Produces: `WordTimestamp(word: str, startMs: int, endMs: int)` exported from `packages/core/contracts/scene.py` and included in `AudioArtifact.words` and `render-props.json` (`captions`).

- [ ] **Step 1: Write the failing test for word timestamp schema and serialization**

Add test in `tests/test_audio_timing.py`:

```python
def test_audio_artifact_retains_word_timestamps() -> None:
    from packages.core.contracts.scene import WordTimestamp
    from packages.core.contracts.artifacts import AudioArtifact

    wt = WordTimestamp(word="Halo", startMs=0, endMs=450)
    assert wt.word == "Halo"
    assert wt.startMs == 0
    assert wt.endMs == 450

    artifact = AudioArtifact(
        narration={"src": "narration.wav", "durationMs": 1000, "voice": "id-ID-ArdiNeural"},
        scenes=[{"sceneId": "sc1", "startMs": 0, "endMs": 1000}],
        subtitles=[{"startMs": 0, "endMs": 1000, "text": "Halo dunia"}],
        words=[wt, WordTimestamp(word="dunia", startMs=460, endMs=980)],
        mix={},
    )
    assert len(artifact.words) == 2
    assert artifact.words[1].word == "dunia"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_audio_timing.py -k test_audio_artifact_retains_word_timestamps -v`
Expected: FAIL with `cannot import name 'WordTimestamp'` or `extra fields not permitted`.

- [ ] **Step 3: Implement WordTimestamp model and AudioArtifact integration**

In `packages/core/contracts/scene.py`:
```python
class WordTimestamp(BaseModel):
    model_config = ConfigDict(extra="forbid")

    word: str = Field(min_length=1, max_length=120)
    startMs: int = Field(ge=0)
    endMs: int = Field(gt=0)

    @model_validator(mode="after")
    def _ordered(self) -> WordTimestamp:
        if self.endMs <= self.startMs:
            raise ValueError("word timestamp endMs must be greater than startMs")
        return self
```

In `packages/core/contracts/artifacts.py`:
Add `words: list[WordTimestamp] = Field(default_factory=list)` to `AudioArtifact`.

In `packages/core/media/tts.py`:
When building `AudioArtifact`, populate `words`:
```python
artifact_words = [
    WordTimestamp(word=w.text, startMs=w.start_ms + start_ms, endMs=w.end_ms + start_ms)
    for w in rebased
]
```

In `packages/core/media/render.py` (`update_storyboard_from_audio`):
Forward `audio.get("words", [])` into `timed["captions"] = audio.get("words", [])`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_audio_timing.py tests/test_contracts_scene.py -v`
Expected: PASS (all tests pass, 0 failed).

- [ ] **Step 5: Commit changes**

```bash
git add packages/core/contracts/scene.py packages/core/contracts/artifacts.py packages/core/media/tts.py packages/core/media/render.py tests/test_audio_timing.py
git commit -m "feat(core): persist word-level timestamps in audio artifact and render props"
```

---

### Task 2: Video Package Types & Product Adapter for Captions

**Files:**
- Modify: `packages/video/src/types.ts:160-195`
- Modify: `packages/video/src/product-adapter.ts:370-425`
- Test: `packages/video/scripts/test-adapter.mjs`

**Interfaces:**
- Consumes: `captions?: Array<{word: string; startMs?: number; endMs?: number; start?: number; end?: number}>` from props.
- Produces: `StoryboardSpec.captions: WordTimestamp[]` in seconds/ms format for Remotion components.

- [ ] **Step 1: Write the failing test for captions in test-adapter.mjs**

Add test in `packages/video/scripts/test-adapter.mjs`:

```javascript
test('captions with word timestamps adapt to normalized seconds and milliseconds', () => {
  const raw = {
    ...productFixture,
    captions: [
      {word: 'Halo', startMs: 100, endMs: 500},
      {word: 'Teman', startMs: 520, endMs: 950},
    ],
  };
  const adapted = adaptProductStoryboard(raw);
  assert(Array.isArray(adapted.captions), 'adapted.captions must be an array');
  assert.equal(adapted.captions.length, 2);
  assert.equal(adapted.captions[0].word, 'Halo');
  assert.equal(adapted.captions[0].startMs, 100);
  assert.equal(adapted.captions[0].endMs, 500);
  assert.equal(adapted.captions[0].start, 0.1);
  assert.equal(adapted.captions[0].end, 0.5);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node packages/video/scripts/test-adapter.mjs`
Expected: FAIL with `adapted.captions must be an array` or `undefined`.

- [ ] **Step 3: Implement WordTimestamp and adapter logic**

In `packages/video/src/types.ts`:
```typescript
export interface WordTimestamp {
  word: string;
  startMs: number;
  endMs: number;
  start: number; // in seconds (for direct Remotion time math)
  end: number;   // in seconds
}

export interface StoryboardSpec {
  // existing fields...
  subtitles: SubtitleCue[];
  captions?: WordTimestamp[];
  // existing fields...
}
```

In `packages/video/src/product-adapter.ts`:
Add `adaptCaptions` function:
```typescript
const adaptCaptions = (raw: unknown): WordTimestamp[] => {
  if (!raw || !Array.isArray(raw)) return [];
  return raw.map((item) => {
    const word = String(item.word || item.text || '');
    const startMs = typeof item.startMs === 'number' ? item.startMs : Math.round((item.start ?? 0) * 1000);
    const endMs = typeof item.endMs === 'number' ? item.endMs : Math.round((item.end ?? 0) * 1000);
    return {
      word,
      startMs,
      endMs,
      start: Number((startMs / 1000).toFixed(3)),
      end: Number((endMs / 1000).toFixed(3)),
    };
  });
};
```
Map `captions: adaptCaptions(storyboard.captions)` inside `adaptProductStoryboard`.

- [ ] **Step 4: Run test and typecheck to verify it passes**

Run: `node packages/video/scripts/test-adapter.mjs && npm --prefix packages/video run typecheck`
Expected: PASS with 0 failures and 0 type errors.

- [ ] **Step 5: Commit changes**

```bash
git add packages/video/src/types.ts packages/video/src/product-adapter.ts packages/video/scripts/test-adapter.mjs
git commit -m "feat(video): add WordTimestamp contract and adapter support for captions"
```

---

### Task 3: High-Retention Auto-Caption Component (`TiktokCaptions.tsx`)

**Files:**
- Create: `packages/video/src/components/TiktokCaptions.tsx`
- Create: `packages/video/scripts/test-captions.mjs`
- Modify: `packages/video/package.json`

**Interfaces:**
- Consumes: `words: WordTimestamp[]`, `wordsPerPage?: number`, `highlightColor?: string`.
- Produces: React component rendering chunked captions with spring page pop-in, active word scale boost, and pill highlight inside 1080x1920 safe zone.

- [ ] **Step 1: Write the test script for caption pagination and active word matching**

Create `packages/video/scripts/test-captions.mjs`:

```javascript
import assert from 'node:assert/strict';

export function paginateWords(words, wordsPerPage = 4) {
  const pages = [];
  for (let i = 0; i < words.length; i += wordsPerPage) {
    const chunk = words.slice(i, i + wordsPerPage);
    if (chunk.length > 0) {
      pages.push({
        start: chunk[0].start,
        end: chunk[chunk.length - 1].end,
        words: chunk,
      });
    }
  }
  return pages;
}

const sampleWords = [
  { word: 'AI', start: 0.1, end: 0.4 },
  { word: 'bisa', start: 0.45, end: 0.7 },
  { word: 'memprediksi', start: 0.75, end: 1.2 },
  { word: 'masa', start: 1.25, end: 1.5 },
  { word: 'depan', start: 1.55, end: 1.9 },
];

const pages = paginateWords(sampleWords, 4);
assert.equal(pages.length, 2, 'should split into 2 pages');
assert.equal(pages[0].words.length, 4);
assert.equal(pages[1].words.length, 1);
assert.equal(pages[0].start, 0.1);
assert.equal(pages[0].end, 1.5);
console.log('PASS test-captions pagination logic');
```

- [ ] **Step 2: Run test to verify logic**

Run: `node packages/video/scripts/test-captions.mjs`
Expected: PASS test-captions pagination logic.

- [ ] **Step 3: Implement TiktokCaptions.tsx**

Create `packages/video/src/components/TiktokCaptions.tsx`:

```tsx
import React, { useMemo } from 'react';
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import type { WordTimestamp } from '../types';

export interface TiktokCaptionsProps {
  words: WordTimestamp[];
  wordsPerPage?: number;
  highlightColor?: string;
  fontFamily?: string;
}

interface CaptionPage {
  start: number;
  end: number;
  words: WordTimestamp[];
}

export const TiktokCaptions: React.FC<TiktokCaptionsProps> = ({
  words,
  wordsPerPage = 4,
  highlightColor = '#facc15',
  fontFamily = 'Montserrat, Inter, system-ui, sans-serif',
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const currentTime = frame / fps;

  const pages = useMemo<CaptionPage[]>(() => {
    if (!words || words.length === 0) return [];
    const result: CaptionPage[] = [];
    for (let i = 0; i < words.length; i += wordsPerPage) {
      const chunk = words.slice(i, i + wordsPerPage);
      if (chunk.length > 0) {
        result.push({
          start: chunk[0].start,
          end: chunk[chunk.length - 1].end,
          words: chunk,
        });
      }
    }
    return result;
  }, [words, wordsPerPage]);

  const activePage = pages.find(
    (p) => currentTime >= p.start && currentTime <= p.end + 0.15
  );

  if (!activePage) return null;

  const pageStartFrame = Math.max(0, Math.floor(activePage.start * fps));
  const pagePop = spring({
    frame: Math.max(0, frame - pageStartFrame),
    fps,
    config: { damping: 14, stiffness: 180, mass: 0.6 },
  });

  const pageScale = interpolate(pagePop, [0, 1], [0.85, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <AbsoluteFill
      style={{
        justifyContent: 'flex-end',
        alignItems: 'center',
        paddingBottom: 460, // Clear of TikTok/Reels description & audio marquee
        paddingLeft: 60,
        paddingRight: 140, // Clear of Like/Comment/Share buttons
        pointerEvents: 'none',
      }}
    >
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          justifyContent: 'center',
          gap: '12px 16px',
          transform: `scale(${pageScale})`,
          maxWidth: 920,
        }}
      >
        {activePage.words.map((item, idx) => {
          const isCurrentWord =
            currentTime >= item.start && currentTime <= item.end;

          const wordStartFrame = Math.max(0, Math.floor(item.start * fps));
          const wordSpring = spring({
            frame: Math.max(0, frame - wordStartFrame),
            fps,
            config: { damping: 12, stiffness: 220, mass: 0.5 },
          });

          const wordScale = isCurrentWord
            ? interpolate(wordSpring, [0, 1], [1, 1.14], {
                extrapolateLeft: 'clamp',
                extrapolateRight: 'clamp',
              })
            : 1;

          return (
            <span
              key={`${item.start}-${idx}`}
              style={{
                display: 'inline-block',
                fontFamily,
                fontSize: 62,
                fontWeight: 900,
                textTransform: 'uppercase',
                color: isCurrentWord ? '#0f172a' : '#ffffff',
                backgroundColor: isCurrentWord ? highlightColor : 'transparent',
                padding: '6px 18px',
                borderRadius: 16,
                transform: `scale(${wordScale})`,
                textShadow: isCurrentWord
                  ? 'none'
                  : '0px 4px 14px rgba(0, 0, 0, 0.9), 0px 2px 4px rgba(0, 0, 0, 0.95)',
                boxShadow: isCurrentWord
                  ? `0px 8px 24px ${highlightColor}66`
                  : 'none',
              }}
            >
              {item.word}
            </span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
```

- [ ] **Step 4: Verify typecheck**

Run: `npm --prefix packages/video run typecheck`
Expected: PASS (0 errors).

- [ ] **Step 5: Commit changes**

```bash
git add packages/video/src/components/TiktokCaptions.tsx packages/video/scripts/test-captions.mjs
git commit -m "feat(video): add TiktokCaptions component with spring animation and safe zone boundaries"
```

---

### Task 4: Safe Zone Overlay & Ken Burns Continuous Micro-Motion

**Files:**
- Create: `packages/video/src/components/SafeZoneOverlay.tsx`
- Create: `packages/video/src/components/KenBurnsContainer.tsx`
- Create: `packages/video/scripts/test-motion-utils.mjs`

**Interfaces:**
- `SafeZoneOverlay`: Dev-mode visual helper rendering vertical safe margin outlines (220px top, 460px bottom, 140px right, 60px left).
- `KenBurnsContainer`: Wraps scene background visual assets with continuous scale (`1.0` -> `1.07`) over scene duration to eliminate static deadness.

- [ ] **Step 1: Write test for Ken Burns scale calculations**

Create `packages/video/scripts/test-motion-utils.mjs`:

```javascript
import assert from 'node:assert/strict';

export function calculateKenBurnsScale(frame, totalFrames, maxScale = 1.07) {
  const progress = Math.min(1, Math.max(0, frame / Math.max(1, totalFrames)));
  return 1.0 + progress * (maxScale - 1.0);
}

assert.equal(calculateKenBurnsScale(0, 300), 1.0);
assert.equal(Number(calculateKenBurnsScale(150, 300).toFixed(4)), 1.035);
assert.equal(Number(calculateKenBurnsScale(300, 300).toFixed(2)), 1.07);
console.log('PASS test-motion-utils scale calculation');
```

- [ ] **Step 2: Run test to verify logic**

Run: `node packages/video/scripts/test-motion-utils.mjs`
Expected: PASS test-motion-utils scale calculation.

- [ ] **Step 3: Implement SafeZoneOverlay and KenBurnsContainer**

Create `packages/video/src/components/SafeZoneOverlay.tsx`:

```tsx
import React from 'react';
import { AbsoluteFill } from 'remotion';

export const SafeZoneOverlay: React.FC<{ visible?: boolean }> = ({ visible = false }) => {
  if (!visible) return null;
  return (
    <AbsoluteFill style={{ pointerEvents: 'none', zIndex: 9999 }}>
      {/* Top UI blocked area */}
      <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 220, backgroundColor: 'rgba(239, 68, 68, 0.25)', borderBottom: '2px dashed #ef4444' }}>
        <span style={{ color: '#ffffff', fontSize: 24, padding: 8, display: 'inline-block', backgroundColor: '#ef4444' }}>Top UI Blocked (220px)</span>
      </div>
      {/* Bottom UI blocked area */}
      <div style={{ position: 'absolute', bottom: 0, left: 0, right: 0, height: 460, backgroundColor: 'rgba(239, 68, 68, 0.25)', borderTop: '2px dashed #ef4444' }}>
        <span style={{ color: '#ffffff', fontSize: 24, padding: 8, display: 'inline-block', backgroundColor: '#ef4444' }}>Bottom UI Blocked (460px)</span>
      </div>
      {/* Right action buttons blocked area */}
      <div style={{ position: 'absolute', top: 220, bottom: 460, right: 0, width: 140, backgroundColor: 'rgba(245, 158, 11, 0.25)', borderLeft: '2px dashed #f59e0b' }}>
        <span style={{ color: '#ffffff', fontSize: 20, padding: 6, writingMode: 'vertical-rl', display: 'inline-block' }}>Right Buttons (140px)</span>
      </div>
      {/* Safe viewport bounds */}
      <div style={{ position: 'absolute', top: 220, bottom: 460, left: 60, right: 140, border: '2px solid #10b981' }} />
    </AbsoluteFill>
  );
};
```

Create `packages/video/src/components/KenBurnsContainer.tsx`:

```tsx
import React from 'react';
import { AbsoluteFill, interpolate, useCurrentFrame } from 'remotion';

export interface KenBurnsContainerProps {
  durationInFrames: number;
  maxScale?: number;
  children: React.ReactNode;
}

export const KenBurnsContainer: React.FC<KenBurnsContainerProps> = ({
  durationInFrames,
  maxScale = 1.07,
  children,
}) => {
  const frame = useCurrentFrame();
  const scale = interpolate(frame, [0, Math.max(1, durationInFrames)], [1, maxScale], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <AbsoluteFill style={{ transform: `scale(${scale})`, transformOrigin: 'center center' }}>
      {children}
    </AbsoluteFill>
  );
};
```

- [ ] **Step 4: Verify typecheck**

Run: `npm --prefix packages/video run typecheck`
Expected: PASS (0 errors).

- [ ] **Step 5: Commit changes**

```bash
git add packages/video/src/components/SafeZoneOverlay.tsx packages/video/src/components/KenBurnsContainer.tsx packages/video/scripts/test-motion-utils.mjs
git commit -m "feat(video): add SafeZoneOverlay and KenBurnsContainer components"
```

---

### Task 5: Mount TiktokCaptions, Layer Separation, and Dynamic Metadata in `Short.tsx`

**Files:**
- Modify: `packages/video/src/compositions/Short.tsx:1-80`
- Modify: `packages/video/src/storyboard-props.ts:100-116`
- Modify: `packages/video/src/Root.tsx:28-35`
- Test: `packages/video/scripts/test-render-props.mjs`

**Interfaces:**
- Layer 1: Visual sequences in `<Sequence>` with `TransitionedScene`.
- Layer 2: Global overlay in `<AbsoluteFill>` holding master `<Audio>`, `<TiktokCaptions>` (or fallback `<Subtitles>`), and progress bar.
- `calculateShortMetadata`: Ensures `durationInFrames` dynamically matches the total length.

- [ ] **Step 1: Write test for Short render props with captions**

In `packages/video/scripts/test-render-props.mjs`:
Add assertion that `Short` mounts successfully with `captions` property and calculates metadata duration.

- [ ] **Step 2: Run test to verify current state**

Run: `node packages/video/scripts/test-render-props.mjs`
Expected: PASS.

- [ ] **Step 3: Update Short.tsx to mount TiktokCaptions in overlay layer**

In `packages/video/src/compositions/Short.tsx`:
Import `TiktokCaptions` from `../components/TiktokCaptions`.
Render `TiktokCaptions` when `storyboard.captions` has items, otherwise fall back to `Subtitles`:

```tsx
{storyboard.captions && storyboard.captions.length > 0 ? (
  <TiktokCaptions
    words={storyboard.captions}
    highlightColor={theme.accent || '#facc15'}
    fontFamily={theme.fontHeading}
  />
) : (
  <Subtitles cues={storyboard.subtitles ?? []} theme={theme} currentFrame={frame} fps={fps} bottom={460} />
)}
```

Also update fallback `Subtitles.tsx` bottom default from `360` to `460` to adhere to the safe zone standard.

- [ ] **Step 4: Verify typecheck and adapter tests**

Run: `npm --prefix packages/video run typecheck && node packages/video/scripts/test-adapter.mjs`
Expected: PASS (0 errors).

- [ ] **Step 5: Commit changes**

```bash
git add packages/video/src/compositions/Short.tsx packages/video/src/components/Subtitles.tsx packages/video/src/storyboard-props.ts packages/video/scripts/test-render-props.mjs
git commit -m "feat(video): integrate TiktokCaptions in Short overlay with safe zone alignment"
```

---

### Task 6: End-to-End Headless CLI Render Verification & Quality Gate

**Files:**
- Test: `packages/video/scripts/still-smoke.mjs`
- Test: `tests/test_audio_timing.py`
- Test: `tests/test_contracts_scene.py`

**Interfaces:**
- Verifies that `remotion render` / `remotion still` headless CLI executes cleanly with `--props=<absolute_path>` and `--port=<free_port>`.

- [ ] **Step 1: Run complete backend test suite for audio and contracts**

Run: `uv run pytest tests/test_audio_timing.py tests/test_contracts_scene.py tests/test_mock_storyboard.py -v`
Expected: PASS (all tests pass).

- [ ] **Step 2: Run video adapter, render-props, and captions test scripts**

Run:
```bash
node packages/video/scripts/test-adapter.mjs
node packages/video/scripts/test-captions.mjs
node packages/video/scripts/test-motion-utils.mjs
node packages/video/scripts/test-render-props.mjs
```
Expected: All PASS with 0 failures.

- [ ] **Step 3: Run full typecheck across both packages**

Run:
```bash
npm --prefix packages/video run typecheck
npm --prefix apps/dashboard run typecheck
```
Expected: Both exit 0 with 0 errors.

- [ ] **Step 4: Commit changes and mark phase complete**

```bash
git status --short
git commit -m "chore: verify Remotion data-driven template architecture with high-retention captions"
```
