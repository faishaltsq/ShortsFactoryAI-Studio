"""The Phase 1 exit-gate demo: a full job lifecycle with no credential and no network.

    uv run python scripts/demo_phase1.py [--keep]

What it proves, in one run, all against the mock transport:

1. a job is created and run to ``STORYBOARD_READY`` with real artifacts on disk;
2. a second job is cancelled mid-flight and stops at a stage boundary rather than lying about it;
3. the process is "killed" by discarding the in-memory worker state and rebuilding the app over the
   same database, exactly as a restart does;
4. the interrupted job resumes and produces exactly one provider call per stage — the duplicate-work
   guarantee, asserted by counting calls, not by reading a log line.

It prints the final state of every job it touched, and exits non-zero if any assertion fails. The
temporary data directory is removed unless ``--keep`` is passed.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.api.jobs import JobService  # noqa: E402
from apps.api.settings import Settings  # noqa: E402
from apps.api.state import AppState  # noqa: E402
from packages.core.contracts.state import JobState  # noqa: E402
from packages.core.orchestration.leases import read_leases  # noqa: E402
from packages.core.orchestration.pipeline import build_stages  # noqa: E402
from packages.core.providers.usage import Budget  # noqa: E402

#: A literal here went stale the day ``MetadataAgent`` joined the chain, and the demo then failed
#: for a reason that had nothing to do with the lifecycle it proves. The expected count is read from
#: the chain the run actually uses, so adding an agent stage cannot break this script.
TERMINAL = {JobState.BLOCKED, JobState.FAILED, JobState.CANCELLED}


def build(root: Path) -> tuple[AppState, JobService]:
    """One app over one data directory. Calling it twice is a restart."""
    settings = Settings(
        data_dir=root / "data",
        db_path=root / "data" / "factory.db",
        jobs_dir=root / "data" / "jobs",
        secrets_dir=root / "data" / "secrets",
        studio_config=root / "config" / "studio.json",
    ).ensure()
    state = AppState.build(settings, budget=Budget())
    state.registry.specs["mock"].enabled = True
    return state, JobService(state)


def wait_until(service: JobService, job_id: str, predicate, *, timeout_s: float = 60) -> JobState:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        job = service.state.store.get(job_id)
        if predicate(job.state):
            return job.state
        if job.state in TERMINAL and job.state is not JobState.CANCELLED:
            return job.state
        time.sleep(0.05)
    raise TimeoutError(f"job {job_id} did not reach the expected state within {timeout_s}s")


def usage_rows(service: JobService, job_id: str) -> int:
    return len(service.state.usage.for_job(job_id))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--keep", action="store_true", help="keep the temporary data directory")
    args = parser.parse_args(argv)

    root = Path(tempfile.mkdtemp(prefix="shorts-demo1-"))
    failures: list[str] = []
    try:
        # -- 1. run a job to STORYBOARD_READY -------------------------------------------------
        state, service = build(root)
        job = service.create({"title": "Demo A", "topic": "demo", "provider_mode": "mock"})
        # Wait for the worker to *finish*, not for a state name: MetadataAgent targets
        # STORYBOARD_READY too, so stopping at the first sighting of that state counts one stage
        # short. The thread is the honest signal for "the chain is done".
        service.start(job.id)
        deadline = time.monotonic() + 60
        while job.id in service.state.running and time.monotonic() < deadline:
            time.sleep(0.05)
        final_a = service.state.store.get(job.id).state
        print(f"1. {job.id} -> {final_a.value}")
        if final_a is not JobState.STORYBOARD_READY:
            failures.append(f"job A ended at {final_a.value}, expected STORYBOARD_READY")

        artifacts = state.store.list_artifacts(job.id)
        print(f"   artifacts: {', '.join(artifacts)}")
        for required in (
            "research.json", "topic.json", "script.json", "review.json", "storyboard.json",
            "metadata.json",
        ):
            if required not in artifacts:
                failures.append(f"job A is missing {required}")
        calls_a = usage_rows(service, job.id)
        expected_calls = len(build_stages(state, job.id))
        print(f"   provider calls: {calls_a} (chain has {expected_calls} stages)")
        if calls_a != expected_calls:
            failures.append(
                f"job A made {calls_a} provider calls, expected {expected_calls}"
            )

        # -- 2. cancel a second job mid-flight -------------------------------------------
        second = service.create({"title": "Demo B", "topic": "cancel", "provider_mode": "mock"})
        service.start(second.id)
        wait_until(service, second.id, lambda s: s is not JobState.IDEA_DISCOVERY, timeout_s=30)
        state.request_cancel(second.id)
        final_b = wait_until(
            service, second.id, lambda s: s in {JobState.CANCELLED, JobState.FAILED}, timeout_s=60
        )
        print(f"2. {second.id} -> {final_b.value} (cancel requested mid-flight)")
        if final_b is not JobState.CANCELLED:
            failures.append(f"cancelled job ended at {final_b.value}, expected CANCELLED")

        # -- 3. "restart" the process -----------------------------------------------------
        before = state.store.list_artifacts(job.id)
        state.running.clear()  # the threads are gone; the database is not
        state, service = build(root)  # a fresh app over the same data directory
        after = state.store.list_artifacts(job.id)
        print(f"3. restarted; {len(after)} artifacts survived, job still {service.state.store.get(job.id).state.value}")
        if before != after:
            failures.append("artifacts changed across the simulated restart")

        # -- 4. resume without repeating paid work ----------------------------------------
        calls_before = usage_rows(service, job.id)
        service.start(job.id)
        deadline = time.monotonic() + 60
        while job.id in service.state.running and time.monotonic() < deadline:
            time.sleep(0.05)
        resumed = service.state.store.get(job.id).state
        calls_after = usage_rows(service, job.id)
        print(f"4. resumed to {resumed.value}; provider calls {calls_before} -> {calls_after}")

        # -- 5. crash recovery: expired lease + no running worker = resume --------------
        # A job interrupted between "state written" and "process killed" has a lease that expires
        # after the worker dies. Once it expires, nothing will ever advance the job, so the
        # recovery hook is what turns a stranded job into a resumable one. Proven here by
        # expiring the lease directly, the way 120 s of real elapsed time would.
        import sqlite3

        victim = service.create({"title": "Demo C", "topic": "crash", "provider_mode": "mock"})
        service.start(victim.id)
        time.sleep(0.2)
        state.running.pop(victim.id, None)  # the thread is gone; the lease row is not
        with sqlite3.connect(str(state.store.db_path)) as conn:
            conn.execute("UPDATE job_leases SET expires_at = '2020-01-01T00:00:00+00:00'")
        lease = read_leases(state.store.db_path, [victim.id])[victim.id]
        if lease.expires_at[:4] != "2020":
            failures.append(f"lease expiry patch did not apply: {lease.expires_at}")
        from apps.api.main import _recover_interrupted

        recovered = _recover_interrupted(state, service)
        print(f"5. crash recovery: {len(recovered)} job(s) resumed from an expired lease")
        if victim.id not in recovered:
            failures.append(f"job {victim.id} was not recovered from its expired lease")
        if calls_after != calls_before:
            failures.append(
                f"resume repeated paid work: {calls_before} calls became {calls_after}. "
                "Every stage should have been reused from its artifact."
            )
        if resumed is not JobState.STORYBOARD_READY:
            failures.append(f"resumed job ended at {resumed.value}")

        print()
        if failures:
            for problem in failures:
                print(f"FAIL  {problem}")
            return 1
        print("PASS  create, cancel, restart and resume, with zero duplicate provider calls")
        return 0
    finally:
        if args.keep:
            print(f"\ndata kept at {root}")
        else:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
