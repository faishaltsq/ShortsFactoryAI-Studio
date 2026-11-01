"""The two cross-cutting gates must be runnable and must fail when they should.

Both scripts are cited in the roadmap's gate table. They did not exist, so two of the eight gates
could not run at all — a gate nobody can execute is worse than a missing one, because the table
reads as if the check happens.

Each gate is proven both ways: a clean tree exits 0, and a planted defect exits 1. The sentinels
are created in ``tmp_path`` and never written into the repository.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN = ROOT / "scripts" / "scan_secrets.py"
EXPORT = ROOT / "scripts" / "export_schemas.py"
BENCHMARKS = ROOT / "scripts" / "run_causal_benchmarks.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# -- scan_secrets ------------------------------------------------------------------------------


def test_scan_secrets_exists():
    assert SCAN.is_file(), "the roadmap cites this gate; a missing script cannot be run"


def test_a_clean_tree_exits_zero():
    result = subprocess.run(  # noqa: S603 - argv array, no shell
        [sys.executable, str(SCAN)], capture_output=True, text=True, cwd=str(ROOT), check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_a_planted_openai_key_exits_one(tmp_path):
    """The failure mode this repo cares about most, planted where a real leak would be."""
    target = tmp_path / "config.py"
    target.write_text('API_KEY = "sk-' + 'proj-9f4c2a1b8e7d6c5f4a3b2c1d0e9f8a7b"\n', encoding="utf-8")
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(SCAN), str(tmp_path)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 1
    assert "config.py" in result.stdout


def test_the_matched_value_is_never_printed(tmp_path):
    secret = "sk-" + "proj-9f4c2a1b8e7d6c5f4a3b2c1d0e9f8a7b"
    (tmp_path / "leak.py").write_text(f'key = "{secret}"\n', encoding="utf-8")
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(SCAN), str(tmp_path)], capture_output=True, text=True, check=False
    )
    combined = result.stdout + result.stderr
    assert secret not in combined, "the scanner must name the pattern, never the value"
    assert "9f4c2a1b" not in combined


def test_a_bearer_token_exits_one(tmp_path):
    (tmp_path / "a.ts").write_text(
        'headers = {"Authorization": "Bearer ' + 'abcdef1234567890"}\n', encoding="utf-8"
    )
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(SCAN), str(tmp_path)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 1


def test_a_private_key_header_exits_one(tmp_path):
    """The header is assembled at runtime so this test file is not itself a finding.

    A scanner that cannot scan its own tests is a scanner whose tests do not run — and one that
    exempts `tests/` cannot see a real key committed beside a fixture.
    """
    header = "-----BEGIN " + "RSA PRIVATE KEY" + "-----"
    (tmp_path / "id.txt").write_text(header + "\nabc\n", encoding="utf-8")
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(SCAN), str(tmp_path)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 1
    assert "private-key-header" in result.stdout


def test_a_high_entropy_env_assignment_exits_one(tmp_path):
    (tmp_path / ".env").write_text(
        "SERVICE_TOKEN=" + "a8f5f167f44f4964e6c998dee827110c9b2e0f4a\n", encoding="utf-8"
    )
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(SCAN), str(tmp_path)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 1


def test_a_short_or_low_entropy_assignment_is_not_a_finding(tmp_path):
    (tmp_path / ".env").write_text("TOKEN=changeme\nAPI_KEY=your-key-here\n", encoding="utf-8")
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(SCAN), str(tmp_path)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout


def test_the_scan_skips_vendored_and_runtime_directories(tmp_path):
    for name in (".venv", "node_modules", "data", ".git"):
        directory = tmp_path / name
        directory.mkdir()
        (directory / "leak.py").write_text(
            'k = "sk-' + 'proj-9f4c2a1b8e7d6c5f4a3b2c1d0e9f8a7b"\n', encoding="utf-8"
        )
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(SCAN), str(tmp_path)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, "vendored and runtime trees are not source"


def test_the_scan_reports_file_and_line(tmp_path):
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "deep.py").write_text(
        "x = 1\ny = 2\nk = 'sk-" + "proj-9f4c2a1b8e7d6c5f4a3b2c1d0e9f8a7b'\n", encoding="utf-8"
    )
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(SCAN), str(tmp_path)], capture_output=True, text=True, check=False
    )
    assert "deep.py:3" in result.stdout


def test_scan_secrets_accepts_a_path_argument():
    module = _load(SCAN, "scan_secrets_mod")
    assert callable(module.scan)
    findings = module.scan(ROOT)
    assert findings == [], f"the repository must be clean: {findings[:3]}"


# -- export_schemas ----------------------------------------------------------------------------


def test_export_schemas_exists():
    assert EXPORT.is_file(), "the roadmap cites this gate; a missing script cannot be run"


def test_the_committed_schemas_match_the_contracts():
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(EXPORT), "--check"], capture_output=True, text=True, cwd=str(ROOT), check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_every_artifact_contract_is_exported():
    directory = ROOT / "config" / "schemas"
    assert directory.is_dir(), "schemas must live in a tracked location"
    names = {path.stem for path in directory.glob("*.json")}
    for expected in (
        "research", "script", "review", "storyboard", "motion-plan", "assets", "audio",
        "render", "technical-qc", "qa", "readiness", "approval", "metadata", "publication",
    ):
        assert expected in names, f"{expected}.json is missing from config/schemas"


def test_an_exported_schema_is_a_real_json_schema():
    payload = json.loads((ROOT / "config" / "schemas" / "qa.json").read_text(encoding="utf-8"))
    assert payload["title"] == "QaArtifact"
    assert payload["type"] == "object"
    assert "properties" in payload


def test_check_fails_when_a_schema_on_disk_is_mutated(tmp_path):
    """The gate's whole purpose: a hand-edited schema must not pass."""
    module = _load(EXPORT, "export_schemas_mod")
    target = tmp_path / "schemas"
    assert module.write_schemas(target) == len(module._contracts()), "every contract must be exported"
    mutated = target / "qa.json"
    payload = json.loads(mutated.read_text(encoding="utf-8"))
    payload["properties"]["extra"] = {"type": "string"}
    mutated.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    assert module.check_schemas(target) == 1


