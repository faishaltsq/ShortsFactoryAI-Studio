"""The publish stage: no duplicate upload, proven by counting insert calls.

Every test here asserts on the stub's call log rather than on a return value, because the failure
this file exists to prevent is a *second* call that returns successfully. A green assertion on the
first result cannot see it.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pytest

from packages.core.contracts.artifacts import PublicationArtifact
from packages.core.contracts.state import JobState
from packages.core.orchestration.jobstore import JobStore
from packages.core.orchestration.runner import StageChainError, StageError, run_stages
from packages.core.publish.reconcile import key_from_description, key_marker, reconcile_uncertain
from packages.core.publish.stage import PUBLICATION_NAME, build_publish_stage, derive_idempotency_key
from packages.core.publish.stub import StubTransport
from packages.core.publish.transport import InsertRequest

SHA = "a" * 64


class _State:
    """The two attributes a stage needs: a store and an event sink."""

    def __init__(self, store: JobStore) -> None:
        self.store = store
        self.events = _Events()

    def __getattr__(self, name):  # the stage only reads .store and .events
        raise AttributeError(name)


class _Events:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def emit(self, **kwargs) -> None:
        self.rows.append(kwargs)


@pytest.fixture
def store(tmp_path) -> JobStore:
    return JobStore(tmp_path / "factory.db", tmp_path / "jobs")


def _approved_job(store: JobStore, *, sha: str = SHA, payload: bytes = b"video-bytes") -> str:
    """A job sitting at APPROVED with a render.json and a real output.mp4 on disk."""
    job = store.create(title="Judul Video", payload={"provider_mode": "live"})
    for state in (
        JobState.TOPIC_SELECTED,
        JobState.RESEARCH_COMPLETE,
        JobState.SCRIPT_GENERATED,
        JobState.CREATIVE_REVIEW,
        JobState.STORYBOARD_READY,
        JobState.ASSETS_READY,
        JobState.AUDIO_READY,
        JobState.RENDERING,
        JobState.TECHNICAL_QC,
        JobState.EDITORIAL_QC,
        JobState.READY_FOR_APPROVAL,
    ):
        store.transition(job.id, state)
    import hashlib

    (store.job_dir(job.id) / "output.mp4").write_bytes(payload)
    store.write_artifact(
        job.id,
        "render.json",
        {
            "src": "output.mp4",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload),
            "width": 1080,
            "height": 1920,
            "fps": 30,
            "frames": 90,
            "duration_ms": 3000,
            "video_codec": "h264",
            "audio_codec": "aac",
            "pix_fmt": "yuv420p",
            "renderer": "remotion",
            "scene_hashes": {},
        },
    )
    store.write_artifact(
        job.id,
        "approval.json",
        {
            "schema_version": 1,
            "decision": "approved",
            "operator": "op",
            "reason": None,
            "checks": {"publishable": True},
            "decided_at": "2026-01-01T00:00:00+00:00",
            "render_sha256": hashlib.sha256(payload).hexdigest(),
        },
    )
    store.transition(job.id, JobState.APPROVED, detail="approved by op")
    return job.id


def _run(store: JobStore, job_id: str, transport: StubTransport) -> dict:
    state = _State(store)
    return run_stages(
        store=store,
        job_id=job_id,
        stages=[build_publish_stage(state, transport)],
    )


# -- the key is derived, not minted -------------------------------------------------------------


def test_the_idempotency_key_is_a_function_of_job_and_bytes():
    assert derive_idempotency_key("job1", SHA) == derive_idempotency_key("job1", SHA)
    assert derive_idempotency_key("job1", SHA) != derive_idempotency_key("job2", SHA)
    assert derive_idempotency_key("job1", SHA) != derive_idempotency_key("job1", "b" * 64)


def test_a_key_without_bytes_is_refused():
    """Without a digest the key cannot bind to a file, so two renders would share one key."""
    with pytest.raises(ValueError, match="render sha256"):
        derive_idempotency_key("job1", "")


# -- the happy path -----------------------------------------------------------------------------


def test_a_private_upload_confirms_with_a_video_id(store):
    job_id = _approved_job(store)
    transport = StubTransport()
    report = _run(store, job_id, transport)

    assert report["ok"] is True, report
    assert transport.insert_count == 1
    assert store.get(job_id).state is JobState.PRIVATE_UPLOAD

    publication = PublicationArtifact.model_validate(store.read_artifact(job_id, PUBLICATION_NAME))
    digest = store.read_artifact(job_id, "render.json")["sha256"]
    assert publication.phase == "confirmed"
    assert publication.video_id == "stub-0001"
    assert publication.privacy == "private"
    assert publication.idempotency_key == derive_idempotency_key(job_id, digest)
    assert publication.attempt == 1


def test_the_confirmed_receipt_records_what_was_sent(store):
    job_id = _approved_job(store)
    transport = StubTransport()
    _run(store, job_id, transport)
    publication = PublicationArtifact.model_validate(store.read_artifact(job_id, PUBLICATION_NAME))

    upload = [r for r in publication.receipts if r["step"] == "upload"]
    assert len(upload) == 1
    assert upload[0]["ok"] is True
    assert upload[0]["sent"]["idempotency_key"] == publication.idempotency_key
    assert upload[0]["sent"]["bytes"] > 0
    assert upload[0]["sent"]["privacy"] == "private"


# -- rule: a confirmed publication is never re-inserted ------------------------------------------


def test_a_confirmed_publication_is_never_inserted_again(store):
    """The core idempotency rule: a second run reuses the record and does not upload.

    This is what survives a process restart, because the decision is read from disk.
    """
    job_id = _approved_job(store)
    transport = StubTransport()
    _run(store, job_id, transport)
    assert transport.insert_count == 1

    # Simulate a restart: a fresh state object and a fresh stage, same store.
    second = StubTransport()
    report = _run(store, job_id, second)

    assert report["ok"] is True, report
    assert second.insert_count == 0, "a confirmed publication must not be uploaded twice"
    assert report["stages"][0]["reused"] is True
    assert store.get(job_id).state is JobState.PRIVATE_UPLOAD


# -- rule: uncertain blocks, and does not insert ------------------------------------------------


def test_an_uncertain_publication_blocks_and_does_not_insert(store):
    """A recorded uncertainty is a hard stop, not a retry prompt."""
    job_id = _approved_job(store)
    transport = StubTransport()
    transport.be_uncertain_next()
    first = _run(store, job_id, transport)
    assert first["ok"] is False
    assert first["stopped"] == "publication_uncertain"
    assert transport.insert_count == 1

    second = StubTransport()
    # The job is BLOCKED, and ``BLOCKED -> PRIVATE_UPLOAD`` is not in the allow-list, so the
    # runner refuses the chain before the stage runs. That is the second lock: even a caller that
    # re-runs the pipeline cannot reach the stage while the job is blocked.
    with pytest.raises(StageChainError) as exc:
        _run(store, job_id, second)
    assert "PRIVATE_UPLOAD" in str(exc.value)
    assert second.insert_count == 0, "an uncertain record must never trigger another insert"

    # And if the operator clears the block first — through the gate state, since
    # BLOCKED -> APPROVED is refused — the stage itself still refuses.
    store.transition(job_id, JobState.READY_FOR_APPROVAL)
    store.transition(job_id, JobState.APPROVED)
    third = StubTransport()
    report = _run(store, job_id, third)
    assert report["ok"] is False
    assert report["stopped"] == "publication_uncertain"
    assert third.insert_count == 0
    assert "reconcile" in report["detail"].lower()
    assert store.get(job_id).state is JobState.BLOCKED


# -- rule: timeout after send is uncertain and not retryable -------------------------------------


def test_a_timeout_after_send_writes_uncertain_and_is_not_retryable(store):
    job_id = _approved_job(store)
    transport = StubTransport()
    transport.be_uncertain_next(detail="timeout after 30s")
    report = _run(store, job_id, transport)

    assert report["ok"] is False
    assert report["stopped"] == "publication_uncertain"
    assert transport.insert_count == 1, "the request was made exactly once, and not retried"

    publication = PublicationArtifact.model_validate(store.read_artifact(job_id, PUBLICATION_NAME))
    assert publication.phase == "uncertain"
    assert publication.video_id is None
    assert publication.attempt == 1
    sent = [r for r in publication.receipts if r["step"] == "insert_sent"]
    assert len(sent) == 1
    assert sent[0]["at"], "the receipt must say when the request left"
    assert sent[0]["sent"]["idempotency_key"] == publication.idempotency_key
    assert store.get(job_id).state is JobState.BLOCKED


def test_an_uncertain_outcome_is_never_retried_by_the_runner(store):
    """``retryable=False`` is the difference between a blocked job and a duplicate upload."""
    job_id = _approved_job(store)
    transport = StubTransport()
    transport.be_uncertain_next()
    report = _run(store, job_id, transport)

    attempts = [stage for stage in report["stages"] if stage["name"] == "PublisherAgent"]
    assert len(attempts) == 1, "an uncertain insert must not be attempted again in the same run"
    assert transport.insert_count == 1


# -- rule: a pre-flight refusal is retryable and writes nothing ----------------------------------


def test_a_pre_flight_refusal_is_retryable_and_writes_nothing(store):
    """Provably-not-sent is safe to retry, and must not leave an uncertain record behind.

    Writing ``uncertain`` here would make the job permanently un-uploadable after the operator
    fixes their credential — the failure DATA_CONTRACTS §13 warns about.

    The runner retries a retryable failure inside one run (up to ``max_attempts``), so with every
    attempt refused the job ends ``BLOCKED`` on the retry cap, and — the point — no publication
    record exists at any stage of that sequence.
    """
    job_id = _approved_job(store)
    transport = StubTransport()
    transport.refuse_next(code="provider_auth", detail="no token configured")
    transport.refuse_next(code="provider_auth", detail="no token configured")
    transport.refuse_next(code="provider_auth", detail="no token configured")
    report = _run(store, job_id, transport)

    assert report["ok"] is False
    assert transport.insert_count == 3, "a retryable refusal is retried up to the cap"
    assert not store.has_artifact(job_id, PUBLICATION_NAME), (
        "a pre-flight refusal must never write a publication record"
    )
    assert store.get(job_id).state is JobState.BLOCKED


def test_a_pre_flight_refusal_is_marked_retryable(store):
    job_id = _approved_job(store)
    transport = StubTransport()
    transport.refuse_next()
    state = _State(store)
    stage = build_publish_stage(state, transport)

    with pytest.raises(StageError) as exc:
        stage.run(stage_ctx(store, job_id))
    assert exc.value.retryable is True, "a refusal before send is safe to retry"
    assert not store.has_artifact(job_id, PUBLICATION_NAME)


def test_a_pre_flight_refusal_can_be_retried_successfully(store):
    """The retry that is allowed: nothing left, so a second attempt is the first real upload."""
    job_id = _approved_job(store)
    transport = StubTransport()
    transport.refuse_next()
    transport.succeed_next()

    report = _run(store, job_id, transport)

    assert report["ok"] is True, report
    assert transport.insert_count == 2, "one refused attempt, then one real one"
    publication = PublicationArtifact.model_validate(store.read_artifact(job_id, PUBLICATION_NAME))
    assert publication.phase == "confirmed"


# -- a record for different bytes is not silently reused -----------------------------------------


def test_a_publication_for_different_bytes_is_refused(store):
    """A confirmation binds to a digest. A re-render is a different video, not a retry."""
    job_id = _approved_job(store)
    transport = StubTransport()
    _run(store, job_id, transport)

    # A re-render: new bytes, new digest, same job.
    import hashlib

    new_bytes = b"different-video-bytes"
    (store.job_dir(job_id) / "output.mp4").write_bytes(new_bytes)
    store.write_artifact(
        job_id,
        "render.json",
        {**store.read_artifact(job_id, "render.json"),
         "sha256": hashlib.sha256(new_bytes).hexdigest()},
    )

    second = StubTransport()
    report = _run(store, job_id, second)
    assert report["ok"] is False
    assert report["stopped"] == "publication_key_mismatch"
    assert second.insert_count == 0, "a different render must not upload silently"
    assert "reconcile" in report["detail"].lower()


# -- reconciliation: read-only, store-backed -----------------------------------------------


def _uncertain_publication(store: JobStore, job_id: str) -> PublicationArtifact:
    transport = StubTransport()
    transport.be_uncertain_next()
    _run(store, job_id, transport)
    return PublicationArtifact.model_validate(store.read_artifact(job_id, PUBLICATION_NAME))


def test_the_stub_records_the_idempotency_key_it_was_given():
    """Matching needs the key to survive the round trip, so the stub must echo it.

    It records it twice: as an explicit field (a transport with custom metadata) and as a
    ``#sf-key:`` marker in the description (a transport without one).
    """
    transport = StubTransport()
    key = "z" * 32
    transport.insert(
        InsertRequest(idempotency_key=key, video_path="x", title="T", description="desc")
    )
    remote = transport.remote[0]
    assert remote.idempotency_key == key
    assert key_from_description(remote.metadata["description"]) == key
    assert transport.inserts[0].request.idempotency_key == key


def test_reconcile_confirms_from_the_store_without_a_second_insert(store):
    """The whole point of ``uncertain``: resolve it by reading, never by uploading again."""
    job_id = _approved_job(store)
    publication = _uncertain_publication(store, job_id)
    assert publication.phase == "uncertain"

    # The upload actually succeeded remotely; only the response was lost.
    transport = StubTransport()
    transport.add_remote(
        "remote-42",
        title="Judul Video",
        privacy="private",
        idempotency_key=publication.idempotency_key,
    )

    reconciled = reconcile_uncertain(store, job_id, transport)

    assert reconciled.phase == "confirmed"
    assert reconciled.video_id == "remote-42"
    assert transport.insert_count == 0, "reconciliation must never insert"
    assert transport.list_calls == 1
    found = [r for r in reconciled.receipts if r["step"] == "reconciled_found"]
    assert len(found) == 1
    assert "no insert performed" in found[0]["detail"]
    # And it persisted, not just returned.
    on_disk = PublicationArtifact.model_validate(store.read_artifact(job_id, PUBLICATION_NAME))
    assert on_disk.phase == "confirmed"
    assert on_disk.video_id == "remote-42"


def test_reconcile_matches_on_the_description_marker_when_there_is_no_key_field(store):
    """A transport with no custom-metadata field still round-trips the key in the description."""
    job_id = _approved_job(store)
    publication = _uncertain_publication(store, job_id)

    transport = StubTransport()
    transport.add_remote(
        "remote-marker",
        title="whatever the remote shows",
        privacy="private",
        description=f"my description {key_marker(publication.idempotency_key)}",
    )

    reconciled = reconcile_uncertain(store, job_id, transport)
    assert reconciled.phase == "confirmed"
    assert reconciled.video_id == "remote-marker"
    assert transport.insert_count == 0


def test_reconcile_clears_when_nothing_was_created(store):
    """Not found is positive evidence from a successful read, so the record is reset."""
    job_id = _approved_job(store)
    publication = _uncertain_publication(store, job_id)

    transport = StubTransport()
    transport.add_remote("unrelated-1", title="Another video", privacy="private")

    reconciled = reconcile_uncertain(store, job_id, transport)

    assert reconciled.phase == "initiating"
    assert reconciled.video_id is None
    assert transport.insert_count == 0, "clearing must not insert either"
    not_found = [r for r in reconciled.receipts if r["step"] == "reconciled_not_found"]
    assert len(not_found) == 1
    assert "created nothing" in not_found[0]["detail"]
    assert publication.idempotency_key == reconciled.idempotency_key, "the key must not change"


def test_reconcile_refuses_an_ambiguous_match(store):
    """Two candidates must not be resolved by picking one — that could confirm a stranger."""
    job_id = _approved_job(store)
    publication = _uncertain_publication(store, job_id)

    transport = StubTransport()
    for video_id in ("remote-a", "remote-b"):
        transport.add_remote(
            video_id, title="Judul Video", privacy="private",
            idempotency_key=publication.idempotency_key,
        )

    with pytest.raises(ValueError, match="refusing to guess"):
        reconcile_uncertain(store, job_id, transport)
    assert transport.insert_count == 0
    on_disk = PublicationArtifact.model_validate(store.read_artifact(job_id, PUBLICATION_NAME))
    assert on_disk.phase == "uncertain", "an ambiguous result must not rewrite the record"


def test_reconcile_refuses_a_confirmed_record(store):
    """A healthy record is not "fixed" by reconciling it."""
    job_id = _approved_job(store)
    transport = StubTransport()
    _run(store, job_id, transport)
    assert store.read_artifact(job_id, PUBLICATION_NAME)["phase"] == "confirmed"

    with pytest.raises(ValueError, match="already 'confirmed'"):
        reconcile_uncertain(store, job_id, StubTransport())


def test_reconcile_refuses_an_initiating_record(store):
    job_id = _approved_job(store)
    store.write_artifact(
        job_id,
        PUBLICATION_NAME,
        PublicationArtifact(
            phase="initiating", privacy="private", idempotency_key="q" * 32
        ).to_json(),
    )
    with pytest.raises(ValueError, match="not 'uncertain'"):
        reconcile_uncertain(store, job_id, StubTransport())


def test_reconcile_refuses_when_there_is_no_publication(store):
    job_id = _approved_job(store)
    with pytest.raises(ValueError, match="nothing to reconcile"):
        reconcile_uncertain(store, job_id, StubTransport())


def test_a_confirmed_reconciliation_is_never_re_uploaded(store):
    """End to end: uncertain -> reconcile -> confirmed -> re-run inserts zero times."""
    job_id = _approved_job(store)
    publication = _uncertain_publication(store, job_id)

    remote = StubTransport()
    remote.add_remote(
        "remote-99", title="Judul Video", privacy="private",
        idempotency_key=publication.idempotency_key,
    )
    reconciled = reconcile_uncertain(store, job_id, remote)
    assert reconciled.phase == "confirmed"

    after = StubTransport()
    report = _run(store, job_id, after)
    assert report["ok"] is True, report
    assert after.insert_count == 0
    assert report["stages"][0]["reused"] is True


# -- the service entry point, proven without adding a route --------------------------------------


def test_the_service_publishes_only_from_approved(store, tmp_path):
    """A service-level test in place of a route: the route would be a thin wrapper over this.

    The claim being proven is the gate interaction, not HTTP plumbing.
    """
    from apps.api.jobs import JobService
    from apps.api.settings import Settings
    from apps.api.state import AppState

    settings = Settings(
        data_dir=tmp_path / "d",
        db_path=tmp_path / "d" / "f.db",
        jobs_dir=tmp_path / "d" / "jobs",
        secrets_dir=tmp_path / "d" / "secrets",
        studio_config=tmp_path / "c" / "studio.json",
    ).ensure()
    state = AppState.build(settings)
    service = JobService(state)

    job = state.store.create(title="Judul Video", payload={"provider_mode": "live"})
    # Not approved: the service refuses before any transport call.
    transport = StubTransport()
    with pytest.raises(Exception) as exc:
        service.publish(job.id, transport)
    assert "APPROVED" in str(exc.value)
    assert transport.insert_count == 0


# -- the service entry: three refusals, and the restart proof -----------------------------------


def _service(tmp_path):
    from apps.api.jobs import JobService
    from apps.api.settings import Settings
    from apps.api.state import AppState

    settings = Settings(
        data_dir=tmp_path / "d",
        db_path=tmp_path / "d" / "f.db",
        jobs_dir=tmp_path / "d" / "jobs",
        secrets_dir=tmp_path / "d" / "secrets",
        studio_config=tmp_path / "c" / "studio.json",
    ).ensure()
    state = AppState.build(settings)
    return JobService(state), state


def test_publish_refuses_a_job_that_is_not_approved(tmp_path):
    service, state = _service(tmp_path)
    job = state.store.create(title="Judul Video", payload={"provider_mode": "live"})
    transport = StubTransport()

    with pytest.raises(Exception) as exc:
        service.publish(job.id, transport)
    assert "only possible at APPROVED" in str(exc.value)
    assert transport.insert_count == 0


def test_publish_refuses_a_mock_job_with_the_publishable_reason(tmp_path):
    """A mock job's video is fabricated; the gate already says so, and publishing must too."""
    service, state = _service(tmp_path)
    job = state.store.create(title="Judul Video", payload={"provider_mode": "mock"})
    for st in (
        JobState.TOPIC_SELECTED, JobState.RESEARCH_COMPLETE, JobState.SCRIPT_GENERATED,
        JobState.CREATIVE_REVIEW, JobState.STORYBOARD_READY, JobState.ASSETS_READY,
        JobState.AUDIO_READY, JobState.RENDERING, JobState.TECHNICAL_QC,
        JobState.EDITORIAL_QC, JobState.READY_FOR_APPROVAL,
    ):
        state.store.transition(job.id, st)
    # The store's APPROVED check is about evidence, not about mock-ness, so the artifact is
    # written here; the SERVICE is what must refuse a mock job.
    import hashlib as _h

    body = b"mock-bytes"
    (state.store.job_dir(job.id) / "output.mp4").write_bytes(body)
    state.store.write_artifact(
        job.id, "render.json",
        {"src": "output.mp4", "sha256": _h.sha256(body).hexdigest(), "bytes": len(body),
         "width": 1080, "height": 1920, "fps": 30, "frames": 90, "duration_ms": 3000,
         "video_codec": "h264", "audio_codec": "aac", "pix_fmt": "yuv420p",
         "renderer": "remotion", "scene_hashes": {}},
    )
    state.store.write_artifact(
        job.id, "approval.json",
        {"schema_version": 1, "decision": "approved", "operator": "op", "reason": None,
         "checks": {"publishable": True}, "decided_at": "2026-01-01T00:00:00+00:00",
         "render_sha256": _h.sha256(body).hexdigest()},
    )
    state.store.transition(job.id, JobState.APPROVED)
    transport = StubTransport()

    with pytest.raises(Exception) as exc:
        service.publish(job.id, transport)
    message = str(exc.value)
    assert "mock" in message
    assert "publishable is false" in message
    assert transport.insert_count == 0
    assert not state.store.has_artifact(job.id, PUBLICATION_NAME)


