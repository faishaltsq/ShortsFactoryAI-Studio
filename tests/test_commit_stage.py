"""commit_stage: multi-artifact promotion under one live-lease check.

The property under test: a worker whose lease is gone (lost or expired) must not be able to
promote canonical files or advance state; a live worker commits every artifact and the state
marker together; and a rejected commit leaves the job exactly as it was.
"""
from __future__ import annotations

import datetime as dt

import pytest

from packages.core.contracts.state import JobState
from packages.core.orchestration.jobstore import JobStore
from packages.core.orchestration.leases import LeaseKeeper, LeaseLost


@pytest.fixture
def store(tmp_path):
    return JobStore(tmp_path / "factory.db", tmp_path / "jobs")


def _at_approving(store: JobStore, job_id: str) -> None:
    for target in (
        JobState.TOPIC_SELECTED,
        JobState.RESEARCH_COMPLETE,
        JobState.SCRIPT_GENERATED,
        JobState.CREATIVE_REVIEW,
        JobState.STORYBOARD_READY,
        JobState.ASSETS_READY,
        JobState.AUDIO_READY,
        JobState.MOTION_READY,
        JobState.RENDERING,
        JobState.TECHNICAL_QC,
        JobState.EDITORIAL_QC,
        JobState.READY_FOR_APPROVAL,
    ):
        store.transition(job_id, target)
    # APPROVED refuses without gate evidence; seed a minimal valid gate result.
    store.write_artifact(
        job_id,
        "render.json",
        {"sha256": "a" * 64},
    )
    store.write_artifact(
        job_id,
        "approval.json",
        {
            "decision": "approved",
            "operator": "test",
            "checks": {"publishable": True},
            "render_sha256": "a" * 64,
        },
    )
    store.transition(job_id, JobState.APPROVED)


def test_commit_stage_promotes_all_artifacts_and_state(store):

    job_id = store.create(title="c").id
    _at_approving(store, job_id)
    keeper = LeaseKeeper(store.db_path)
    keeper.acquire(job_id)

    payload = {"thumb": {"path": "thumb.png", "sha256": "x"}}
    record = store.commit_stage(
        job_id,
        token=keeper.token,
        json_artifacts=[("metadata", payload)],
        target=JobState.PRIVATE_UPLOAD,
        detail="done",
    )
    assert record.state is JobState.PRIVATE_UPLOAD
    json_store = store.read_artifact(job_id, "metadata")
    assert json_store == payload
    events = store.events(job_id)
    assert events[-1]["to_state"] == JobState.PRIVATE_UPLOAD.value
    events_kept = [e for e in events if e["to_state"] == JobState.APPROVED.value]
    assert events_kept, "prior history kept"
    keeper.release()


def test_commit_stage_refused_for_wrong_token(store):
    job_id = store.create(title="c").id
    _at_approving(store, job_id)
    keeper = LeaseKeeper(store.db_path, owner="mine")
    keeper.acquire(job_id)

    with pytest.raises(LeaseLost):
        store.commit_stage(job_id, token="not-my-token", json_artifacts=[("metadata", {})])
    assert store.get(job_id).state is JobState.APPROVED
    assert not store.has_artifact(job_id, "metadata")


def test_commit_stage_refused_for_expired_token(store):
    """Expiry alone kills the commit even though the token still matches the row."""
    import json

    job_id = store.create(title="c").id
    _at_approving(store, job_id)
    keeper = LeaseKeeper(store.db_path, ttl_s=120)
    keeper.acquire(job_id)

    metadata = store.job_dir(job_id) / "metadata.json"
    metadata.write_text(json.dumps({"old": True}), encoding="utf-8")

    with keeper._connect() as conn:
        past = (dt.datetime.now(dt.UTC) - dt.timedelta(seconds=5)).replace(microsecond=0).isoformat()
        conn.execute("UPDATE job_leases SET expires_at = ? WHERE job_id = ?", (past, job_id))

    with pytest.raises(LeaseLost):
        store.commit_stage(
            job_id,
            token=keeper.token,
            json_artifacts=[("metadata", {"new": True})],
            target=JobState.PRIVATE_UPLOAD,
        )
    assert store.get(job_id).state is JobState.APPROVED
    assert json.loads(metadata.read_text(encoding="utf-8")) == {"old": True}, (
        "expired worker must not overwrite canonical files"
    )
    assert not list(store.job_dir(job_id).glob(".*.tmp")), "staging files cleaned up"


def test_commit_stage_binary_file_promotion(store):
    job_id = store.create(title="c").id
    _at_approving(store, job_id)
    keeper = LeaseKeeper(store.db_path)
    keeper.acquire(job_id)

    staged = store.job_dir(job_id) / ".thumb.staging-src.png"
    staged.write_bytes(b"png-bytes")
    try:
        store.commit_stage(
            job_id,
            token=keeper.token,
            files=[("thumb.png", staged)],
            target=JobState.PRIVATE_UPLOAD,
        )
        assert (store.job_dir(job_id) / "thumb.png").read_bytes() == b"png-bytes"
        assert not staged.exists()
    finally:
        keeper.release()


def test_commit_stage_without_target_keeps_state(store):
    job_id = store.create(title="c").id
    store.transition(job_id, JobState.TOPIC_SELECTED)
    keeper = LeaseKeeper(store.db_path)
    keeper.acquire(job_id)
    record = store.commit_stage(job_id, token=keeper.token, json_artifacts=[("topic.json", {"a": 1})])
    assert record.state is JobState.TOPIC_SELECTED
    assert store.read_artifact(job_id, "topic.json") == {"a": 1}
    keeper.release()
