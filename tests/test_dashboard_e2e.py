"""E2E startup must never reuse an operator listener, environment, or build."""
from __future__ import annotations

import os
import socket
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import dashboard_e2e as harness


def test_occupied_loopback_port_is_rejected_without_closing_listener():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as operator:
        operator.bind(("127.0.0.1", 0))
        operator.listen(2)
        port = operator.getsockname()[1]
        with pytest.raises(RuntimeError, match="Cannot reserve"):
            harness._reserve_port(str(port))
        assert operator.fileno() >= 0
        assert operator.getsockname()[1] == port


def test_os_selected_ports_are_distinct_and_reserved():
    with harness._reserve_port(None) as api, harness._reserve_port(None) as dashboard:
        assert api.getsockname()[1] != dashboard.getsockname()[1]
        with pytest.raises(RuntimeError):
            harness._reserve_port(str(api.getsockname()[1]))


@pytest.mark.parametrize("value", ["not-a-port", "-1", "65536"])
def test_invalid_port_fails_before_startup(value):
    with pytest.raises(RuntimeError):
        harness._reserve_port(value)


def test_child_environment_does_not_adopt_operator_paths_or_mutate_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("SHORTS_DATA_DIR", "operator-data")
    monkeypatch.setenv("SHORTS_STUDIO_CONFIG", "operator-config")
    monkeypatch.setenv("STUDIO_API_TOKEN", "operator-token")
    monkeypatch.setenv("STUDIO_URL", "http://127.0.0.1:3018")
    before = os.environ.copy()
    env = harness._environment(tmp_path, "http://127.0.0.1:41001", "http://127.0.0.1:41002")
    for key in (
        "SHORTS_DATA_DIR", "SHORTS_DB_PATH", "SHORTS_JOBS_DIR", "SHORTS_SECRETS_DIR",
        "SHORTS_STUDIO_CONFIG", "STUDIO_E2E_DATA",
    ):
        assert Path(env[key]).is_relative_to(tmp_path)
    assert env["STUDIO_API_ORIGIN"] == env["STUDIO_E2E_API"] == "http://127.0.0.1:41001"
    assert env["STUDIO_URL"] == "http://127.0.0.1:41002"
    assert "STUDIO_API_TOKEN" not in env
    assert os.environ == before


def test_readiness_rejects_exited_child_before_querying_any_listener(monkeypatch):
    from packages.core.providers.http_base import PinnedHTTP

    def no_request(*args, **kwargs):
        pytest.fail("an exited child must not adopt a listener on its port")

    monkeypatch.setattr(PinnedHTTP, "request", no_request)
    process = SimpleNamespace(poll=lambda: 7, returncode=7)
    with pytest.raises(RuntimeError, match="exited with code 7"):
        harness._wait_ready("http://127.0.0.1:41001/api/settings", process, 1, Path("isolated-data"))


def test_readiness_does_not_adopt_errors_redirects_or_another_servers_data(monkeypatch):
    from packages.core.providers.http_base import PinnedHTTP

    statuses = iter([(404, None), (302, None), (200, "operator-data"), (200, "isolated-data")])
    observed = []

    def request(*args, **kwargs):
        status, data_dir = next(statuses)
        observed.append((status, data_dir))
        return SimpleNamespace(status_code=status, json=lambda: {"storage": {"data_dir": data_dir}})

    monkeypatch.setattr(PinnedHTTP, "request", request)
    monkeypatch.setattr(harness.time, "sleep", lambda _: None)
    harness._wait_ready("http://127.0.0.1:41001/api/settings", SimpleNamespace(poll=lambda: None), 1, Path("isolated-data"))
    assert observed == [(404, None), (302, None), (200, "operator-data"), (200, "isolated-data")]


@pytest.mark.parametrize("failure", ["build", "build-timeout", "dashboard", "tests"])
def test_startup_failure_stops_owned_children_before_removing_temp_root(tmp_path, monkeypatch, failure):
    app = tmp_path / "operator-dashboard"
    for relative in ("next/dist/bin/next", "@playwright/test/cli.js"):
        cli = app / "node_modules" / relative
        cli.parent.mkdir(parents=True, exist_ok=True)
        cli.touch()
    (app / "src").mkdir()
    (app / "src" / "page.tsx").write_text("export default function Page() { return null; }")
    (app / ".env.local").write_text("operator secret")
    (app / ".next").mkdir()
    (app / ".next" / "lock").write_text("operator build")
    monkeypatch.setattr(harness, "DASHBOARD", app)
    monkeypatch.setattr(harness.shutil, "which", lambda _: "node")
    monkeypatch.setattr(harness.time, "sleep", lambda _: None)
    monkeypatch.delenv("STUDIO_E2E_API_PORT", raising=False)
    monkeypatch.delenv("STUDIO_E2E_UI_PORT", raising=False)
    # Only the external process boundary is replaced; main still reserves ports, copies source,
    # creates the environment, handles return codes, and removes its actual temporary directory.
    spawned = []
    stopped = []
    roots = []

    def run(command, **kwargs):
        # This is dependency linking only; no build/test command may go through a shell.
        return SimpleNamespace(returncode=0)

    class Process:
        def __init__(self, command, **kwargs):
            self.command = command
            self.env = kwargs["env"]
            self.cwd = Path(kwargs["cwd"])
            self.kind = (
                "build" if "build" in command else "dashboard" if "start" in command
                else "api" if "uvicorn" in command else "tests"
            )
            spawned.append(self)
            roots.append(Path(self.env["STUDIO_E2E_DATA"]).parent)
            self.returncode = None
            assert kwargs.get("shell", False) is False
            if self.kind == "build":
                assert not (self.cwd / ".env.local").exists()
                assert not (self.cwd / ".next").exists()
            if self.kind == "dashboard" and failure == "dashboard":
                raise OSError("dashboard startup failure")

        def wait(self, timeout=None):
            if self.kind == "build" and failure == "build-timeout":
                raise subprocess.TimeoutExpired(self.command, timeout)
            self.returncode = 5 if self.kind == failure else 0
            return self.returncode

        def poll(self):
            return self.returncode

    monkeypatch.setattr(harness.subprocess, "Popen", Process)
    monkeypatch.setattr(harness.subprocess, "run", run)
    monkeypatch.setattr(harness, "_wait_ready", lambda *args: None)

    def stop(process):
        assert Path(process.env["STUDIO_E2E_DATA"]).parent.is_dir()
        stopped.append(process.kind)

    monkeypatch.setattr(harness, "_stop", stop)
    result = harness.main(["--grep", "studio"])
    assert result == (5 if failure == "tests" else 2)
    expected = [process.kind for process in spawned if not (
        process.kind == "dashboard" and failure == "dashboard"
    )]
    assert stopped == list(reversed(expected))
    assert all(not root.exists() for root in roots)
    assert (app / ".next" / "lock").read_text() == "operator build"
    assert (app / ".env.local").read_text() == "operator secret"