def test_check_fails_when_a_schema_is_missing(tmp_path):
    module = _load(EXPORT, "export_schemas_mod2")
    target = tmp_path / "schemas"
    assert module.write_schemas(target) == len(module._contracts())
    (target / "render.json").unlink()
    assert module.check_schemas(target) == 1


def test_write_then_check_is_clean(tmp_path):
    module = _load(EXPORT, "export_schemas_mod3")
    target = tmp_path / "schemas"
    assert module.write_schemas(target) == len(module._contracts())
    assert module.check_schemas(target) == 0


def test_the_committed_schema_set_matches_the_contracts():
    """A hardcoded count goes stale the moment a contract is added, which is exactly the drift
    this gate exists to catch: the committed set must equal what the models produce now."""
    module = _load(EXPORT, "export_schemas_mod4")
    expected = {f"{kind}.json" for kind in module._contracts()}
    present = {path.name for path in module.SCHEMA_DIR.glob("*.json")}
    assert present == expected

# -- mypy --------------------------------------------------------------------------------------
# The type gate is checked through the real tool, not a re-implementation: a planted type error
# in a scratch package must exit 1, and the repository's own tree must exit 0.

def test_the_committed_core_tree_type_checks():
    result = subprocess.run(  # noqa: S603 - argv array, no shell
        ["uv", "run", "mypy", "packages/core", "--strict"],
        capture_output=True, text=True, cwd=ROOT, timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr

def test_a_planted_type_error_exits_one(tmp_path):
    pkg = tmp_path / "scratch_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "broken.py").write_text(
        "def add(a: int, b: int) -> int:\n    return a + b\n\n\n"
        "result_value: int = add('one', 2)\n",
        encoding="utf-8",
    )
    result = subprocess.run(  # noqa: S603 - argv array, no shell
        ["uv", "run", "mypy", str(pkg), "--strict"],
        capture_output=True, text=True, cwd=ROOT, timeout=300,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "add" in result.stdout


# -- run_causal_benchmarks ---------------------------------------------------------------------


def test_run_causal_benchmarks_exists():
    assert BENCHMARKS.is_file(), "causal benchmarks runner script must exist at scripts/run_causal_benchmarks.py"


def test_run_causal_benchmarks_help():
    result = subprocess.run(
        [sys.executable, str(BENCHMARKS), "--help"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        check=False,
    )
    assert result.returncode == 0
    assert "--benchmark" in result.stdout
    assert "--dry-run" in result.stdout


def test_run_causal_benchmarks_dry_run():
    result = subprocess.run(
        [sys.executable, str(BENCHMARKS), "--dry-run"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        check=False,
    )
    assert result.returncode == 0
    assert "Benchmark A" in result.stdout
    assert "Benchmark B" in result.stdout
    assert "Benchmark C" in result.stdout

