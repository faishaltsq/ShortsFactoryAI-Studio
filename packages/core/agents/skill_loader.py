from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SkillBundle:
    content: str
    token_estimate: int
    sha256_hash: str
    loaded_skills: list[str] = field(default_factory=list)
    #: ``name -> sha256`` of the *portion actually sent*, not of the file on disk. A skill cut to
    #: fit the budget is recorded as the cut version, so the provenance says what the model read
    #: rather than what happened to be available.
    skill_hashes: dict[str, str] = field(default_factory=dict)


#: Words that carry no selection signal. Deliberately short: a stopword list that grows into a
#: model of English is a list needing maintenance, and the ranking only has to beat "everything,
#: alphabetically".
_SKILL_STOPWORDS = frozenset(
    {
        "the", "and", "for", "with", "that", "this", "from", "into", "your", "you", "are",
        "how", "when", "what", "use", "using", "not", "its", "all", "any", "can", "over",
        "each", "then", "than", "some", "also", "but", "who", "why", "will", "was", "were",
    }
)


@dataclass(frozen=True)
class SkillSummary:
    """One installed skill's name plus the description it declares for itself."""

    name: str
    description: str


class MotionSkillLoader:
    """Discovers and bundles Remotion agent skills for LLM prompt context."""

    def __init__(self, skills_dir: Path | None = None) -> None:
        if skills_dir is None:
            repo_root = Path(__file__).resolve().parents[3]
            candidate = repo_root / ".agents" / "skills"
            self.skills_dir = candidate if candidate.is_dir() else Path(".agents/skills")
        else:
            self.skills_dir = Path(skills_dir)
        self._cache: dict[str, str | None] = {}

    def list_available_skills(self) -> list[str]:
        try:
            if not self.skills_dir.is_dir():
                return []
            skills: list[str] = []
            for item in self.skills_dir.iterdir():
                try:
                    if item.is_dir() and "remotion-" in item.name:
                        skills.append(item.name)
                except (OSError, PermissionError):
                    continue
            return sorted(skills)
        except (OSError, PermissionError):
            return []

    def _resolve_skill_dir(self, name: str) -> Path | None:
        if not name or not name.strip():
            return None
        if any(sep in name for sep in ("/", "\\", "..", "\0")):
            return None
        try:
            if not self.skills_dir.is_dir():
                return None
            base_dir = self.skills_dir.resolve()
        except (OSError, PermissionError, ValueError):
            return None

        candidates = [name]
        if not name.startswith("remotion-"):
            candidates.append(f"remotion-{name}")

        for candidate_name in candidates:
            try:
                candidate = (self.skills_dir / candidate_name).resolve()
                if candidate != base_dir and candidate.is_relative_to(base_dir) and candidate.is_dir():
                    return candidate
            except (OSError, PermissionError):
                continue
        return None

    def summaries(self) -> list[SkillSummary]:
        """Every installed skill's name and its declared description.

        The description is read from the frontmatter, not from the cleaned body — cleaning strips
        that block, and the description is precisely the line each skill wrote to say what it is
        for. Reading the body instead would rank skills on their prose.
        """
        out: list[SkillSummary] = []
        for name in self.list_available_skills():
            skill_dir = self._resolve_skill_dir(name)
            description = ""
            if skill_dir is not None:
                skill_file = skill_dir / "SKILL.md"
                try:
                    if skill_file.is_file():
                        raw = skill_file.read_text(encoding="utf-8", errors="replace")
                        match = re.search(
                            r"^---\s*\n.*?^description:\s*(.+?)\s*$.*?^---\s*$",
                            raw,
                            flags=re.DOTALL | re.MULTILINE,
                        )
                        if match:
                            description = match.group(1).strip().strip("\"'")
                except (OSError, PermissionError):
                    description = ""
            out.append(SkillSummary(name=name, description=description))
        return out

    def rank(self, needs: str | list[str], *, limit: int = 4) -> list[str]:
        """Pick the installed skills whose declared purpose best matches what the shots need.

        Deterministic and cheap: a weighted term overlap over ``name``, ``description`` and
        markdown headings, ties broken by name so two identical runs select identically. It is a
        relevance *filter*, not a ranking model — the point is to stop discarding a typography
        skill for a typography shot because an unrelated one was longer.

        Returns at most ``limit`` names, highest score first. An unrankable request still returns
        something: with no usable terms, every skill scores zero and the first ``limit``
        alphabetically come back, which is the old "just load some" behaviour.
        """
        raw_needs = [needs] if isinstance(needs, str) else list(needs)
        terms = {
            term
            for text in raw_needs
            for term in re.findall(r"[a-z0-9]{3,}", str(text).lower())
            if term not in _SKILL_STOPWORDS
        }
        if limit <= 0:
            return []
        summaries = self.summaries()
        if not terms or not summaries:
            return [summary.name for summary in summaries[:limit]]
        scored: list[tuple[int, str]] = []
        for summary in summaries:
            name = summary.name.lower()
            description = summary.description.lower()
            body = (self._load_skill_text(summary.name) or "").lower()
            headings = " ".join(re.findall(r"^#{1,4}\s*(.+)$", body, flags=re.MULTILINE))
            score = sum(
                5 * (term in name)
                + 3 * (term in description)
                + 2 * (term in headings)
                + 1 * (term in body)
                for term in terms
            )
            scored.append((score, summary.name))
        # ``-score`` then name: an exact tie must not depend on directory iteration order.
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        return [name for _score, name in scored[:limit]]

    def _clean_markdown(self, raw_text: str) -> str:
        text = raw_text.lstrip("\ufeff").replace("\r\n", "\n")
        # Strip YAML frontmatter at start
        text = re.sub(r"^---\s*\n.*?\n---\s*\n?", "", text, flags=re.DOTALL)
        # Strip markdown images / binary asset references
        text = re.sub(r"!\[.*?\]\(.*?\)", "", text)
        text = re.sub(r"<img\b[^>]*>", "", text, flags=re.IGNORECASE)
        # Collapse excessive newlines
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _load_skill_text(self, skill_name: str) -> str | None:
        if skill_name in self._cache:
            return self._cache[skill_name]
        skill_dir = self._resolve_skill_dir(skill_name)
        if skill_dir is None:
            self._cache[skill_name] = None
            return None

        skill_file = skill_dir / "SKILL.md"
        raw: str | None = None
        try:
            if skill_file.is_file():
                raw = skill_file.read_text(encoding="utf-8", errors="replace")
            else:
                md_texts: list[str] = []
                for f in sorted(skill_dir.glob("*.md")):
                    try:
                        if f.is_file():
                            md_texts.append(f.read_text(encoding="utf-8", errors="replace"))
                    except (OSError, PermissionError):
                        continue
                if not md_texts:
                    self._cache[skill_name] = None
                    return None
                raw = "\n\n".join(md_texts)
        except (OSError, PermissionError):
            self._cache[skill_name] = None
            return None

        if raw is None:
            self._cache[skill_name] = None
            return None

        cleaned = self._clean_markdown(raw)
        self._cache[skill_name] = cleaned
        return cleaned

    def load_bundle(self, skill_names: list[str], max_tokens: int = 2000) -> SkillBundle:
        if max_tokens <= 0:
            return SkillBundle(
                content="",
                token_estimate=0,
                sha256_hash="",
                loaded_skills=[],
            )

        unique_names = list(dict.fromkeys(skill_names))
        raw_skills: list[tuple[str, str]] = []

        for name in unique_names:
            text = self._load_skill_text(name)
            if text is not None and text.strip():
                raw_skills.append((name, text))

        if not raw_skills:
            return SkillBundle(
                content="",
                token_estimate=0,
                sha256_hash="",
                loaded_skills=[],
            )

        # ponytail: token ceiling uses ~4 chars/token heuristic; upgrade to tiktoken when precise provider token boundaries needed.
        char_budget = max(0, max_tokens * 4)
        sep = "\n\n"
        sep_total = max(0, len(raw_skills) - 1) * len(sep)
        avail = max(0, char_budget - sep_total)

        skill_entries = [
            (name, f"# Skill: {name}\n\n{text}", f"# Skill: {name}\n\n") for name, text in raw_skills
        ]

        n = len(skill_entries)
        indices = sorted(range(n), key=lambda i: len(skill_entries[i][1]))
        allocations = [0] * n
        remaining = avail
        rem_count = n

        for idx in indices:
            share = remaining // rem_count
            text_len = len(skill_entries[idx][1])
            alloc = min(text_len, share)
            allocations[idx] = alloc
            remaining -= alloc
            rem_count -= 1

        parts: list[tuple[str, str]] = []
        loaded_skills: list[str] = []
        for idx, (name, full_text, header) in enumerate(skill_entries):
            alloc = allocations[idx]
            if alloc <= len(header):
                continue
            if len(full_text) <= alloc:
                parts.append((name, full_text))
                loaded_skills.append(name)
            else:
                cut = full_text[:alloc]
                nl = cut.rfind("\n")
                if nl > alloc // 2 and nl > len(header):
                    cut = cut[:nl]
                cut = cut.rstrip()
                if len(cut) > len(header.rstrip()) and cut[len(header) :].strip():
                    parts.append((name, cut))
                    loaded_skills.append(name)

        if not parts:
            return SkillBundle(
                content="",
                token_estimate=0,
                sha256_hash="",
                loaded_skills=[],
            )

        content = sep.join(text for _name, text in parts).strip()
        token_estimate = (len(content) + 3) // 4 if content else 0
        sha256_hash = hashlib.sha256(content.encode("utf-8")).hexdigest() if content else ""
        # Per-skill digests of the sent portions, so a stale skill file is detectable from the
        # artifact alone rather than by re-reading the working tree months later.
        skill_hashes = {
            name: hashlib.sha256(text.encode("utf-8")).hexdigest() for name, text in parts
        }

        return SkillBundle(
            content=content,
            token_estimate=token_estimate,
            sha256_hash=sha256_hash,
            loaded_skills=loaded_skills,
            skill_hashes=skill_hashes,
        )
