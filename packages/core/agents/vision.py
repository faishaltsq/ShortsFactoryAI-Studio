"""The visual pass: one contact sheet, one declared-vision provider, one honest verdict.

This module is the only place that both reads frames and talks to a provider, which is why it sits
in ``agents`` (``agents`` may import ``providers`` and ``contracts``; it may not import
``media``). The frames arrive as :class:`VisionImage` values built by the caller, so this file
never touches ffmpeg and stays testable without a video.

The three rules, and what each one prevents:

1. **No provider → ``skipped_no_vision_provider``.** Not ``passed``. The skip is visible to the
   operator and does not block approval (STATE_MACHINE invariant 3), but it never claims sight.
2. **The answer must account for the frames that were sent.** A provider that returns
   ``{"status": "passed", "frames_inspected": 0}`` — the mock's canned reply — is rejected,
   because it is a claim about frames nobody looked at.
3. **One repair, then fail.** A malformed answer gets the same bounded repair every other agent
   gets; a second malformed answer is a ``failed`` visual pass, not a retry loop.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ..contracts.artifacts import QaArtifact
from ..contracts.base import validate_artifact
from ..providers.base import (
    Capability,
    Provider,
    ProviderError,
    ResolvedCall,
    VisionImage,
    VisionUnsupported,
)
from ..security.redact import redact

#: A finding at this severity blocks approval. ``minor`` is recorded and does not.
BLOCKING_SEVERITIES = frozenset({"blocker", "major"})
SEVERITIES = frozenset({"blocker", "major", "minor"})

SYSTEM_PROMPT = """\
You are the visual inspector for a vertical short video. You receive ONE contact sheet: a grid of
stills taken from the finished render, in reading order.

