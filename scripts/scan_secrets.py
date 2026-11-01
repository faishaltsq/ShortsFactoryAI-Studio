"""Credential-shape scanner: the one gate that catches the failure this repo cares about most.

    uv run python scripts/scan_secrets.py [path]

Exit codes are the contract:

    0  no credential-shaped string in the scanned tree
    1  at least one finding, printed as ``path:line: pattern-name``

The value is never printed. A scanner that echoes the secret into CI logs has moved the leak, not
found it — so only the file, the line and the *name* of the matched pattern are reported.

Scanned: source, config and docs under the given path (default: the repository root), excluding
vendored and runtime trees. Those exclusions matter: ``.venv`` contains hundreds of
credential-shaped strings by design, ``data/`` holds job artifacts, and scanning either would make
the gate permanently red and therefore ignored.
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Never scanned. Vendored code and runtime state are not this repository's source, and a gate
#: that is always red is a gate that gets bypassed.
EXCLUDED_DIRS = frozenset(
    {".venv", "venv", "node_modules", "data", ".git", "__pycache__", ".next", "test-results",
     "dist", "build", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".agents", ".hermes"}
)

#: Extensions worth reading. A binary file cannot contain a literal credential in a useful form,
#: and decoding one produces false positives.
TEXT_SUFFIXES = frozenset(
    {".py", ".ps1", ".sh", ".bat", ".cmd", ".toml", ".md", ".txt", ".json", ".jsonc", ".yml",
     ".yaml", ".ini", ".cfg", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".env", ".example",
     ".sql", ".css", ".html", ""}
)

#: Filenames with no suffix that are still text.
TEXT_NAMES = frozenset({".env", ".env.example", "Dockerfile", "Makefile"})

MAX_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    pattern: str

    def render(self) -> str:
        """``path:line: pattern-name``. No value, no fragment of one."""
        return f"{self.path}:{self.line}: {self.pattern}"


#: Each pattern is named, so a finding says *what kind* of credential leaked without repeating it.
PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openai-style-key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}")),
    ("anthropic-style-key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{16,}")),
    ("bearer-token", re.compile(r"Bearer\s+[A-Za-z0-9._\-]{16,}")),
    ("private-key-header", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----")),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("api-key-assignment", re.compile(r"(?i)\b(?:api[_-]?key|apikey|access[_-]?key)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{20,}")),
    ("token-assignment", re.compile(r"(?i)\b(?:token|secret|password|passwd|client[_-]?secret)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{20,}")),
)

#: A high-entropy value assigned to a credential-ish name. Separated from the patterns above
#: because it needs a length and an entropy check rather than a shape.
ENV_ASSIGNMENT = re.compile(
    r"(?i)\b[A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL)[A-Z0-9_]*\s*=\s*['\"]?([A-Za-z0-9_\-+/=]{32,})"
)

#: Values that are obviously placeholders. Excluding them keeps the gate honest: `TOKEN=changeme`
#: in an example file is documentation, not a leak.
PLACEHOLDERS = re.compile(
    r"(?i)^(?:change[-_]?me|your[-_]?|placeholder|example|dummy|xxx+|\.\.\.|<.*>|\$\{.*\}|"
    r"[a-z]+[-_]?(?:here|value|goes[-_]?here)|redacted|test[-_]?|fake[-_]?)"
)

#: A *named* sentinel is a value the repository uses to prove redaction works — it appears in
#: `tests/conftest.py`, in the redaction tests and in the provider tests. It is deliberately
#: credential-shaped and deliberately not a credential. Matching it exactly is narrower than
#: excluding `tests/`, which would hide a real key committed next to a test.
SENTINEL_MARKERS = re.compile(r"(?i)SENTINEL|DO-NOT-LEAK")

#: Values a test asserts redaction on. They are in the same category: shaped like a credential so
#: the redactor has something to remove, and meaningless outside the assertion.
#:
#: Scoped to *files that are allowed to contain them*. A global value allowlist would let the same
#: string pass anywhere in the tree — which is exactly how a real key gets missed after someone
#: copies a fixture. `tests/test_redact.py` is the only file that needs these, because it is the
#: file whose job is to prove redaction removes them.
FIXTURE_FILES = frozenset({"tests/test_redact.py"})

#: Files that legitimately contain credential-shaped *regex source* rather than credentials: this
#: scanner's own pattern table, and its tests which plant values on purpose. Named explicitly, so
#: a new file cannot inherit the exemption by sitting in the same directory.
PATTERN_SOURCE_FILES = frozenset({"scripts/scan_secrets.py"})
DOCUMENTED_FIXTURES = frozenset(
    {
        "sk-proj-9f4c2a1b8e7d6c5f4a3b2c1d0e9f8a7b",
        "sk-abcdefghijkl",
        "abcdef1234567890",
        "abcdef123456.xyz",
        "a8f5f167f44f4964e6c998dee827110c9b2e0f4a",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N",
    }
)


def _is_fixture(relative_path: str, line: str) -> bool:
    """True when the line is a documented sentinel rather than an unknown credential."""
    if SENTINEL_MARKERS.search(line):
        return True
    if relative_path in FIXTURE_FILES:
        return any(fixture in line for fixture in DOCUMENTED_FIXTURES)
    return False


def _entropy(value: str) -> float:
    """Shannon entropy in bits per character. Random hex is ~4.0; English prose is ~3.0."""
    if not value:
        return 0.0
    counts: dict[str, int] = {}
    for char in value:
        counts[char] = counts.get(char, 0) + 1
    total = len(value)
    return -sum((count / total) * math.log2(count / total) for count in counts.values())


def _looks_random(value: str) -> bool:
    if PLACEHOLDERS.match(value):
        return False
    # A path, a URL or a dotted identifier is not a secret.
    if any(marker in value for marker in ("/", "\\", "://", " ", ".")):
        return False
    return _entropy(value) >= 3.2


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _iter_files(root: Path) -> Iterator[Path]:
    for path in sorted(root.rglob("*")):
        if any(part in EXCLUDED_DIRS for part in path.parts):
            continue
        if not path.is_file():
            continue
        if _relative(path, root) in PATTERN_SOURCE_FILES:
            continue
        if path.name in TEXT_NAMES or path.suffix.lower() in TEXT_SUFFIXES:
            try:
                if path.stat().st_size > MAX_BYTES:
                    continue
            except OSError:
                continue
            yield path


def scan(root: Path) -> list[Finding]:
    """Every credential-shaped string under ``root``, as ``(path, line, pattern-name)``."""
    findings: list[Finding] = []
    for path in _iter_files(root):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if _is_fixture(_relative(path, root), line):
                continue
            for name, pattern in PATTERNS:
                if pattern.search(line):
                    findings.append(Finding(_relative(path, root), number, name))
                    break
            else:
                for match in ENV_ASSIGNMENT.finditer(line):
                    if _looks_random(match.group(1)):
                        findings.append(Finding(_relative(path, root), number, "high-entropy-assignment"))
                        break
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan for credential-shaped strings.")
    parser.add_argument("path", nargs="?", default=str(ROOT), help="root to scan")
    args = parser.parse_args(argv)

    root = Path(args.path).resolve()
    if not root.exists():
        print(f"ERROR: {root} does not exist", file=sys.stderr)
        return 2

    findings = scan(root)
    if not findings:
        print(f"scan_secrets: 0 findings in {root}")
        return 0
    for finding in findings:
        print(finding.render())
    print(f"\nscan_secrets: {len(findings)} finding(s)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
