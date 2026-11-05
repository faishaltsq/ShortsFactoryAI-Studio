import pytest

from tests.test_api_approval_gate import _approve, _ready_job
from tests.test_api_approval_gate import app as _app_fixture
from tests.test_api_approval_gate import client as _client_fixture

app = _app_fixture
client = _client_fixture


def test_cached_semantic_pass_cannot_authorize_an_uninspected_job(client, app):
    job_id, _ = _ready_job(client, app, provider_mode="live", manual_review=False)
    store = app.state.studio.store
    cached = store.read_artifact(job_id, "readiness.json")
    cached.update(
        ready=True,
        blockers=[],
        checks={"technical": True, "creative": True, "visual": True, "checksum": True},
        technical_ready=True,
        manual_review_eligible=True,
        semantic_status="PASS",
        review_basis="semantic_pass",
        human_approved=False,
    )
    store.write_artifact(job_id, "readiness.json", cached)
    response = _approve(client, job_id)
    assert response.status_code == 409
    assert "semantic_review_eligible" in response.json()["detail"]


def test_policy_permission_is_explicit_render_bound_and_not_approval(client, app):
    job_id, facts = _ready_job(client, app, provider_mode="live", manual_review=False)
    result = client.post(
        f"/api/jobs/{job_id}/manual-review-policy",
        json={
            "operator": "fixture-reviewer",
            "reason": "Allow direct human inspection of this exact video",
            "render_sha256": facts["sha256"],
            "allow_unverified": True,
        },
    )
    assert result.status_code == 200, result.text
    store = app.state.studio.store
    assert store.get(job_id).state.value == "READY_FOR_APPROVAL"
    assert not store.has_artifact(job_id, "approval.json")
    policy = store.read_artifact(job_id, "manual-review-policy.json")
    assert policy["render_sha256"] == facts["sha256"]
    assert policy["operator"] == "fixture-reviewer"
    assert policy["reason"]
    assert result.json()["approved"] is False
    from packages.core.orchestration.editorial import build_readiness_stage
    from packages.core.orchestration.runner import run_stages

    report = run_stages(store=store, job_id=job_id, stages=[build_readiness_stage(app.state.studio)])
    assert report["ok"] is True, report
    ready = store.read_artifact(job_id, "readiness.json")
    assert ready["semantic_status"] == "UNVERIFIED"
    assert ready["manual_review_eligible"] is True
    assert ready["human_approved"] is False
    response = _approve(client, job_id)
    assert response.status_code == 200, response.text


def test_policy_for_other_render_is_refused(client, app):
    job_id, _ = _ready_job(client, app, provider_mode="live", manual_review=False)
    result = client.post(
        f"/api/jobs/{job_id}/manual-review-policy",
        json={
            "operator": "fixture-reviewer",
            "reason": "Manual review permission",
            "render_sha256": "f" * 64,
            "allow_unverified": True,
        },
    )
    assert result.status_code == 409
    assert not app.state.studio.store.has_artifact(job_id, "manual-review-policy.json")


def test_source_context_change_revokes_manual_eligibility_without_changing_video(client, app):
    job_id, _ = _ready_job(client, app, provider_mode="live")
    store = app.state.studio.store
    from packages.core.orchestration.editorial import evaluate_job_readiness

    assert evaluate_job_readiness(store, job_id)["ready"] is True
    audio = store.read_artifact(job_id, "audio.json")
    audio["subtitles"][0]["text"] = "Different narration requirement"
    store.write_artifact(job_id, "audio.json", audio)
    response = _approve(client, job_id)
    assert response.status_code == 409
    assert "semantic_review_eligible" in response.json()["detail"]


@pytest.mark.parametrize("permission", [False, "true", 1, None])
def test_permission_requires_literal_true_not_coercion(client, app, permission):
    job_id, facts = _ready_job(client, app, provider_mode="live", manual_review=False)
    response = client.post(
        f"/api/jobs/{job_id}/manual-review-policy",
        json={
            "operator": "fixture-reviewer",
            "reason": "Explicit review request",
            "render_sha256": facts["sha256"],
            "allow_unverified": permission,
        },
    )
    assert response.status_code == 422
    assert not app.state.studio.store.has_artifact(job_id, "manual-review-policy.json")


def test_policy_cannot_write_while_another_worker_holds_the_lease(client, app):
    from packages.core.orchestration.leases import LeaseKeeper

    job_id, facts = _ready_job(client, app, provider_mode="live", manual_review=False)
    keeper = LeaseKeeper(app.state.studio.store.db_path, owner="fixture-worker")
    keeper.acquire(job_id)
    try:
        response = client.post(
            f"/api/jobs/{job_id}/manual-review-policy",
            json={
                "operator": "fixture-reviewer",
                "reason": "Explicit review request",
                "render_sha256": facts["sha256"],
                "allow_unverified": True,
            },
        )
        assert response.status_code == 409
        assert not app.state.studio.store.has_artifact(job_id, "manual-review-policy.json")
    finally:
        keeper.release()


def test_blank_operator_is_not_a_final_human_approval(client, app):
    job_id, _ = _ready_job(client, app, provider_mode="live")
    from packages.core.orchestration.editorial import evaluate_job_readiness

    assert evaluate_job_readiness(app.state.studio.store, job_id)["ready"] is True
    response = client.post(f"/api/jobs/{job_id}/approve", json={"operator": "   "})
    assert response.status_code == 409
    assert not app.state.studio.store.has_artifact(job_id, "approval.json")


@pytest.mark.parametrize("decision", ["approve", "reject", "manual-review-policy"])
def test_lost_decision_lease_cannot_write_approval(client, app, monkeypatch, decision):
    import datetime as dt

    from apps.api import jobs
    from packages.core.orchestration import leases

    job_id, facts = _ready_job(
        client, app, provider_mode="live", manual_review=decision != "manual-review-policy"
    )
    evaluate = jobs.evaluate_job_readiness
    clock = leases._now
    rival = leases.LeaseKeeper(app.state.studio.store.db_path, owner="replacement-worker")

    def steal_after_evaluation(store, current_job):
        result = evaluate(store, current_job)
        monkeypatch.setattr(leases, "_now", lambda: clock() + dt.timedelta(seconds=120))
        rival.acquire(current_job)
        return result

    monkeypatch.setattr(jobs, "evaluate_job_readiness", steal_after_evaluation)
    try:
        body = {"operator": "fixture-reviewer"}
        if decision != "approve":
            body["reason"] = "Explicit operator decision"
        if decision == "manual-review-policy":
            body.update(render_sha256=facts["sha256"], allow_unverified=True)
        response = client.post(f"/api/jobs/{job_id}/{decision}", json=body)
        assert response.status_code == 409
        assert not app.state.studio.store.has_artifact(job_id, "approval.json")
        if decision == "manual-review-policy":
            assert not app.state.studio.store.has_artifact(job_id, "manual-review-policy.json")
        assert rival.owns()
    finally:
        rival.release()


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_human_decision_cannot_race_an_active_worker(client, app, decision):
    from packages.core.orchestration.leases import LeaseKeeper

    job_id, _ = _ready_job(client, app, provider_mode="live")
    keeper = LeaseKeeper(app.state.studio.store.db_path, owner="fixture-worker")
    keeper.acquire(job_id)
    try:
        response = client.post(
            f"/api/jobs/{job_id}/{decision}",
            json={
                "operator": "fixture-reviewer",
                **({"reason": "Observed defect"} if decision == "reject" else {}),
            },
        )
        assert response.status_code == 409
        assert not app.state.studio.store.has_artifact(job_id, "approval.json")
    finally:
        keeper.release()