Rules:
- Report only what you can see in the sheet. Do not guess at anything outside it.
- Every finding must name the tile it came from (atMs is the still's timestamp) and the visible
  consequence: a missing character, text clipped by the frame, a black or blank tile, two scenes
  that are visually identical.
- If a tile is unreadable, say so as a finding rather than assuming it is fine.
- frames_inspected must equal the number of tiles in the sheet. You will be told that number; an
  answer that reports a different count is discarded.
- Aesthetics are not findings. This pass exists to catch what is broken, not what is plain.

Return ONLY JSON:
{"status": "passed" | "failed", "frames_inspected": <int>, "findings": [
  {"atMs": <int>, "issue": "<what is visibly wrong>", "severity": "blocker" | "major" | "minor"}
]}
"""


@dataclass
class VisualResult:
    """What the visual pass decided, in the shape ``QaArtifact.visual`` expects."""

    status: str
    provider: str | None
    frames_extracted: int
    frames_inspected: int
    findings: list[dict[str, Any]] = field(default_factory=list)
    model: str = ""
    reason: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "provider": self.provider,
            "frames_extracted": self.frames_extracted,
            "frames_inspected": self.frames_inspected,
            "findings": self.findings,
            "model": self.model,
            "reason": self.reason,
        }


def skip_no_provider(*, frames_extracted: int) -> VisualResult:
    """The honest skip. Visible, non-passing, and it never names a provider it did not use."""
    return VisualResult(
        status="skipped_no_vision_provider",
        provider=None,
        frames_extracted=frames_extracted,
        frames_inspected=0,
        findings=[],
        reason=(
            "no configured provider declares the vision capability; frames were extracted and "
            "kept for operator review"
        ),
    )


def _failed(
    *, frames_extracted: int, frames_inspected: int, reason: str, provider: str | None
) -> VisualResult:
    return VisualResult(
        status="failed",
        provider=provider,
        frames_extracted=frames_extracted,
        frames_inspected=frames_inspected,
        findings=[{"atMs": 0, "issue": reason, "severity": "blocker"}],
        reason=reason,
    )


def _parse(text: str, *, expected: int) -> tuple[dict[str, Any] | None, str]:
    """Parse and check one answer. Returns ``(payload, problem)``; ``problem`` is empty on success."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return None, "response was not a JSON object"
        try:
            payload = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None, "response was not a JSON object"
    if not isinstance(payload, dict):
        return None, "response was not a JSON object"

    status = payload.get("status")
    if status not in {"passed", "failed"}:
        return None, f"status must be passed or failed, got {status!r}"

    inspected = payload.get("frames_inspected")
    if not isinstance(inspected, int) or isinstance(inspected, bool):
        return None, "frames_inspected must be an integer"
    if status == "passed" and inspected != expected:
        return None, (
            f"frames_inspected {inspected} does not match the {expected} frames sent; "
            "a verdict about a different sheet is not a verdict about this one"
        )

    findings = payload.get("findings")
    if findings is None:
        findings = []
    if not isinstance(findings, list):
        return None, "findings must be a list"
    for index, finding in enumerate(findings):
        if not isinstance(finding, dict):
            return None, f"findings[{index}] must be an object"
        if finding.get("severity") not in SEVERITIES:
            return None, f"findings[{index}].severity must be one of {sorted(SEVERITIES)}"
        if not isinstance(finding.get("issue"), str) or not finding["issue"].strip():
            return None, f"findings[{index}].issue must be a non-empty string"

    payload["findings"] = findings
    payload["frames_inspected"] = inspected
    return payload, ""


def inspect_frames(
    *,
    call: ResolvedCall,
    provider: Provider,
    images: list[VisionImage],
    storyboard: dict[str, Any],
) -> VisualResult:
    """Ask one vision provider about one contact sheet.

    ``images`` is a list so a future pass can send two sheets; this pass always sends one, and the
    frame count is derived from the storyboard's keyframe plan, not from the caller's list length.
    """
    frames_extracted = _frame_count(storyboard)
    provider_name = call.provider or getattr(provider, "name", "")

    if Capability.VISION not in call.capabilities:
        # A binding that reached here without the capability is a programming error, not a skip:
        # the resolver is supposed to have caught it. Raise rather than pretend.
        raise VisionUnsupported(f"{provider_name} (vision not declared)")
    if not images:
        return _failed(
            frames_extracted=frames_extracted,
            frames_inspected=0,
            reason="no contact sheet was produced, so nothing could be inspected",
            provider=provider_name,
        )

    user = _user_prompt(storyboard=storyboard, frames=frames_extracted, sheets=len(images))
    try:
        first = provider.complete_vision(
            call, system=SYSTEM_PROMPT, user=user, task="vision", images=images
        )
    except ProviderError as exc:
        return _failed(
            frames_extracted=frames_extracted,
            frames_inspected=0,
            reason=redact(f"{exc.code}: {exc.detail}", limit=300),
            provider=provider_name,
        )

    payload, problem = _parse(first.content, expected=frames_extracted)
    if problem:
        repair = (
            f"{user}\n\nYour previous answer was rejected: {problem}\n"
            f'Return ONLY JSON with status, frames_inspected (must be {frames_extracted}), and '
            "findings."
        )
        try:
            second = provider.complete_vision(
                call, system=SYSTEM_PROMPT, user=repair, task="vision:repair", images=images
            )
        except ProviderError as exc:
            return _failed(
                frames_extracted=frames_extracted,
                frames_inspected=0,
                reason=redact(f"repair call failed: {exc.code}: {exc.detail}", limit=300),
                provider=provider_name,
            )
        payload, problem = _parse(second.content, expected=frames_extracted)
        if problem:
            return _failed(
                frames_extracted=frames_extracted,
                frames_inspected=0,
                reason=f"schema_violation: {problem}",
                provider=provider_name,
            )
        model = second.model
    else:
        model = first.model
    if payload is None:  # unreachable: both parse failures above return _failed
        return _failed(
            frames_extracted=frames_extracted,
            frames_inspected=0,
            reason="schema_violation: no usable verdict",
            provider=provider_name,
        )

    findings = [
        {
            "atMs": int(finding.get("atMs") or 0),
            "issue": str(finding["issue"])[:400],
            "severity": str(finding["severity"]),
        }
        for finding in payload["findings"]
    ]
    blocking = [item for item in findings if item["severity"] in BLOCKING_SEVERITIES]
    status = "failed" if payload["status"] == "failed" or blocking else "passed"
    reason = (
        "blocking findings: " + ", ".join(sorted({str(item["severity"]) for item in blocking}))
        if blocking
        else ("the provider reported a failure" if status == "failed" else "no blocking findings")
    )
    result = VisualResult(
        status=status,
        provider=provider_name,
        frames_extracted=frames_extracted,
        frames_inspected=int(payload["frames_inspected"]),
        findings=findings,
        model=model,
        reason=reason,
    )
    # The contract is the last word: a pass with zero inspected frames, or a skip that names a
    # provider, must be impossible to construct rather than merely discouraged. QaArtifact already
    # enforces the visual block, so it is used here as the validator rather than duplicating it.
    validate_artifact(
        QaArtifact,
        {
            "technical": {"passed": True, "failed": []},
            "creative": {"passed": True, "metrics": {"frames": frames_extracted}, "failed": []},
            "visual": {
                "status": result.status,
                "provider": result.provider,
                "frames_extracted": result.frames_extracted,
                "frames_inspected": result.frames_inspected,
                "findings": result.findings,
            },
            "repairs": [],
        },
    )
    return result


#: Must match ``media.qc.MAX_KEYFRAMES`` and ``media.qc.BOUNDARY_OFFSET_S``. Duplicated because
#: ``agents`` may not import ``media`` (ARCHITECTURE §3), and the alternative — passing the count
#: in from the caller — would let a caller assert a number the sheet does not have.
KEYFRAME_LIMIT = 6
BOUNDARY_OFFSET_S = 0.5


def _keyframe_frames(storyboard: dict[str, Any]) -> list[int]:
    """The frames the contact sheet will hold: scene midpoints plus one still after each cut."""
    body = storyboard.get("storyboard") if isinstance(storyboard, dict) else None
    if not isinstance(body, dict):
        body = storyboard if isinstance(storyboard, dict) else {}
    scenes = body.get("scenes")
    if not isinstance(scenes, list):
        return []
    raw_fps = body.get("fps")
    fps = raw_fps if isinstance(raw_fps, (int, float)) and not isinstance(raw_fps, bool) and raw_fps else 30
    offset = round(BOUNDARY_OFFSET_S * float(fps))
    frames: set[int] = set()
    for index, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue
        start = scene.get("startFrame")
        duration = scene.get("durationInFrames")
        if not isinstance(start, int) or not isinstance(duration, int) or duration <= 0:
            continue
        frames.add(start + duration // 2)
        if index + 1 < len(scenes):
            following = scenes[index + 1]
            next_start = following.get("startFrame") if isinstance(following, dict) else None
            next_duration = following.get("durationInFrames") if isinstance(following, dict) else None
            if isinstance(next_start, int) and isinstance(next_duration, int):
                frames.add(min(start + duration + offset, next_start + max(0, next_duration - 1)))
    return sorted(frames)[:KEYFRAME_LIMIT]


def _frame_count(storyboard: dict[str, Any]) -> int:
    return len(_keyframe_frames(storyboard))


def _user_prompt(*, storyboard: dict[str, Any], frames: int, sheets: int) -> str:
    body = storyboard.get("storyboard") if isinstance(storyboard, dict) else None
    if not isinstance(body, dict):
        body = storyboard if isinstance(storyboard, dict) else {}
    raw_scenes = body.get("scenes")
    scenes = raw_scenes if isinstance(raw_scenes, list) else []
    summary = [
        {
            "sceneId": scene.get("sceneId"),
            "template": scene.get("template"),
            "seconds": round(
                (scene.get("durationInFrames") or 0) / max(1, body.get("fps") or 30), 2
            ),
            "text": [element.get("text") for element in (scene.get("text") or []) if isinstance(element, dict)],
        }
        for scene in scenes
        if isinstance(scene, dict)
    ]
    return (
        f"The contact sheet contains {frames} stills from {len(scenes)} scenes "
        f"({sheets} image attached).\n"
        f"frames_inspected must be exactly {frames}.\n"
        "Storyboard, for cross-checking what should be on screen:\n"
        + json.dumps(summary, ensure_ascii=False)[:4000]
    )


__all__ = ["BLOCKING_SEVERITIES", "SYSTEM_PROMPT", "VisualResult", "inspect_frames", "skip_no_provider"]