def test_publish_refuses_when_the_approval_is_no_longer_publishable(tmp_path):
    """The gate is recomputed at publish time, not trusted from the earlier decision."""
    service, state = _service(tmp_path)
    job = state.store.create(title="Judul Video", payload={"provider_mode": "live"})
    for st in (
        JobState.TOPIC_SELECTED, JobState.RESEARCH_COMPLETE, JobState.SCRIPT_GENERATED,
        JobState.CREATIVE_REVIEW, JobState.STORYBOARD_READY, JobState.ASSETS_READY,
        JobState.AUDIO_READY, JobState.RENDERING, JobState.TECHNICAL_QC,
        JobState.EDITORIAL_QC, JobState.READY_FOR_APPROVAL,
    ):
        state.store.transition(job.id, st)
    # Evidence the store accepts, but no QC artifacts — so _approval_checks says not publishable.
    import hashlib as _h

    body = b"live-bytes"
    (state.store.job_dir(job.id) / "output.mp4").write_bytes(body)
    state.store.write_artifact(
        job.id, "render.json",
        {"src": "output.mp4", "sha256": _h.sha256(body).hexdigest(), "bytes": len(body),
         "width": 1080, "height": 1920, "fps": 30, "frames": 90, "duration_ms": 3000,
         "video_codec": "h264", "audio_codec": "aac", "pix_fmt": "yuv420p",
         "renderer": "remotion", "scene_hashes": {}},
    )
    state.store.write_artifact(
        job.id, "approval.json",
        {"schema_version": 1, "decision": "approved", "operator": "op", "reason": None,
         "checks": {"publishable": True}, "decided_at": "2026-01-01T00:00:00+00:00",
         "render_sha256": _h.sha256(body).hexdigest()},
    )
    state.store.transition(job.id, JobState.APPROVED)
    transport = StubTransport()

    with pytest.raises(Exception) as exc:
        service.publish(job.id, transport)
    assert "no longer publishable" in str(exc.value)
    assert transport.insert_count == 0


