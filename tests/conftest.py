"""Shared fixtures. No test may reach the network or require a real credential."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SECRET_SENTINEL = "sk-SENTINEL-4f19c2ae-DO-NOT-LEAK"


@pytest.fixture
def sentinel_secret() -> str:
    """A credential-shaped string that must never appear in any output."""
    return SECRET_SENTINEL


@pytest.fixture
def tmp_jobs(tmp_path: Path) -> Path:
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    return jobs
