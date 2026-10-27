"""Run the dashboard E2E suite against servers it owns, in a temporary data root.

Replaces the webServer command that deleted ``data/e2e`` from the repository root: that path
expression did not even resolve to the configured ``data/e2e``, and deleting a fixed repository
path from a test hook is how operator data dies. This wrapper creates one
``tempfile.TemporaryDirectory``, points every ``SHORTS_*`` path at it, starts both servers,
runs the existing Playwright CLI through Node, and removes only its own directory after both
children have stopped.

    uv run python scripts/dashboard_e2e.py [extra playwright args...]

Ports stay 8019/3018 and ``reuseExistingServer: false``, exactly as configured; if either port
is taken by an operator process, Playwright fails to bind and this is a visible failure - the
wrapper never adopts or kills an unrelated process.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_PORT = 8019
UI_PORT = 3018
API_URL = f"http://127.0.0.1:{API_PORT}"
UI_URL = f"http://127.0.0.1:{UI_PORT}"


def main(argv: list[str]) -> int:
    # --hold: Playwright's webServer spawns this and probes the ports; keep the temp root and
    # both children alive until Playwright exits, then clean up. Without --hold, run the suite
    # directly.
    hold = "--hold" in argv
    if hold:
        argv = [a for a in argv if a != "--hold"]
    with tempfile.TemporaryDirectory(prefix="studio-e2e-") as tmp:
        tmp_root = Path(tmp)
        env = os.environ.copy()
        env.update(
            SHORTS_DATA_DIR=str(tmp_root / "data"),
            SHORTS_DB_PATH=str(tmp_root / "data" / "factory.db"),
            SHORTS_JOBS_DIR=str(tmp_root / "data" / "jobs"),
            SHORTS_SECRETS_DIR=str(tmp_root / "data" / "secrets"),
            SHORTS_STUDIO_CONFIG=str(tmp_root / "data" / "studio.json"),
            SHORTS_MOCK_DELAY_MS="1500",
            STUDIO_API_ORIGIN=API_URL,
            STUDIO_E2E_API=API_URL,
            STUDIO_E2E_DATA=str(tmp_root / "data"),
        )

        api = subprocess.Popen(
            [
                "uv", "run", "uvicorn", "apps.api.main:app",
                "--host", "127.0.0.1", "--port", str(API_PORT),
            ],
            cwd=ROOT,
            env=env,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        ui = subprocess.Popen(
            ["npm", "run", "dev", "--", "--port", str(UI_PORT)],
            cwd=ROOT / "apps" / "dashboard",
            env=env,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        try:
            if not _wait_ready(f"{API_URL}/api/health", 30.0):
                print(f"FAIL API did not become ready at {API_URL}", file=sys.stderr)
                return 2
            if not _wait_ready(UI_URL, 90.0):
                print(f"FAIL dashboard did not become ready at {UI_URL}", file=sys.stderr)
                return 2

            # --hold mode: Playwright spawned us as its API webServer; the UI webServer entry
            # probes :3018 which our UI child already owns, so no second server spawns.
            if hold:
                print(
                    f"e2e servers ready: api={API_URL} ui={UI_URL} root={tmp_root}",
                    flush=True,
                )
                # Parent (Playwright) signals exit by closing our stdin... simplest: serve
                # until terminated.
                api.wait()
                return 0
            config = ROOT / "apps" / "dashboard" / "playwright.e2e.config.ts"
            config.write_text(_config(), encoding="utf-8")
            result = subprocess.run(
                ["npx", "playwright", "test", "--config=playwright.e2e.config.ts", *argv],
                cwd=ROOT / "apps" / "dashboard",
                env=env,
            )
            return result.returncode
        finally:
            _stop(api)
            _stop(ui)


def _wait_ready(url: str, timeout_s: float) -> bool:
    """Poll until the URL answers; the dashboard server needs the longer budget."""
    from packages.core.providers.http_base import PinnedHTTP

    http = PinnedHTTP(timeout_s=5.0, max_retries=0)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            response = http.request("GET", url, allow_private_hosts=True)
            if response.status_code < 500:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def _stop(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)


def _config() -> str:
    """A config with no webServer block: the ports above are already owned by this wrapper."""
    return """\
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: { baseURL: "http://127.0.0.1:3018", trace: "retain-on-failure" },
});
"""


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
