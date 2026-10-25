"""Dependency direction, checked rather than documented.

A comment saying "core must not import fastapi" has never stopped anyone. This parses the import
graph and fails.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "packages" / "core"

FORBIDDEN_IN_CORE = {"fastapi", "starlette", "next", "uvicorn"}


def _modules() -> list[Path]:
    return [p for p in CORE.rglob("*.py") if "__pycache__" not in p.parts]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                found.add(node.module.split(".")[0])
    return found


def test_core_does_not_import_a_web_framework():
    offenders: list[str] = []
    for path in _modules():
        bad = _imports(path) & FORBIDDEN_IN_CORE
        if bad:
            offenders.append(f"{path.relative_to(ROOT)} imports {sorted(bad)}")
    assert not offenders, "\n".join(offenders)


def test_contracts_import_nothing_from_the_project():
    """Relative imports *within* contracts are fine; reaching outside the package is not."""
    contracts = CORE / "contracts"
    offenders: list[str] = []
    for path in contracts.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and node.module.split(".")[0] == "packages":
                    offenders.append(f"{path.name} imports {node.module}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] == "packages":
                        offenders.append(f"{path.name} imports {alias.name}")
    assert not offenders, "\n".join(offenders)
