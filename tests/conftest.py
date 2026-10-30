"""Shared fixtures. No test may reach the network or require a real credential."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SECRET_SENTINEL = "sk-SENTINEL-4f19c2ae-DO-NOT-LEAK"


def pytest_configure(config: pytest.Config) -> None:
    """Isolate module-level API construction before collection imports ``apps.api.main``."""
    temporary = tempfile.TemporaryDirectory(prefix="shorts-pytest-collection-")
    root = Path(temporary.name)
    patch = pytest.MonkeyPatch()
    for key, path in {
        "SHORTS_DATA_DIR": root / "data",
        "SHORTS_DB_PATH": root / "data" / "factory.db",
        "SHORTS_JOBS_DIR": root / "data" / "jobs",
        "SHORTS_SECRETS_DIR": root / "data" / "secrets",
        "SHORTS_STUDIO_CONFIG": root / "config" / "studio.json",
    }.items():
        patch.setenv(key, str(path))
    patch.setenv("SHORTS_SCHEDULER_ENABLED", "0")
    config.add_cleanup(patch.undo)
    config.add_cleanup(temporary.cleanup)


@pytest.fixture(autouse=True)
def _isolate_operator_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point ``SHORTS_STUDIO_CONFIG`` at the test's own temp directory.

    `AppState.build` loads provider declarations from `config/studio.json`. Without this
    fixture, an operator who declares a real provider there leaks it into every test â
    the "live mode with no provider must fail" test, among others, silently gains a provider
    and passes for the wrong reason. Tests that want a configured provider declare one explicitly.
    """
    monkeypatch.setenv("SHORTS_STUDIO_CONFIG", str(tmp_path / "config" / "studio.json"))


@pytest.fixture
def sentinel_secret() -> str:
    """A credential-shaped string that must never appear in any output."""
    return SECRET_SENTINEL


@pytest.fixture
def tmp_jobs(tmp_path: Path) -> Path:
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    return jobs
