from __future__ import annotations

import hashlib
from pathlib import Path

from packages.core.agents.skill_loader import MotionSkillLoader, SkillBundle


def test_skill_loader_discovers_remotion_skills() -> None:
    loader = MotionSkillLoader(skills_dir=Path(".agents/skills"))
    available = loader.list_available_skills()
    assert "remotion-best-practices" in available
    assert "remotion-markup" in available
    assert "remotion-render" in available


def test_skill_loader_bundles_prompt_context() -> None:
    loader = MotionSkillLoader(skills_dir=Path(".agents/skills"))
    bundle = loader.load_bundle(["remotion-best-practices", "remotion-markup"], max_tokens=1500)
    assert isinstance(bundle, SkillBundle)
    assert bundle.sha256_hash != ""
    assert len(bundle.sha256_hash) == 64
    assert len(bundle.loaded_skills) == 2
    assert "remotion" in bundle.content.lower()
    assert bundle.token_estimate <= 1600


def test_skill_loader_default_constructor() -> None:
    loader = MotionSkillLoader()
    available = loader.list_available_skills()
    assert "remotion-best-practices" in available


def test_skill_loader_handles_missing_skill_gracefully() -> None:
    loader = MotionSkillLoader(skills_dir=Path(".agents/skills"))
    bundle = loader.load_bundle(["non-existent-skill-xyz", "bad\0name"])
    assert bundle.loaded_skills == []
    assert bundle.content == ""


