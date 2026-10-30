"""Run Playwright with a temporary API, production dashboard build, and data root.

    uv run python -m scripts.dashboard_e2e [Playwright arguments...]

STUDIO_E2E_API_PORT / STUDIO_E2E_UI_PORT select explicit loopback ports; omitted
or zero asks the OS for free ports. No existing server, build, or data is reused.
"""
from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "apps" / "dashboard"


def _reserve_port(value: str | None) -> socket.socket:
    try:
        port = int(value or "0")
        if not 0 <= port <= 65535:
            raise ValueError
    except ValueError as exc:
        raise RuntimeError("E2E ports must be integers between 0 and 65535") from exc
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        if port:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.settimeout(0.25)
                if probe.connect_ex(("127.0.0.1", port)) == 0:
                    raise OSError("another process is already listening")
        sock.bind(("127.0.0.1", port))
        sock.listen(1)
        return sock
    except OSError as exc:
        sock.close()
        raise RuntimeError(f"Cannot reserve E2E loopback port {port}: {exc}") from exc


def _environment(root: Path, api_url: str, ui_url: str) -> dict[str, str]:
    env = os.environ.copy()
    # The isolated API has no operator credentials or operator configuration.
    env.pop("STUDIO_API_TOKEN", None)
    env.update(
        SHORTS_DATA_DIR=str(root / "data"),
        SHORTS_DB_PATH=str(root / "data" / "factory.db"),
        SHORTS_JOBS_DIR=str(root / "data" / "jobs"),
        SHORTS_SECRETS_DIR=str(root / "data" / "secrets"),
        SHORTS_STUDIO_CONFIG=str(root / "data" / "studio.json"),
        SHORTS_MOCK_DELAY_MS="1500",
        SHORTS_SCHEDULER_ENABLED="0",
        STUDIO_API_ORIGIN=api_url,
        STUDIO_E2E_API=api_url,
        STUDIO_E2E_DATA=str(root / "data"),
        STUDIO_URL=ui_url,
        STUDIO_E2E_OWNED="1",
        NEXT_TELEMETRY_DISABLED="1",
        NODE_ENV="production",
    )
    return env


def _spawn(command: list[str], *, cwd: Path, env: dict[str, str]) -> subprocess.Popen:
    return subprocess.Popen(  # noqa: S603 - argv array; no shell or generated code
        command, cwd=cwd, env=env,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        start_new_session=os.name != "nt",
    )


def _stop(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        if proc.poll() is None:
            # The PID is a child we created, never a listener discovered on a port.
            subprocess.run(  # noqa: S603, S607 - Windows process-tree utility, owned PID only
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            )
    else:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        if os.name != "nt":
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            proc.kill()
        proc.wait(timeout=10)


def _stop_children(children: list[subprocess.Popen]) -> None:
    while children:
        _stop(children.pop())


def _wait_ready(url: str, proc: subprocess.Popen, timeout_s: float, data_dir: Path) -> None:
    from packages.core.providers.http_base import PinnedHTTP

    http = PinnedHTTP(timeout_s=2.0, max_retries=0)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"Server exited with code {proc.returncode} before ready: {url}")
        try:
            response = http.request("GET", url, allow_private_hosts=True)
            if response.status_code == 200:
                storage = response.json().get("storage", {})
                if storage.get("data_dir") == str(data_dir):
                    # A successful response must name our temporary storage, not a racing listener.
                    if proc.poll() is None:
                        return
        except Exception:
            pass
        time.sleep(0.25)
    raise RuntimeError(f"Server did not become ready within {timeout_s:g}s: {url}")


def _prepare_dashboard(destination: Path, node: str, env: dict[str, str]) -> None:
    destination.mkdir()
    # Copy source/config only: no operator .env, .next lock/build, probes, or runtime state.
    for name in ("src", "public"):
        source = DASHBOARD / name
        if source.is_dir():
            shutil.copytree(source, destination / name)
    for pattern in (
        "package.json", "package-lock.json", "tsconfig.json", "next-env.d.ts",
        "next.config.*", "postcss.config.*",
    ):
        for source in DASHBOARD.glob(pattern):
            shutil.copy2(source, destination / source.name)
    # Junctions need no Windows developer-mode privileges; dependencies remain read-only inputs.
    subprocess.run(  # noqa: S603 - constant JavaScript, paths passed as argv, no shell
        [node, "-e", "require('node:fs').symlinkSync(process.argv[1], process.argv[2], 'junction')",
         str(DASHBOARD / "node_modules"), str(destination / "node_modules")],
        cwd=ROOT, env=env, check=True,
    )


def main(argv: list[str]) -> int:
    children: list[subprocess.Popen] = []
    try:
        node = shutil.which("node")
        if node is None:
            raise RuntimeError("Node.js is required for the dashboard E2E gate")
        next_cli = DASHBOARD / "node_modules" / "next" / "dist" / "bin" / "next"
        playwright_cli = DASHBOARD / "node_modules" / "@playwright" / "test" / "cli.js"
        if not next_cli.is_file() or not playwright_cli.is_file():
            raise RuntimeError("Install dashboard dependencies with npm ci --include=dev first")
        with ExitStack() as stack:
            tmp = stack.enter_context(tempfile.TemporaryDirectory(prefix="studio-e2e-"))
            stack.callback(_stop_children, children)
            api_socket = stack.enter_context(_reserve_port(os.environ.get("STUDIO_E2E_API_PORT")))
            ui_socket = stack.enter_context(_reserve_port(os.environ.get("STUDIO_E2E_UI_PORT")))
            api_port = api_socket.getsockname()[1]
            ui_port = ui_socket.getsockname()[1]
            api_url = f"http://127.0.0.1:{api_port}"
            ui_url = f"http://127.0.0.1:{ui_port}"
            env = _environment(Path(tmp), api_url, ui_url)
            app = Path(tmp) / "dashboard"
            _prepare_dashboard(app, node, env)
            build_env = env.copy()
            build_env.pop("STUDIO_API_ORIGIN", None)
            # Build without the backend address. next start receives it only at runtime.
            build = _spawn([node, str(next_cli), "build", "--webpack"], cwd=app, env=build_env)
            children.append(build)
            if build.wait(timeout=600) != 0:
                raise RuntimeError("Isolated production dashboard build failed (see output above)")
            try:
                api_socket.close()
                api = _spawn(
                    [sys.executable, "-m", "uvicorn", "apps.api.main:app",
                     "--host", "127.0.0.1", "--port", str(api_port)],
                    cwd=ROOT, env=env,
                )
                children.append(api)
                _wait_ready(f"{api_url}/api/settings", api, 45, Path(env["SHORTS_DATA_DIR"]))
                ui_socket.close()
                ui = _spawn(
                    [node, str(next_cli), "start", "--hostname", "127.0.0.1",
                     "--port", str(ui_port)], cwd=app, env=env,
                )
                children.append(ui)
                _wait_ready(f"{ui_url}/api/settings", ui, 90, Path(env["SHORTS_DATA_DIR"]))
                print(f"Isolated E2E ready: api={api_url} dashboard={ui_url}", flush=True)
                test_env = {**env, "NODE_ENV": "test"}
                tests = _spawn(
                    [node, str(playwright_cli), "test", *argv], cwd=DASHBOARD, env=test_env,
                )
                children.append(tests)
                return tests.wait()
            finally:
                _stop_children(children)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"FAIL dashboard E2E: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    finally:
        _stop_children(children)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
