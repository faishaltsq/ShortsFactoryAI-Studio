from __future__ import annotations

from pathlib import Path

from packages.core.agents.concrete import MotionCoderAgent
from packages.core.contracts.artifacts import (
    CreativeMotionBriefArtifact,
    MotionCodeArtifact,
    StoryboardArtifact,
)
from packages.core.media.codeguard import CodeGuard


def test_motion_code_artifact_schema() -> None:
    assert CodeGuard is not None
    assert StoryboardArtifact is not None
    assert CreativeMotionBriefArtifact is not None
    raw = {
        "entry_component": "RootComposition",
        "files": {
            "RootComposition.tsx": "import React from 'react'; export const RootComposition = () => null;",
            "Scene01.tsx": "import React from 'react'; export const Scene01 = () => <div>Motion</div>;",
        },
        "dependencies": ["react", "remotion"],
        "skill_hashes": ["abc123hash"],
        "validated_by_codeguard": True,
    }
    art = MotionCodeArtifact.model_validate(raw)
    assert art.kind == "motion-code"
    assert art.entry_component == "RootComposition"
    assert "Scene01.tsx" in art.files
    assert art.validated_by_codeguard is True


def test_motion_coder_agent_sanitizes_and_validates_code() -> None:
    agent = MotionCoderAgent.__new__(MotionCoderAgent)
    payload = {
        "files": {
            "Scene01.tsx": "import React from 'react'; export const Scene01 = () => <div>Safe</div>;",
            "Bad.tsx": "import fs from 'fs';",
        }
    }
    sanitized = agent.sanitize_payload(payload)
    assert sanitized["validated_by_codeguard"] is False
    assert "issues" in sanitized or not sanitized["validated_by_codeguard"]


def test_motion_coder_agent_prompt_and_contract() -> None:
    from packages.core.agents import CallContext
    from packages.core.providers.base import Capability, ResolvedCall
    from packages.core.providers.mock import MockProvider

    call = ResolvedCall(
        provider="mock",
        transport="mock",
        base_url="",
        model="mock-1",
        temperature=None,
        max_tokens=None,
        timeout_s=5.0,
        max_retries=0,
        capabilities=frozenset({Capability.CHAT}),
        allow_private_hosts=False,
    )
    ctx = CallContext(call=call, provider=MockProvider())
    agent = MotionCoderAgent(ctx)
    assert agent.contract() == MotionCodeArtifact

    user_prompt = agent.build_user_prompt(
        storyboard={"scenes": []},
        creative_motion_brief={"art_direction": {}},
        visual_plan={"beats": []},
    )
    assert "RootComposition.tsx" in user_prompt

    sys_prompt = agent.system_prompt_for_task("motion_code")
    assert "Remotion" in sys_prompt


def test_build_stages_includes_motion_code_when_custom_renderer(tmp_path: Path) -> None:
    from packages.core.orchestration.jobstore import JobStore
    from packages.core.orchestration.pipeline import build_stages

    class DummyState:
        def __init__(self, store: JobStore) -> None:
            self.store = store

    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs")
    job = store.create(
        title="test",
        payload={
            "topic": "test",
            "render_video": True,
            "renderer": "custom-motion",
        },
    )
    stages = build_stages(DummyState(store), job.id)
    motion_stages = [s for s in stages if s.name == "MotionCoderAgent"]
    assert len(motion_stages) == 1
    assert motion_stages[0].contract_artifact == "motion-code.json"


def test_motion_coder_stage_writes_files_to_quarantined_workspace(tmp_path: Path) -> None:
    from apps.api.settings import Settings
    from apps.api.state import AppState
    from packages.core.contracts.state import JobState
    from packages.core.orchestration.pipeline import _dynamic_stage
    from packages.core.orchestration.runner import StageContext
    from packages.core.providers.usage import Budget

    settings = Settings(
        data_dir=tmp_path / "data",
        db_path=tmp_path / "data" / "factory.db",
        jobs_dir=tmp_path / "data" / "jobs",
        secrets_dir=tmp_path / "data" / "secrets",
        studio_config=tmp_path / "config" / "studio.json",
    ).ensure()
    state = AppState.build(settings, budget=Budget())
    job = state.store.create(
        title="test",
        payload={
            "topic": "test",
            "render_video": True,
            "renderer": "custom-motion",
            "provider_mode": "mock",
        },
    )
    stage = _dynamic_stage(
        state,
        agent_name="MotionCoderAgent",
        stage_state=JobState.STORYBOARD_READY,
        produces="motion-code.json",
        task="motion_code",
        kwargs_fn=lambda _s, _j: {},
    )
    staging = tmp_path / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    outcome = stage.run(StageContext(store=state.store, job_id=job.id, staging=staging))
    assert outcome.ok is True
    code_dir = state.store.job_dir(job.id) / "code"
    assert code_dir.is_dir()
    assert (code_dir / "RootComposition.tsx").is_file()
    assert (code_dir / "Scene01.tsx").is_file()
    assert "Safe Motion" in (code_dir / "Scene01.tsx").read_text(encoding="utf-8")


def test_motion_code_artifact_rejections() -> None:
    import pytest

    # Path traversal in filename
    with pytest.raises(ValueError, match="Path traversal"):
        MotionCodeArtifact.model_validate({
            "entry_component": "RootComposition",
            "files": {"../../evil.tsx": "export const Evil = () => null;"},
            "validated_by_codeguard": True,
        })

    # Unsupported extension
    with pytest.raises(ValueError, match="Unsupported file extension"):
        MotionCodeArtifact.model_validate({
            "entry_component": "RootComposition",
            "files": {"evil.exe": "binary content"},
            "validated_by_codeguard": True,
        })

    # Missing entry component in files
    with pytest.raises(ValueError, match="Entry component 'RootComposition' not found"):
        MotionCodeArtifact.model_validate({
            "entry_component": "RootComposition",
            "files": {"Scene01.tsx": "export const S = () => null;"},
            "validated_by_codeguard": True,
        })

    # Code failed CodeGuard
    with pytest.raises(ValueError, match="failed CodeGuard"):
        MotionCodeArtifact.model_validate({
            "entry_component": "RootComposition",
            "files": {"RootComposition.tsx": "import fs from 'fs';"},
            "validated_by_codeguard": False,
            "issues": ["forbidden import fs"],
        })


