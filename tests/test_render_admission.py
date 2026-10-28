"""Render admission: one slot, honest telemetry, cancellable waits."""
from __future__ import annotations

import datetime as dt

import pytest

from packages.core.orchestration import resources
from packages.core.orchestration.jobstore import JobStore
from packages.core.orchestration.resources import (
    AdmissionVerdict,
    RenderAdmission,
    ResourcePolicy,
    Telemetry,
    probe_telemetry,
)


@pytest.fixture
def db(tmp_path):
    # JobStore owns the schema; RenderAdmission reuses its connection.
    JobStore(tmp_path / "f.db", tmp_path / "jobs")
    return tmp_path / "f.db"


def test_only_one_render_slot_is_held_at_a_time(db):
    first = RenderAdmission(db)
    second = RenderAdmission(db)
    assert first.acquire() is True
    assert second.acquire() is False, "a second live render must not start"
    first.release()
    assert second.acquire() is True


def test_an_expired_slot_is_reclaimed(db):
    admission = RenderAdmission(db, ttl_s=1)
    assert admission.acquire() is True
    # Rewrite the row's expiry into the past rather than sleeping a real second.
    with admission._connect() as conn:  # noqa: SLF001 - test-controlled expiry
        conn.execute(
            "UPDATE render_slots SET expires_at = ? WHERE slot = ?",
            ("2000-01-01T00:00:00+00:00", RenderAdmission.SLOT),
        )
    other = RenderAdmission(db)
    assert other.acquire() is True, "an expired slot belongs to whoever claims it next"


def test_a_release_only_frees_the_holders_own_slot(db):
    holder = RenderAdmission(db)
    stranger = RenderAdmission(db)
    assert holder.acquire() is True
    stranger.release()
    other = RenderAdmission(db)
    assert other.acquire() is False, "a non-holder's release must not free the slot"
    holder.release()
    assert other.acquire() is True


def test_renewal_keeps_the_hold_and_a_lost_slot_is_reported(db):
    holder = RenderAdmission(db, ttl_s=60)
    assert holder.acquire() is True
    assert holder.renew() is True
    other = RenderAdmission(db, ttl_s=60)
    # Force the takeover the way a crashed worker's expiry would: delete and re-insert with a
    # different token, exactly what a second acquire does once the row has expired.
    with holder._connect() as conn:  # noqa: SLF001
        conn.execute("DELETE FROM render_slots WHERE slot = ?", (RenderAdmission.SLOT,))
    other.acquire()
    assert holder.renew() is False, "a stolen slot must read as lost to its previous holder"


def test_low_ram_blocks_even_when_the_slot_is_free(db, monkeypatch):
    monkeypatch.setattr(
        resources, "probe_telemetry", lambda **_kw: Telemetry(free_ram_mib=512, free_vram_mib=8192)
    )
    verdict = RenderAdmission(db).check()
    assert verdict.ok is False
    assert "512 MiB" in verdict.reason


def test_unmeasured_gpu_waits_unless_the_operator_opted_in(db, monkeypatch):
    monkeypatch.setattr(resources, "probe_telemetry", lambda **_kw: Telemetry(free_ram_mib=8192, free_vram_mib=None))
    assert RenderAdmission(db).check().ok is False
    opted_in = RenderAdmission(db, policy=ResourcePolicy(allow_unmeasured_gpu=True))
    assert opted_in.check().ok is True


def test_a_held_slot_reports_waiting_even_with_headroom(db, monkeypatch):
    monkeypatch.setattr(
        resources, "probe_telemetry", lambda **_kw: Telemetry(free_ram_mib=8192, free_vram_mib=8192)
    )
    holder = RenderAdmission(db)
    holder.acquire()
    verdict = RenderAdmission(db).check()
    assert verdict.ok is False
    assert "already held" in verdict.reason


def test_wait_is_cancellable_and_bounded(db, monkeypatch):
    monkeypatch.setattr(
        resources, "probe_telemetry", lambda **_kw: Telemetry(free_ram_mib=256, free_vram_mib=256)
    )
    holder = RenderAdmission(db)
    holder.acquire()
    cancelled = {"flag": False}

    def is_cancelled() -> bool:
        cancelled["flag"] = True
        return True

    verdict = RenderAdmission(db).wait_for(is_cancelled=is_cancelled, limit_s=30)
    assert verdict.ok is False
    assert "cancelled" in verdict.reason
    assert cancelled["flag"] is True


def test_wait_gives_up_with_a_recorded_reason_not_an_exception(db, monkeypatch):
    monkeypatch.setattr(
        resources, "probe_telemetry", lambda **_kw: Telemetry(free_ram_mib=256, free_vram_mib=256)
    )
    verdict = RenderAdmission(db).wait_for(limit_s=0.05, poll_s=0.01)
    assert verdict.ok is False
    assert "256 MiB" in verdict.reason


def test_probe_never_reports_zero_for_a_missing_measurement(monkeypatch):
    """An unmeasurable GPU is ``None``, not 0: 0 MiB would read as "full", which is a different
    (and wrong) claim."""
    monkeypatch.setattr(resources, "_probe_vram", lambda **_kw: None)
    monkeypatch.setattr(resources, "_probe_ram", lambda **_kw: None)
    telemetry = probe_telemetry()
    assert telemetry.free_ram_mib is None
    assert telemetry.free_vram_mib is None


def test_verdict_detail_projects_numbers_and_reasons_only():
    verdict = AdmissionVerdict(False, "busy", Telemetry(free_ram_mib=100, free_vram_mib=None))
    detail = resources.verdict_detail(verdict)
    assert detail == {
        "ok": False,
        "reason": "busy",
        "free_ram_mib": 100,
        "free_vram_mib": None,
    }
    assert all(not isinstance(value, dt.datetime) for value in detail.values())
