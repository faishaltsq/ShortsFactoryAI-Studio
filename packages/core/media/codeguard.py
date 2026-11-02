from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

ALLOWED_PACKAGES: frozenset[str] = frozenset({"react", "remotion"})

DISALLOWED_PACKAGES: frozenset[str] = frozenset({
    "child_process",
    "cluster",
    "dgram",
    "dns",
    "fs",
    "http",
    "https",
    "net",
    "os",
    "process",
    "tls",
    "v8",
    "vm",
    "worker_threads",
})

DANGEROUS_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\beval\b"), "eval"),
    (re.compile(r"\bFunction\b"), "Function()"),
    (
        re.compile(r"\b(?:window|globalThis)\s*(?:\.\s*fetch\b|\[\s*['\"`]fetch['\"`]\s*\])"),
        "window.fetch",
    ),
    (re.compile(r"\bfetch\s*(?:[\(`]|\)\s*[\(`])"), "fetch()"),
    (re.compile(r"\blocalStorage\b"), "localStorage"),
    (re.compile(r"\bsessionStorage\b"), "sessionStorage"),
    (
        re.compile(r"\bdocument\s*(?:\.\s*cookie\b|\[\s*['\"`]cookie['\"`]\s*\])"),
        "document.cookie",
    ),
    (re.compile(r"\bXMLHttpRequest\b"), "XMLHttpRequest"),
    (re.compile(r"\bWebSocket\b"), "WebSocket"),
    (re.compile(r"\bprocess\b"), "process"),
    (re.compile(r"\bglobal\b"), "global"),
    (re.compile(r"\bglobalThis\b"), "globalThis"),
    (re.compile(r"\.constructor\b"), "constructor access"),
    (re.compile(r"\[\s*['\"`]constructor['\"`]\s*\]"), "constructor access"),
    (re.compile(r"\brequire\b"), "require"),
    (re.compile(r"\bimport\s*[\(`]"), "dynamic import()"),
)

COMMENT_STRIP_RE = re.compile(
    r"""
    (?P<string>
        "(?:\\.|[^"\\\r\n])*"
      | '(?:\\.|[^'\\\r\n])*'
      | `(?:\\.|[^`\\])*`
    )
  | (?P<comment>
        /\*[\s\S]*?(?:\*/|$)
      | //[^\r\n]*
    )
    """,
    re.VERBOSE,
)

IMPORT_FROM_RE = re.compile(
    r"""\b(?:import|export)(?:\s+(?:type\s+)?|\s*(?=\*))(?:[^;=\(\)>]*?\bfrom\s*)(['"])([^'"]+)\1"""
)
IMPORT_BARE_RE = re.compile(r"""\bimport\s*(['"])([^'"]+)\1""")
IMPORT_DYNAMIC_RE = re.compile(r"""\b(?:import|require)\s*\(\s*(['"`])([^'"`]+)\1\s*\)""")

ILLEGAL_PATH_CHARS: frozenset[str] = frozenset("<>:\"|?*\\")


@dataclass
class CodeGuardResult:
    valid: bool
    issues: list[str] = field(default_factory=list)
    imported_modules: list[str] = field(default_factory=list)


