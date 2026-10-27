"""The readiness binding hash must not depend on the clock.

``compute_inputs_hash`` canonicalises the storyboard through its contract so a raw dict and a
validated model agree. It also picked up ``created_at``, which ``Artifact`` fills with the current
whole second — so the same job hashed differently a second later. Measured before the fix: 40
identical calls produced 3 distinct hashes.

That is worse than flaky. A verdict recorded at 12:00:00 and recomputed at 12:00:01 disagreed, so
the gate could refuse a correct job; and the reverse is true of a stale verdict that happens to be
recomputed within the same second, which is a false pass. ``Artifact.canonical_json`` already
documents the rule: ``created_at`` must not affect a hash.
"""

from __future__ import annotations

import time

from packages.core.contracts.artifacts import StoryboardArtifact
from packages.core.orchestration.editorial import compute_inputs_hash


def _storyboard(**overrides) -> dict:
    payload = {
        "schema_version": 1,
        "fps": 30,
        "width": 1080,
        "height": 1920,
        "theme": "dusk",
        "scenes": [
            {
                "sceneId": "sc1",
                "template": "IllustratedStory",
                "segment": "s1",
                "startFrame": 0,
                "durationInFrames": 90,
                "assetRefs": [],
                "text": [{"id": "t1", "text": "Halo", "role": "title", "atFrame": 0}],
                "camera": {"shot": "wide", "move": "static"},
                "motion": {"energy": 0.5, "continuity": "cut", "beats": []},
                "transition": {"kind": "cut", "frames": 0},
                "data": {
                    "setting": "desert",
                    "timeOfDay": "dusk",
                    "actors": [],
                    "props": [],
                    "fx": [],
                    "shots": [{"framing": "wide", "camera": "pushIn", "weight": 1}],
                },
            }
        ],
        "subtitles": [],
    }
    payload.update(overrides)
    return payload


def _hash(storyboard: dict, *, render: str = "a" * 64, narration: float = 1000) -> str:
    return compute_inputs_hash(
        render_sha256=render, narration_ms=narration, storyboard=storyboard
    )


def test_the_hash_is_stable_across_a_simulated_clock_second(monkeypatch):
    """The defect: ``created_at`` is stamped at call time, so the hash moved with the clock."""
    import packages.core.contracts.base as base

    monkeypatch.setattr(base, "_utc_now", lambda: "2026-01-01T00:00:00+00:00")
    first = _hash(_storyboard())

    monkeypatch.setattr(base, "_utc_now", lambda: "2026-01-01T00:00:01+00:00")
    second = _hash(_storyboard())

    assert first == second


def test_the_hash_is_stable_across_real_time():
    """No monkeypatch: the real clock must not be able to change it either."""
    hashes = {_hash(_storyboard()) for _ in range(5) if not time.sleep(1.05)}
    assert len(hashes) == 1, "sleeping across a second boundary changed the hash"


def test_a_storyboard_with_a_created_at_hashes_the_same_as_one_without():
    """The stored artifact carries ``created_at``; the hash must ignore it."""
    with_stamp = _storyboard()
    with_stamp["created_at"] = "2020-05-05T05:05:05+00:00"
    assert _hash(with_stamp) == _hash(_storyboard())


def test_two_different_created_at_values_hash_the_same():
    first = _storyboard()
    first["created_at"] = "2020-01-01T00:00:00+00:00"
    second = _storyboard()
    second["created_at"] = "2026-12-31T23:59:59+00:00"
    assert _hash(first) == _hash(second)


def test_a_real_content_change_still_changes_the_hash():
    changed = _storyboard()
    changed["scenes"][0]["text"][0]["text"] = "Berbeda"
    assert _hash(changed) != _hash(_storyboard())


def test_a_render_change_changes_the_hash():
    assert _hash(_storyboard(), render="b" * 64) != _hash(_storyboard())


def test_a_narration_change_changes_the_hash():
    assert _hash(_storyboard(), narration=2000) != _hash(_storyboard())


def test_the_hash_matches_the_contracts_own_canonicalisation():
    """One rule, not two: the storyboard's contribution is its ``content_hash``."""
    storyboard = _storyboard()
    model = StoryboardArtifact.model_validate(storyboard)
    from packages.core.contracts.base import content_hash as contract_hash

    expected = contract_hash(
        {
            "render_sha256": "a" * 64,
            "narration_ms": 1000.0,
            "storyboard": model.content_hash(),
        }
    )
    assert _hash(storyboard) == expected


def test_an_invalid_storyboard_still_hashes_without_raising():
    assert len(_hash({"scenes": "not a list"})) == 64