def _run_fake_thumbnail(**kwargs) -> dict:
    """The stub renderer's body: write a real PNG header so digest checks pass."""
    from pathlib import Path as _Path

    _Path(kwargs["out_path"]).write_bytes(b"\x89PNG\r\n\x1a\nthumbnail-bytes")
    return {"elapsed_ms": 1}


def test_a_process_restart_after_uncertain_uploads_exactly_once(tmp_path, monkeypatch):
    """The Phase 4 gate's restart half, proven offline.

    Run 1 ends in ``uncertain``: the insert was attempted once and the outcome was lost. Run 2 is
    a *fresh* service object over the same database — the closest offline analogue of a restarted
    process. It must not insert a second time. The only path to a confirmed record is
    reconciliation, which reads.
    """
    service, state = _service(tmp_path)
    # The publish flow now renders the thumbnail first; a unit test stubs the renderer (the slow
    # suite proves the real one), otherwise this test would need a browser for a Remotion render
    # that has nothing to do with what it proves.
    from packages.core.orchestration import resources
    from packages.core.publish import thumbnail as thumb_mod
    monkeypatch.setattr(thumb_mod, "render_storyboard", _run_fake_thumbnail)
    monkeypatch.setattr(resources, "probe_telemetry", lambda **kwargs: resources.Telemetry(8192, 8192))
    # A genuinely publishable job: the same gate fixture the approval tests use, driven through
    # the real approve route so every artifact the gate recomputes is present and coherent.
    from fastapi.testclient import TestClient

    from apps.api.main import create_app
    from tests.test_api_approval_gate import _ready_job

    app = create_app(state)
    client = TestClient(app)
    job_id, _ = _ready_job(client, app, provider_mode="live")
    assert client.post(f"/api/jobs/{job_id}/approve", json={"operator": "op"}).status_code == 200
    first = StubTransport()
    first.be_uncertain_next()
    first_report = service.publish(job_id, first)

    assert first_report["ok"] is False
    assert first_report["stopped"] == "publication_uncertain"
    assert first.insert_count == 1
    assert state.store.read_artifact(job_id, PUBLICATION_NAME)["phase"] == "uncertain"

    # Restart: a new service over the same store.
    restarted, _ = _service(tmp_path)
    second = StubTransport()
    # The job is BLOCKED now, so the service refuses before any transport call.
    with pytest.raises(Exception) as exc:
        restarted.publish(job_id, second)
    assert "only possible at APPROVED" in str(exc.value)
    assert second.insert_count == 0

    # Even after the operator clears the block through the gate, the stage refuses.
    state.store.transition(job_id, JobState.READY_FOR_APPROVAL)
    state.store.transition(job_id, JobState.APPROVED)
    third = StubTransport()
    third_report = restarted.publish(job_id, third)
    assert third_report["ok"] is False
    assert third_report["stopped"] == "publication_uncertain"
    assert third.insert_count == 0

    assert first.insert_count + second.insert_count + third.insert_count == 1, (
        "exactly one insert across the whole restart sequence"
    )

    # Reconciliation is the only way forward, and it reads.
    remote = StubTransport()
    publication = PublicationArtifact.model_validate(
        state.store.read_artifact(job_id, PUBLICATION_NAME)
    )
    remote.add_remote(
        "remote-after-restart", title="Judul Video", privacy="private",
        idempotency_key=publication.idempotency_key,
    )
    reconciled = reconcile_uncertain(state.store, job_id, remote)
    assert reconciled.phase == "confirmed"
    assert reconciled.video_id == "remote-after-restart"
    assert remote.insert_count == 0
    assert first.insert_count + second.insert_count + third.insert_count == 1