class CodeGuard:
    ALLOWED_PACKAGES = ALLOWED_PACKAGES
    DISALLOWED_PACKAGES = DISALLOWED_PACKAGES
    DANGEROUS_PATTERNS = DANGEROUS_PATTERNS
    COMMENT_STRIP_RE = COMMENT_STRIP_RE

    def __init__(
        self,
        allowed_packages: frozenset[str] | set[str] | None = None,
        disallowed_packages: frozenset[str] | set[str] | None = None,
    ) -> None:
        self.allowed = (
            frozenset(allowed_packages) if allowed_packages is not None else self.ALLOWED_PACKAGES
        )
        self.disallowed = (
            frozenset(disallowed_packages)
            if disallowed_packages is not None
            else self.DISALLOWED_PACKAGES
        )

    @classmethod
    def strip_comments(cls, source: str) -> str:
        def _replace(match: re.Match[str]) -> str:
            if match.group("comment"):
                comment = match.group("comment")
                return "\n" * comment.count("\n") if "\n" in comment else " "
            return match.group(0)

        return cls.COMMENT_STRIP_RE.sub(_replace, source)

    def _is_allowed_module(self, mod: str) -> bool:
        clean = mod.strip()
        if not clean:
            return False

        if any(ord(c) < 32 or c == "\0" for c in clean):
            return False

        # Strictly prohibit absolute paths starting with / or \ or Windows drive letter (e.g. C:/...)
        if clean.startswith(("/", "\\")) or (
            len(clean) >= 2 and clean[1] == ":" and clean[0].isalpha()
        ):
            return False

        # Check against disallowed list
        normalized_name = clean.removeprefix("node:").split("/")[0]
        if normalized_name in self.disallowed or clean in self.disallowed:
            return False

        parts = [p for p in clean.replace("\\", "/").split("/") if p]
        forbidden_dirs = {"node_modules", "config", "secrets", "core", ".env", ".git"}
        if any(p in forbidden_dirs for p in parts):
            return False
        if any("secret" in p.lower() or "config" in p.lower() for p in parts):
            return False

        # 1. Exact match in allowlist (e.g. 'react', 'remotion')
        if clean in self.allowed:
            return True

        # 2. @remotion/<subpath> without '..' traversal or illegal characters
        if clean.startswith("@remotion/"):
            subpath = clean[len("@remotion/"):]
            if not subpath or any(ch in ILLEGAL_PATH_CHARS for ch in subpath):
                return False
            subparts = subpath.split("/")
            if any(part in {"..", ".", ""} for part in subparts):
                return False
            return True

        # 3. Relative paths:
        if clean.startswith(("./", "../")):
            if any(ch in ILLEGAL_PATH_CHARS for ch in clean):
                return False
            # Check if it's a local sibling (starts with ./ and contains no ..)
            if clean.startswith("./") and ".." not in parts:
                return True
            # If it traverses with .., it must strictly target video/src:
            # All '..' must precede 'video' / 'src', and no '..' allowed after 'src'
            video_idx = -1
            for i in range(len(parts) - 1):
                if parts[i] == "video" and parts[i + 1] == "src":
                    video_idx = i
                    break
            if video_idx != -1:
                before_video = parts[:video_idx]
                if all(p in {"..", "packages"} for p in before_video):
                    after_src = parts[video_idx + 2 :]
                    if after_src and not any(p in {"..", "."} for p in after_src):
                        return True
            return False

        # 4. packages/video/src/... without '..' traversal
        if clean.startswith("packages/video/src/"):
            subpath = clean[len("packages/video/src/"):]
            if not subpath or any(ch in ILLEGAL_PATH_CHARS for ch in subpath):
                return False
            subparts = subpath.split("/")
            if any(part in {"..", "."} for part in subparts):
                return False
            return True

        return False

    def _extract_imports(self, source: str) -> list[str]:
        modules: list[str] = []
        for m in IMPORT_FROM_RE.finditer(source):
            modules.append(m.group(2).strip())
        for m in IMPORT_BARE_RE.finditer(source):
            modules.append(m.group(2).strip())
        for m in IMPORT_DYNAMIC_RE.finditer(source):
            modules.append(m.group(2).strip())
        return modules

    def validate_source(self, source: str, filename: str = "snippet.tsx") -> CodeGuardResult:
        issues: list[str] = []
        clean_source = self.strip_comments(source)
        imports = self._extract_imports(clean_source)
        deduped_imports = list(dict.fromkeys(imports))

        for mod in deduped_imports:
            if not self._is_allowed_module(mod):
                issues.append(f"{filename}: Disallowed import: {mod}")

        for pattern, label in self.DANGEROUS_PATTERNS:
            if pattern.search(clean_source):
                issues.append(f"{filename}: Forbidden token or call: '{label}'")

        # Invoke AST inspection via ast_guard.mjs when node is available
        node = shutil.which("node")
        ast_script = Path(__file__).resolve().parents[3] / "packages" / "video" / "scripts" / "ast_guard.mjs"
        if node and ast_script.is_file():
            try:
                proc = subprocess.run(
                    [node, str(ast_script), filename],
                    input=source,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    capture_output=True,
                    timeout=15,
                    check=False,
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    data = json.loads(proc.stdout)
                    ast_issues = data.get("issues", [])
                    if isinstance(ast_issues, list):
                        for iss in ast_issues:
                            if iss not in issues:
                                issues.append(str(iss))
                    ast_imports = data.get("imported_modules", [])
                    if isinstance(ast_imports, list):
                        for imp in ast_imports:
                            if imp not in deduped_imports:
                                deduped_imports.append(str(imp))
                elif proc.returncode != 0:
                    err_msg = proc.stderr.strip() or f"Process exited with {proc.returncode}"
                    issues.append(f"{filename}: AST validator failed: {err_msg[:300]}")
            except Exception as exc:
                issues.append(f"{filename}: AST validation error: {exc}")

        return CodeGuardResult(
            valid=len(issues) == 0,
            issues=issues,
            imported_modules=deduped_imports,
        )

    def validate_file(self, file_path: str | Path) -> CodeGuardResult:
        path = Path(file_path)
        try:
            if not path.exists():
                return CodeGuardResult(
                    valid=False,
                    issues=[f"File does not exist: {path}"],
                    imported_modules=[],
                )
            if not path.is_file():
                return CodeGuardResult(
                    valid=False,
                    issues=[f"Path is not a file: {path}"],
                    imported_modules=[],
                )
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as err:
            return CodeGuardResult(
                valid=False,
                issues=[f"Error reading file {path}: {err}"],
                imported_modules=[],
            )
        return self.validate_source(content, filename=path.name)

    def validate_directory(self, dir_path: str | Path) -> CodeGuardResult:
        path = Path(dir_path)
        try:
            if not path.exists():
                return CodeGuardResult(
                    valid=False,
                    issues=[f"Directory does not exist: {path}"],
                    imported_modules=[],
                )
            if path.is_file():
                return self.validate_file(path)
            if not path.is_dir():
                return CodeGuardResult(
                    valid=False,
                    issues=[f"Path is not a directory: {path}"],
                    imported_modules=[],
                )
        except OSError as err:
            return CodeGuardResult(
                valid=False,
                issues=[f"Error accessing directory {path}: {err}"],
                imported_modules=[],
            )

        all_issues: list[str] = []
        all_modules: list[str] = []

        try:
            code_files = [
                p
                for p in path.rglob("*")
                if p.is_file() and p.suffix.lower() in {".tsx", ".ts", ".jsx", ".js", ".mjs", ".cjs"}
            ]
            code_files.sort()
        except OSError as err:
            return CodeGuardResult(
                valid=False,
                issues=[f"Error scanning directory {path}: {err}"],
                imported_modules=[],
            )

        for file_path in code_files:
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except OSError as err:
                all_issues.append(f"Error reading file {file_path}: {err}")
                continue
            try:
                rel_name = str(file_path.relative_to(path))
            except ValueError:
                rel_name = file_path.name
            file_result = self.validate_source(content, filename=rel_name)
            all_issues.extend(file_result.issues)
            all_modules.extend(file_result.imported_modules)

        deduped_modules = list(dict.fromkeys(all_modules))
        return CodeGuardResult(
            valid=len(all_issues) == 0,
            issues=all_issues,
            imported_modules=deduped_modules,
        )
