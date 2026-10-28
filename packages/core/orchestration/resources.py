"""Render admission: one global slot, honest telemetry, cancellable waits.

Why this exists: the pipeline renders video, per-scene fragments, thumbnails and motion-skill
validation through the same ffmpeg/Remotion toolchain. On one operator machine those runs compete
for the same RAM, the same GPU encoder and the same disk, and the honest answer to "can I start
another render right now?" is usually "no". This module answers that question once, from persisted
state, and makes waiting a visible state rather than a silent queue.

Two things it deliberately refuses to do:

* **Fabricate a measurement.** If RAM or VRAM telemetry cannot be read, the answer is
  ``waiting`` with the reason recorded — not a guessed zero, and not an automatic bypass.
* **Relax the cap for a busy caller.** The cap is 1 and only the operator's settings change it
  (they cannot raise it above 1; that is the ceiling, not a default).
"""
from __future__ import annotations

import datetime as dt
import os
import shutil
import sqlite3
import subprocess
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Seconds a slot is held without a renewal before another worker may take it. A render that
#: takes longer than this renews; a crashed render's row expires.
DEFAULT_SLOT_TTL_S = 900

#: Where a wait stops being a wait and becomes a blocked job with a recorded reason. The request
#: stays visible; the next tick retries it.
WAIT_LIMIT_S = 300

#: How long a wait sleeps between probes. Short enough to stay cancellable, long enough not to
#: spin the CPU it is trying to protect.
POLL_INTERVAL_S = 2.0


@dataclass(frozen=True)
class ResourcePolicy:
    """Operator settings for admission. Defaults are conservative on purpose."""

    min_free_ram_mib: int = 2048
    min_free_vram_mib: int = 1024
    allow_unmeasured_gpu: bool = False


@dataclass(frozen=True)
class Telemetry:
    """What the machine actually reported, with ``None`` meaning "could not measure"."""

    free_ram_mib: int | None
    free_vram_mib: int | None


@dataclass(frozen=True)
class AdmissionVerdict:
    """The answer to "may this render start?"."""

    ok: bool
    reason: str = ""
    telemetry: Telemetry | None = None


def probe_telemetry(*, timeout_s: float = 3.0) -> Telemetry:
    """Read free RAM and free VRAM. ``None`` fields are unmeasured, never zero.

    RAM comes from ``wmic OS`` (no psutil dependency on a project that already shells out to
    ffmpeg). VRAM comes from ``nvidia-smi``; a machine with no NVIDIA GPU, a driver that refuses
    the query, or a missing binary reports ``None`` — which is a different fact from 0 MiB.
    """
    return Telemetry(
        free_ram_mib=_probe_ram(timeout_s=timeout_s),
        free_vram_mib=_probe_vram(timeout_s=timeout_s),
    )


