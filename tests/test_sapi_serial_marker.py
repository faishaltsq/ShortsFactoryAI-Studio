"""The SAPI tests must not run concurrently, and the marker that says so must exist.

A verifier measured that three concurrent pytest processes make `sapi_tts.ps1` fail with
`NamedParameterNotFound`: several tests drive the same PowerShell SAPI COM object at once and the
parameter binding is not process-isolated. Nothing in the suite enforced exclusion, so a CI runner
that parallelises at process level would flake on tests that pass perfectly in sequence.

`slow` already exists but answers a different question — how long a test takes. Concurrency is a
separate axis, so it gets a separate marker. These tests guard the registration and the annotation,
because an unregistered marker is only a warning and would be lost silently.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_serial_marker_is_registered():
    """An unregistered marker is a warning, not an error, so nothing else would catch its loss."""
    config = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    markers = config[config.index("markers = ["):]
    assert "serial:" in markers, "the serial marker must be registered in pyproject.toml"


def test_the_real_sapi_tests_are_marked_serial():
    """Only the tests that actually spawn PowerShell: the monkeypatched ones touch no COM object."""
    source = (ROOT / "tests" / "test_media_tts.py").read_text(encoding="utf-8")
    for name in (
        "test_real_sapi_boundaries_preserve_source_punctuation",
        "test_real_sapi_boundaries_never_emit_empty_text_for_alphanumeric_token",
    ):
        block = _block(source, name)
        assert "@pytest.mark.serial" in block, f"{name} spawns PowerShell and must be marked serial"


def test_a_monkeypatched_sapi_test_is_not_marked_serial():
    """It replaces subprocess.run, so it never reaches PowerShell and need not be exclusive."""
    source = (ROOT / "tests" / "test_media_tts.py").read_text(encoding="utf-8")
    block = _block(source, "test_sapi_passes_text_by_file_and_removes_partial_outputs")
    assert "@pytest.mark.serial" not in block


def test_the_audio_timing_module_is_marked_serial():
    """The whole module is real SAPI, so it carries the marker at module level."""
    source = (ROOT / "tests" / "test_audio_timing.py").read_text(encoding="utf-8")
    assert re.search(r"^pytestmark = \[.*pytest\.mark\.serial", source, re.MULTILINE | re.DOTALL), (
        "test_audio_timing.py runs real SAPI throughout and must be marked serial"
    )


def _block(source: str, name: str) -> str:
    """The decorators and body of one test, up to the next top-level def."""
    start = source.index(f"def {name}(")
    # Walk back over any decorator lines directly above the def.
    lines = source[:start].splitlines()
    decorators = []
    for line in reversed(lines):
        if line.startswith("@"):
            decorators.append(line)
        elif line.strip() == "" and not decorators:
            continue
        else:
            break
    end = source.find("\ndef ", start + 1)
    body = source[start : end if end != -1 else len(source)]
    return "\n".join(decorators) + "\n" + body