# -- metadata stage: MetadataAgent is in the chain and writes metadata.json ---------------------


def test_the_metadata_stage_writes_metadata_json(tmp_path):
    """``MetadataAgent`` existed but was in no chain, so ``metadata.json`` was never produced.

    The publish stage falls back to the job title when metadata is absent; that fallback exists so
    a missing stage cannot crash a publish, not so the stage can be missing.

    Runs the real agent chain in mock mode, so this proves the stage end to end rather than only
    that a name appears in a list.
    """
    from packages.core.orchestration.pipeline import build_stages

    _, state = _service(tmp_path)
    job = state.store.create(title="Judul", payload={"provider_mode": "mock"})
    stages = build_stages(state, job.id)
    names = [stage.name for stage in stages]
    assert "MetadataAgent" in names, names

    report = run_stages(store=state.store, job_id=job.id, stages=stages)
    assert report["ok"] is True, report
    assert state.store.has_artifact(job.id, "metadata.json")
    metadata = state.store.read_artifact(job.id, "metadata.json")
    assert metadata["schema_version"] == 1
    assert metadata["title"]
    assert metadata["synthetic_media"] is True


def test_the_metadata_stage_runs_after_the_storyboard(store):
    """Metadata is derived from the script and storyboard, so both must already exist."""
    from packages.core.orchestration.pipeline import build_stages

    job = store.create(title="Judul", payload={"provider_mode": "mock"})
    names = [stage.name for stage in build_stages(_State(store), job.id)]
    assert names.index("MetadataAgent") > names.index("StoryboardAgent")


