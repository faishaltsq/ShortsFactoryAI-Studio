"""Dependency direction, checked rather than documented.

A comment saying "core must not import fastapi" has never stopped anyone. This parses the import
graph and fails.
"""

from __future__ import annotations

import ast
import re
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


# -- the 3D agent office is a separate application feature -------------------------------------

THREE_STUDIO = ROOT / "apps" / "dashboard" / "src" / "three"


def _ts_imports(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    return set(re.findall(r"from\s+['\"]([^'\"]+)['\"]", text)) | set(
        re.findall(r"import\(\s*['\"]([^'\"]+)['\"]\s*\)", text)
    )


def test_the_3d_office_imports_nothing_from_the_video_engine():
    """The virtual office must outlive the video engine.

    It is a React Three Fiber application with its own agents, animation and event wiring. It
    shares no module with `packages/video`, so retiring the video character system cannot reach it.
    This fails the day someone imports a renderer helper into the studio.
    """
    offenders: list[str] = []
    for path in THREE_STUDIO.rglob("*.ts*"):
        for specifier in _ts_imports(path):
            if "packages/video" in specifier or "packages/core" in specifier:
                offenders.append(f"{path.relative_to(ROOT)} imports {specifier}")
    assert not offenders, offenders


def test_the_video_engine_imports_nothing_from_the_dashboard():
    """The exported film is produced by Remotion alone; a dashboard import would couple the two."""
    video = ROOT / "packages" / "video" / "src"
    offenders: list[str] = []
    for path in video.rglob("*.ts*"):
        for specifier in _ts_imports(path):
            if "apps/dashboard" in specifier or specifier.startswith("@/"):
                offenders.append(f"{path.relative_to(ROOT)} imports {specifier}")
    assert not offenders, offenders


def test_the_object_vocabulary_agrees_across_languages():
    """`OBJECT_KINDS` is the only thing stopping a blank box on screen.

    The TypeScript library draws; the Python contract validates. If the two lists drift, the
    storyboard can name an object the renderer cannot draw and the QC gate would still pass.
    """
    from packages.core.contracts.scene import OBJECT_KINDS

    source = (ROOT / "packages" / "video" / "src" / "art" / "object-kinds.ts").read_text(encoding="utf-8")
    block = source[source.index("export const OBJECT_KINDS") : source.index("] as const;")]
    shipped = tuple(re.findall(r"'([a-zA-Z]+)'", block))
    assert shipped == OBJECT_KINDS, (shipped, OBJECT_KINDS)


def test_the_environment_vocabulary_agrees_across_languages():
    from packages.core.contracts.scene import ENVIRONMENTS

    source = (ROOT / "packages" / "video" / "src" / "art" / "palette.ts").read_text(encoding="utf-8")
    block = source[source.index("export const ENVIRONMENTS") : source.index("] as const;")]
    shipped = tuple(re.findall(r"'([a-zA-Z]+)'", block))
    assert shipped == ENVIRONMENTS, (shipped, ENVIRONMENTS)