def _probe_ram(*, timeout_s: float) -> int | None:
    command = ["wmic", "OS", "get", "FreePhysicalMemory", "/value"]
    try:
        raw = subprocess.run(  # noqa: S603 - fixed argv, no shell
            command,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in raw.splitlines():
        key, _, value = line.partition("=")
        if key.strip().lower() != "freephysicalmemory":
            continue
        try:
            kib = int(value.strip())
        except ValueError:
            return None
        return kib // 1024  # wmic reports KiB
    return None


def _probe_vram(*, timeout_s: float) -> int | None:
    if shutil.which("nvidia-smi") is None:
        return None
    command = [
        "nvidia-smi",
        "--query-gpu=memory.free",
        "--format=csv,noheader,nounits",
    ]
    try:
        raw = subprocess.run(  # noqa: S603 - fixed argv, no shell
            command,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    total: int | None = None
    for line in raw.splitlines():
        token = line.strip().split(",")[0].strip()
        if not token.isdigit():
            continue
        mib = int(token)
        total = mib if total is None else max(total, mib)
    return total


class RenderAdmission:
    """The one global render slot, fenced by token and policy like a job lease.

    Usage is acquire/renew/release around the render, with ``wait_for`` as the cancellable
    front door. A verdict of ``waiting_resources`` is not an error: it is the operator-visible
    "this will start when the machine can take it", and the caller releases ownership and keeps
    the request.
    """

    SLOT = "render"

    def __init__(
        self,
        db_path: Path,
        *,
        policy: ResourcePolicy | None = None,
        ttl_s: int = DEFAULT_SLOT_TTL_S,
        owner: str | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.policy = policy or ResourcePolicy()
        self.ttl_s = ttl_s
        self.owner = owner or f"render-{os.getpid()}"
        self._token = uuid.uuid4().hex
        self._held = False
        self._lock = threading.Lock()

    # -- slot -------------------------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _now(self) -> dt.datetime:
        return dt.datetime.now(dt.UTC).replace(microsecond=0)

    def _iso(self, moment: dt.datetime) -> str:
        return moment.isoformat()

    def acquire(self) -> bool:
        """Take the slot if it is free (or expired). False when another live render holds it."""
        with self._lock:
            now = self._now()
            expires = now + dt.timedelta(seconds=self.ttl_s)
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    row = conn.execute(
                        "SELECT token, expires_at FROM render_slots WHERE slot = ?", (self.SLOT,)
                    ).fetchone()
                    if row is not None:
                        if dt.datetime.fromisoformat(row["expires_at"]) > now:
                            return False
                        conn.execute("DELETE FROM render_slots WHERE slot = ?", (self.SLOT,))
                    conn.execute(
                        "INSERT INTO render_slots(slot, token, owner, acquired_at, expires_at)"
                        " VALUES (?,?,?,?,?)",
                        (self.SLOT, self._token, self.owner, self._iso(now), self._iso(expires)),
                    )
                    conn.commit()
                except BaseException:
                    conn.rollback()
                    raise
            self._held = True
            return True

    def renew(self) -> bool:
        """Extend the hold. False once another worker has taken the slot."""
        with self._lock:
            if not self._held:
                return False
            expires = self._now() + dt.timedelta(seconds=self.ttl_s)
            with self._connect() as conn:
                cursor = conn.execute(
                    "UPDATE render_slots SET expires_at = ? WHERE slot = ? AND token = ?",
                    (self._iso(expires), self.SLOT, self._token),
                )
                if cursor.rowcount != 1:
                    self._held = False
                    return False
            return True

    def release(self) -> None:
        with self._lock:
            if not self._held:
                return
            with self._connect() as conn:
                conn.execute(
                    "DELETE FROM render_slots WHERE slot = ? AND token = ?",
                    (self.SLOT, self._token),
                )
            self._held = False

    def __enter__(self) -> RenderAdmission:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()

    # -- policy ------------------------------------------------------------------------------
    def check(self) -> AdmissionVerdict:
        """Can a render start *right now*, given the slot and the telemetry?"""
        telemetry = probe_telemetry()
        if not self._slot_free():
            return AdmissionVerdict(False, "a render slot is already held", telemetry)
        if telemetry.free_ram_mib is None:
            return AdmissionVerdict(False, "free RAM could not be measured", telemetry)
        if telemetry.free_ram_mib < self.policy.min_free_ram_mib:
            return AdmissionVerdict(
                False,
                f"free RAM {telemetry.free_ram_mib} MiB below the "
                f"{self.policy.min_free_ram_mib} MiB floor",
                telemetry,
            )
        if telemetry.free_vram_mib is None:
            if not self.policy.allow_unmeasured_gpu:
                return AdmissionVerdict(
                    False,
                    "GPU memory could not be measured and unmeasured-GPU rendering is not "
                    "opted in",
                    telemetry,
                )
            # Operator opted in: still capped at one concurrent render, never relaxed further.
            return AdmissionVerdict(True, "", telemetry)
        if telemetry.free_vram_mib < self.policy.min_free_vram_mib:
            return AdmissionVerdict(
                False,
                f"free VRAM {telemetry.free_vram_mib} MiB below the "
                f"{self.policy.min_free_vram_mib} MiB floor",
                telemetry,
            )
        return AdmissionVerdict(True, "", telemetry)

    def _slot_free(self) -> bool:
        now = self._now()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT expires_at FROM render_slots WHERE slot = ?", (self.SLOT,)
            ).fetchone()
        return row is None or dt.datetime.fromisoformat(row["expires_at"]) <= now

    def wait_for(
        self,
        *,
        is_cancelled: Callable[[], bool] | None = None,
        limit_s: float = WAIT_LIMIT_S,
        poll_s: float = POLL_INTERVAL_S,
    ) -> AdmissionVerdict:
        """Wait for the machine to be able to render. Cancellable; bounded by ``limit_s``.

        Returns the last verdict: ``ok=True`` means the caller may render (the slot is *not*
        taken here — the caller acquires it, so the hold covers exactly the render), and
        ``ok=False`` with ``waiting`` semantics means the caller should report
        ``waiting_resources`` and stop without consuming a stage attempt.
        """
        deadline = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=limit_s)
        verdict = self.check()
        while not verdict.ok:
            if is_cancelled is not None and is_cancelled():
                return AdmissionVerdict(False, "cancelled while waiting for resources", verdict.telemetry)
            if dt.datetime.now(dt.UTC) >= deadline:
                return verdict
            self._sleep(poll_s, is_cancelled)
            verdict = self.check()
        return verdict

    @staticmethod
    def _sleep(seconds: float, is_cancelled: Callable[[], bool] | None) -> None:
        # A plain sleep is interruptible enough here: the deadline bounds it and cancellation is
        # observed on the next poll. A per-call Event would add machinery for no extra honesty.
        import time

        time.sleep(seconds)


def verdict_detail(verdict: AdmissionVerdict) -> dict[str, Any]:
    """A safe projection for events and job detail: numbers and reasons, never process output."""
    telemetry = verdict.telemetry
    return {
        "ok": verdict.ok,
        "reason": verdict.reason,
        "free_ram_mib": telemetry.free_ram_mib if telemetry else None,
        "free_vram_mib": telemetry.free_vram_mib if telemetry else None,
    }