# -- thumbnail render wiring -------------------------------------------------------------------


def test_the_thumbnail_stage_records_a_sha256_in_metadata(tmp_path, monkeypatch):
    """The thumbnail composition exists but nothing rendered it.

    The stage is proven with a stub renderer: what is under test is the wiring — the composition
    name it asks for, the file it writes, and the digest it records into ``metadata.json``. A real
    Remotion render is the ``slow`` suite's job, not this test's.
    """
    from packages.core.publish import thumbnail as thumb_mod

    _, state = _service(tmp_path)
    job = state.store.create(title="Judul", payload={"provider_mode": "mock"})
    for st in (
        JobState.TOPIC_SELECTED, JobState.RESEARCH_COMPLETE, JobState.SCRIPT_GENERATED,
        JobState.CREATIVE_REVIEW, JobState.STORYBOARD_READY,
    ):
        state.store.transition(job.id, st)
    state.store.write_artifact(
        job.id, "metadata.json",
        {"schema_version": 1, "title": "Judul", "description": "", "tags": [],
         "category_id": "22", "made_for_kids": False, "synthetic_media": True, "thumbnail": {}},
    )
    state.store.write_artifact(
        job.id, "storyboard.json",
        {"schema_version": 1, "fps": 30, "width": 1080, "height": 1920, "theme": "dusk",
         "scenes": [], "subtitles": []},
    )

    state.store.write_artifact(
        job.id, "render-props.json", {"storyboard": {"scenes": []}}
    )

    calls: list[dict] = []

    def fake_render(**kwargs):
        calls.append(kwargs)
        Path(kwargs["out_path"]).write_bytes(b"\x89PNG\r\n\x1a\nthumbnail-bytes")
        return {"elapsed_ms": 1}

    monkeypatch.setattr(thumb_mod, "render_storyboard", fake_render)
    stage = thumb_mod.build_thumbnail_stage(state, video_dir=tmp_path)
    ctx = stage_ctx(state.store, job.id, tmp_path)
    outcome = stage.run(ctx)

    assert outcome.ok is True, outcome.detail
    assert calls and calls[0]["composition"] == "Thumbnail"
    # A direct stage.run stops at staging; promotion is the runner's fenced step. The pairing is
    # what matters here: the staged png exists and the staged metadata names it with a digest.
    assert (ctx.staging / "thumb.png").is_file()
    metadata = dict(ctx.json_pending)["metadata.json"]
    thumb = metadata["thumbnail"]
    assert thumb["path"] == "thumb.png"
    assert len(thumb["sha256"]) == 64


def stage_ctx(store, job_id, tmp: Path | None = None) -> Any:
    """A stage context for direct stage.run() calls outside run_stages."""
    from packages.core.orchestration.runner import NullCancel, StageContext

    return StageContext(
        store,
        job_id,
        (tmp or Path(tempfile.mkdtemp(prefix="stagectx-"))),
        cancel=NullCancel(),
    )