def test_skill_loader_rejects_path_traversal(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("SUPER_SECRET_TOKEN", encoding="utf-8")

    valid_skill = skills_dir / "remotion-valid"
    valid_skill.mkdir()
    (valid_skill / "SKILL.md").write_text("# Valid Skill\nBody content", encoding="utf-8")

    loader = MotionSkillLoader(skills_dir=skills_dir)

    traversal_attempts = [
        "../../secret.txt",
        "../something",
        "..\\windows\\system32",
        "..",
        ".",
        "nested/path",
        "/etc/passwd",
        "\\etc\\passwd",
    ]

    for attempt in traversal_attempts:
        assert loader._resolve_skill_dir(attempt) is None
        bundle = loader.load_bundle([attempt])
        assert bundle.content == ""
        assert bundle.loaded_skills == []
        assert bundle.token_estimate == 0
        assert bundle.sha256_hash == ""

    # Ensure traversal attempt mixed with valid skill does not leak or traverse
    mixed_bundle = loader.load_bundle(["../../secret.txt", "valid"])
    assert mixed_bundle.loaded_skills == ["valid"]
    assert "SUPER_SECRET_TOKEN" not in mixed_bundle.content
    assert "Valid Skill" in mixed_bundle.content


def test_skill_loader_cleans_markdown(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / "remotion-clean"
    skill_dir.mkdir(parents=True)

    raw_markdown = (
        "\ufeff---\n"
        "title: Frontmatter Title\n"
        "author: Test Author\n"
        "---\n\n\n\n"
        "![Alt image text](https://example.com/image.png)\n\n"
        '<img src="https://example.com/banner.jpg" alt="banner">\n\n\n\n\n'
        "# Main Heading\n\n\n\n\n"
        "Body paragraph with information.\n\n\n\n"
    )
    (skill_dir / "SKILL.md").write_text(raw_markdown, encoding="utf-8")

    loader = MotionSkillLoader(skills_dir=skills_dir)
    bundle = loader.load_bundle(["clean"])

    assert bundle.loaded_skills == ["clean"]
    assert "\ufeff" not in bundle.content
    assert "Frontmatter Title" not in bundle.content
    assert "Test Author" not in bundle.content
    assert "---" not in bundle.content
    assert "![Alt image text]" not in bundle.content
    assert "<img" not in bundle.content
    assert "\n\n\n" not in bundle.content
    assert "# Main Heading" in bundle.content
    assert "Body paragraph with information." in bundle.content


def test_skill_loader_truncation_tiny_budget_and_multiple_skills(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    skill_a = skills_dir / "remotion-alpha"
    skill_a.mkdir(parents=True)
    (skill_a / "SKILL.md").write_text("Alpha line 1\nAlpha line 2\nAlpha line 3", encoding="utf-8")

    skill_b = skills_dir / "remotion-beta"
    skill_b.mkdir(parents=True)
    (skill_b / "SKILL.md").write_text("Beta line 1\nBeta line 2\nBeta line 3", encoding="utf-8")

    loader = MotionSkillLoader(skills_dir=skills_dir)

    # Tiny budget where header + content cannot fit: no orphaned header fragment
    tiny_bundle = loader.load_bundle(["alpha", "beta"], max_tokens=3)
    assert tiny_bundle.content == ""
    assert tiny_bundle.loaded_skills == []
    assert tiny_bundle.token_estimate == 0

    # Moderate budget where skills are truncated but content fits
    bundle = loader.load_bundle(["alpha", "beta"], max_tokens=30)
    assert len(bundle.loaded_skills) > 0
    # Every skill in loaded_skills must have actual content past its header
    for name in bundle.loaded_skills:
        header = f"# Skill: {name}"
        assert header in bundle.content
        header_idx = bundle.content.find(header)
        after_header = bundle.content[header_idx + len(header) :].strip()
        assert len(after_header) > 0


def test_skill_loader_max_tokens_zero_or_negative(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / "remotion-test"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("Some text", encoding="utf-8")

    loader = MotionSkillLoader(skills_dir=skills_dir)

    for non_pos in (0, -1, -50):
        bundle = loader.load_bundle(["test"], max_tokens=non_pos)
        assert bundle.content == ""
        assert bundle.token_estimate == 0
        assert bundle.sha256_hash == ""
        assert bundle.loaded_skills == []


def test_skill_loader_deduplicates_requests_and_caches_negatives(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / "remotion-single"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("Single skill content", encoding="utf-8")

    loader = MotionSkillLoader(skills_dir=skills_dir)

    # Deduplication
    bundle = loader.load_bundle(["single", "single", "single"])
    assert bundle.loaded_skills == ["single"]
    assert bundle.content.count("# Skill: single") == 1

    # Negative caching
    assert loader._load_skill_text("missing") is None
    assert "missing" in loader._cache
    assert loader._cache["missing"] is None


def test_skill_loader_handles_os_errors(tmp_path: Path, monkeypatch) -> None:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    loader = MotionSkillLoader(skills_dir=skills_dir)

    def raise_oserror(*args, **kwargs):
        raise OSError("Simulated disk error")

    monkeypatch.setattr(Path, "iterdir", raise_oserror)
    assert loader.list_available_skills() == []

    monkeypatch.setattr(Path, "read_text", raise_oserror)
    assert loader._load_skill_text("anything") is None


# -- relevance selection ------------------------------------------------------------------------


def test_ranking_picks_the_skill_the_shot_needs() -> None:
    """The selection is per shot: a caption-heavy film and a map-heavy film must not get the same
    reference block, which is what one fixed "load some skills" call produced."""
    loader = MotionSkillLoader()
    captions = loader.rank(["kinetic typography captions subtitle reveal"], limit=3)
    maps = loader.rank(["geographic map route travel"], limit=3)
    assert "remotion-captions" in captions
    assert "remotion-maps" in maps
    assert captions != maps


def test_ranking_is_deterministic() -> None:
    """Two identical runs must select identically, or the recorded provenance describes a run
    nobody can reproduce."""
    loader = MotionSkillLoader()
    request = ["animated svg path diagram geometry morph", "tracking camera mask"]
    assert loader.rank(request, limit=4) == loader.rank(request, limit=4)


def test_ranking_respects_its_limit_and_still_returns_something_when_nothing_matches() -> None:
    loader = MotionSkillLoader()
    assert len(loader.rank("zoom", limit=2)) == 2
    assert len(loader.rank("zzzzqqqq", limit=3)) == 3, "an unrankable request still gets a block"
    assert loader.rank("anything", limit=0) == []


def test_summaries_read_the_declared_description() -> None:
    loader = MotionSkillLoader()
    by_name = {summary.name: summary.description for summary in loader.summaries()}
    assert by_name.get("remotion-captions")
    assert "caption" in by_name["remotion-captions"].lower()


def test_the_bundle_records_the_digest_of_what_was_actually_sent(tmp_path: Path) -> None:
    """A skill truncated to fit the budget is recorded as the truncated version: the provenance
    says what the model read, not what happened to be available on disk."""
    skills_dir = tmp_path / "skills"
    skill = skills_dir / "long-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: long-skill\ndescription: x\n---\n" + "A" * 5000,
                                    encoding="utf-8")

    loader = MotionSkillLoader(skills_dir=skills_dir)
    bundle = loader.load_bundle(["long-skill"], max_tokens=200)
    assert bundle.loaded_skills == ["long-skill"]
    sent = bundle.skill_hashes["long-skill"]
    full = loader.load_bundle(["long-skill"], max_tokens=10_000)
    assert sent != full.skill_hashes["long-skill"], "a truncation must change the recorded digest"
    assert sent == hashlib.sha256(bundle.content.encode("utf-8")).hexdigest()
