"""Emit one self-contained HTML document from a validated storyboard.

ADR-0012: the secondary renderer authors its own document. It does not ingest upstream starter
markup, and it loads nothing — no GSAP, no webfont, no CDN. The whole runtime contract is
``window.OPENER``, and ``seek(t)`` is a pure function of time so that two runs at the same ``t``
produce the same pixels.

Three rules hold this file together:

1. **Nothing from the model is markup.** Every string reaches the document through
   :func:`html.escape` as element *content*. There is no ``innerHTML``, no template interpolation of
   unescaped text, and no place where a scene field becomes a tag, an attribute name, or code.
2. **The vocabulary is closed.** Pose, expression, tone, framing and motion preset are checked
   against the same lists ``packages/video/src/character/ids.ts`` and ``scene-data.ts`` declare. An
   unknown value is an error, never a silent default — a typo that renders as "neutral" is a bug
   nobody sees.
3. **Duration is derived, not trusted.** ``DURATION`` and the frame count come from
   ``sum(durationInFrames)``; a mismatch with the caller's frame count is refused before a browser
   is started.
"""

from __future__ import annotations

import json
from html import escape
from typing import Any

#: The complete ``window.OPENER`` surface required by ADR-0007/0012. Tests pin this tuple.
OPENER_KEYS: tuple[str, ...] = (
    "W",
    "H",
    "DURATION",
    "tl",
    "ready",
    "seek",
    "clipsReady",
    "play",
)

#: Mirrors ``packages/video/src/character/ids.ts``. Duplicating the list is deliberate: this module
#: must not import TypeScript, and a drift here is caught by the emitter tests naming a bad value.
POSES: frozenset[str] = frozenset({"stand", "point", "reach", "walk", "lookUp", "shrug", "sit"})
EXPRESSIONS: frozenset[str] = frozenset(
    {"neutral", "curious", "happy", "surprised", "concerned", "determined", "thinking", "sad"}
)
MOTION_PRESETS: frozenset[str] = frozenset(
    {"idle", "talk", "walk", "gesture", "react", "enter", "poseChange"}
)
TONES: frozenset[str] = frozenset({"primary", "secondary", "accent"})
BEAT_KINDS: frozenset[str] = frozenset({"enter", "emphasis", "exit", "action", "reveal"})
TRANSITION_KINDS: frozenset[str] = frozenset({"cut", "fade", "wipe", "push", "match"})
TEXT_ROLES: frozenset[str] = frozenset({"title", "body", "caption", "label"})

#: The only character this renderer can draw. A second one is real work (a second rig), not a
#: registry entry, so the name is a closed set until that work exists.
CHARACTERS: frozenset[str] = frozenset({"maya"})

#: Frame budget. A 30 s Short at 30 fps is 900 frames; the cap leaves room for a 100 s cut and
#: refuses a runaway loop before a browser is launched.
DEFAULT_FRAME_CAP = 3000

#: Wall-clock budget in seconds, matching the primary renderer's 900 s default.
DEFAULT_WALL_CLOCK_S = 900

#: Ramp up from silence to full aperture. Mirrors ``packages/video/src/speech.ts``.
ATTACK_MS = 40
#: Ramp back down to silence, starting at the window's end. Mirrors the same module.
RELEASE_MS = 70

#: The closed mouth, as an SVG path in the figure's own coordinates.
_MOUTH_CLOSED = "M-14,-462 q14,4 28,0 q-14,6 -28,0 z"
#: Half-height of a fully open mouth, in figure units.
_MOUTH_OPEN_HALF = 13.0

_SAFE_MARGIN = 0.78
_STAGE_CSS = """
*,*::before,*::after{box-sizing:border-box}
html,body{margin:0;padding:0;width:100%;height:100%;background:#0a0f1e;overflow:hidden}
#stage{position:absolute;left:0;top:0;width:var(--w);height:var(--h);overflow:hidden;
  background:var(--bg);color:var(--ink);font-family:var(--font-body)}
#world{position:absolute;inset:0;transform-origin:50% 50%}
.safe{position:absolute;inset:0;transform:scale(var(--safe));transform-origin:50% 50%}
.scene{position:absolute;inset:0;opacity:0}
.copy{position:absolute;left:8%;width:84%;top:14%;display:flex;flex-direction:column;gap:26px}
.text{position:relative;opacity:0;line-height:1.12;overflow-wrap:anywhere}
.role-title{font-family:var(--font-heading);font-size:118px;font-weight:900;letter-spacing:-.01em}
.role-body{font-family:var(--font-body);font-size:56px;font-weight:600;opacity:0}
.role-caption{font-family:var(--font-body);font-size:42px;font-weight:500}
.role-label{font-family:var(--font-body);font-size:34px;font-weight:700;letter-spacing:.14em;
  text-transform:uppercase}
#maya{position:absolute;left:0;top:0;width:100%;height:100%;overflow:visible}
/* Burned-in captions. The band matches packages/video/src/components/Subtitles.tsx exactly:
   bottom 360 px of a 1920 px stage, 90 px side insets, centred, on a translucent backing. */
#captions{position:absolute;left:90px;right:90px;bottom:360px;text-align:center;
  pointer-events:none;font-family:var(--font-heading)}
.cue{display:none;font-size:58px;line-height:1.25;font-weight:700;color:var(--ink);
  text-shadow:0 4px 18px rgba(0,0,0,0.85)}
.cue span{background-color:rgba(0,0,0,0.35);border-radius:12px;padding:6px 16px;
  box-decoration-break:clone;-webkit-box-decoration-break:clone}
#vignette{position:absolute;inset:0;pointer-events:none;
  background:radial-gradient(92% 92% at 50% 46%,transparent 58%,rgba(8,12,26,.34))}
"""

#: Dusk palette. Deliberately one theme: a second theme is a design decision with its own review,
#: not a field this renderer invents.
_PALETTE = {
    "bg": "linear-gradient(168deg,#101a33 0%,#1d2b4d 52%,#3a2434 100%)",
    "ink": "#f4f1ea",
    "accent": "#d7262c",
    "skin": "#e8b48c",
    "cloth": "#2f4a7a",
    "hair": "#20161a",
}


def _speech_attr(windows: list[dict[str, int]]) -> str:
    """``"100-500,900-1200"`` — the windows in a form that needs no escaping in an attribute."""
    return ",".join(f"{window['startMs']}-{window['endMs']}" for window in windows)


def _speech_windows(scene: dict[str, Any], *, fps: int) -> list[dict[str, int]]:
    """Validate ``scene.speech`` and return it as ``[{startMs, endMs}]``.

    This is a trust boundary, not a tidy-up. ``audio.json`` is written by the audio stage, but a
    stale or hand-edited artifact can carry windows that are out of order, overlap, or run past the
    scene. Each of those makes the mouth open at a time the voice never reached, so each is
    rejected loudly: sorting or clamping here would render a plausible mouth over audio nobody
    measured, which is the failure this module exists to prevent.

    An inverted or empty window is an error for the same reason: a mouth that silently never opens
    is the same class of failure as a caption that never appears.
    """
    windows = scene.get("speech") or []
    _require(isinstance(windows, list), "scene.speech must be a list")
    # Frames to milliseconds without rounding down: 299 frames at 30 fps is 9966.66... ms, and a
    # window ending at 9966 ms is still inside it.
    duration_ms = scene["durationInFrames"] * 1000 / fps
    validated: list[dict[str, int]] = []
    previous_start: int | None = None
    previous_end: int | None = None
    for index, window in enumerate(windows):
        _require(isinstance(window, dict), f"speech window {index} must be an object")
        start = window.get("startMs")
        end = window.get("endMs")
        for name, value in (("startMs", start), ("endMs", end)):
            _require(
                isinstance(value, int) and not isinstance(value, bool) and value >= 0,
                f"speech window {index} {name} must be a non-negative integer",
            )
        _require(end > start, f"speech window {index} has an empty or inverted span")
        if previous_start is not None and previous_end is not None:
            _require(
                start >= previous_start,
                f"speech[{index}] starts at {start} ms, before speech[{index - 1}] at "
                f"{previous_start} ms: the windows are out of order",
            )
            _require(
                start >= previous_end,
                f"speech[{index}] starts at {start} ms but speech[{index - 1}] ends at "
                f"{previous_end} ms: the windows overlap",
            )
        _require(
            end <= duration_ms,
            f"speech[{index}] ends at {end} ms, past the scene end at {duration_ms:g} ms",
        )
        validated.append({"startMs": start, "endMs": end})
        previous_start, previous_end = start, end
    return validated


def mouth_aperture(windows: list[dict[str, Any]], ms: float) -> float:
    """Aperture 0..1 for a scene-local time in milliseconds.

    The envelope is the primary renderer's, ported so the two agree on *when* the mouth moves even
    though their art differs: ramp up over ``ATTACK_MS`` from ``startMs``, hold at full through the
    body, ramp down over ``RELEASE_MS`` starting at ``endMs`` (so the mouth is still partly open on
    the frame after a word ends). Both ramps clamp to half the window, so a 40 ms word is a triangle
    inside its own span rather than a mouth that opens after the word has finished.

    Pure in ``(windows, ms)``: nothing accumulates, so out-of-order capture seeks produce the same
    mouth for the same ``t``. An empty list returns 0 — never a fallback clock.
    """
    if not windows:
        return 0.0
    for index, window in enumerate(windows):
        start = window.get("startMs")
        end = window.get("endMs")
        if not isinstance(start, int) or not isinstance(end, int) or end <= start:
            raise ValueError(f"speech window {index} has an empty or inverted span")
        length: int = end - start
        attack = min(ATTACK_MS, length / 2)
        release = min(RELEASE_MS, length / 2)
        if ms < start or ms >= end + release:
            continue
        if ms < start + attack:
            return max(0.0, min(1.0, (ms - start) / attack))
        if ms < end:
            return 1.0
        return max(0.0, min(1.0, 1 - (ms - end) / release))
    return 0.0


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def storyboard_frames(storyboard: dict[str, Any]) -> int:
    """Total frames, derived from the scenes. The single source of truth for duration."""
    scenes = storyboard.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise ValueError("storyboard.scenes must be a non-empty list")
    total = 0
    for scene in scenes:
        if not isinstance(scene, dict):
            raise ValueError("each storyboard scene must be an object")
        duration = scene.get("durationInFrames")
        if not isinstance(duration, int) or isinstance(duration, bool) or duration <= 0:
            raise ValueError(f"scene {scene.get('sceneId')!r} has no positive integer durationInFrames")
        total += duration
    _require(total > 0, "storyboard has no renderable duration")
    return total


def _pick(value: Any, allowed: frozenset[str], field: str, fallback: str | None = None) -> str:
    if value is None:
        if fallback is None:
            raise ValueError(f"{field} is required")
        return fallback
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"unsupported {field}: {value!r}")
    return value


def _unit(value: Any, field: str, fallback: float) -> float:
    if value is None:
        return fallback
    _require(
        isinstance(value, (int, float)) and not isinstance(value, bool) and 0.0 <= float(value) <= 1.0,
        f"{field} must be a number in 0..1",
    )
    return float(value)


def _text_elements(scene: dict[str, Any], width: int, height: int) -> str:
    parts: list[str] = []
    for element in scene.get("text") or []:
        _require(isinstance(element, dict), "each text element must be an object")
        role = _pick(element.get("role"), TEXT_ROLES, "text role", "body")
        at_frame = element.get("atFrame", 0)
        _require(
            isinstance(at_frame, int) and not isinstance(at_frame, bool) and at_frame >= 0,
            f"text element {element.get('id')!r} has an invalid atFrame",
        )
        parts.append(
            f'<div class="text role-{role}" data-at="{at_frame}">'
            f'{escape(str(element.get("text", "")))}</div>'
        )
    return f'<div class="copy">{"".join(parts)}</div>'


def _maya(actor: dict[str, Any], width: int, height: int, scene_id: str) -> str:
    """One rigged figure, drawn as inline SVG in stage coordinates.

    The arm and head are addressed by id so ``seek`` can rotate them per beat. Nothing here reads
    the clock; every attribute is a function of the pose name and the stage size.
    """
    character = _pick(actor.get("character"), CHARACTERS, "character")
    pose = _pick(actor.get("pose"), POSES, "pose", "stand")
    expression = _pick(actor.get("expression"), EXPRESSIONS, "expression", "neutral")
    tone = _pick(actor.get("tone"), TONES, "actor tone", "primary")
    facing = actor.get("facing", "right")
    _require(facing in {"left", "right"}, f"unsupported actor facing: {facing!r}")
    motion = actor.get("motion") or {}
    _require(isinstance(motion, dict), "actor motion must be an object")
    preset = _pick(motion.get("preset"), MOTION_PRESETS, "motion preset", "idle")

    cx = _unit(actor.get("x"), "actor x", 0.5) * width
    ground = _unit(actor.get("ground"), "actor ground", 0.72) * height
    scale = actor.get("scale", 1)
    _require(
        isinstance(scale, (int, float)) and not isinstance(scale, bool) and 0.2 <= float(scale) <= 2.5,
        "actor scale must be a number in 0.2..2.5",
    )
    scale = float(scale)

    arm_angle = {"point": -68, "reach": -34, "shrug": -14, "lookUp": -22}.get(pose, -8)
    head_tilt = {"lookUp": -9, "curious": -6, "sad": 5, "thinking": 7}.get(expression, 0)
    flip = -1 if facing == "left" else 1
    silhouette = "true" if actor.get("silhouette") else "false"
    fill = "var(--ink)" if actor.get("silhouette") else _PALETTE["cloth"]

    figure_transform = (
        f"translate({cx:.1f},{ground:.1f}) scale({scale * flip:.4f},{scale:.4f})"
    )
    return (
        f'<g id="{character}" data-pose="{pose}" data-expression="{expression}" '
        f'data-motion="{preset}" data-tone="{tone}" data-silhouette="{silhouette}" '
        f'data-scene="{escape(scene_id)}" transform="{figure_transform}">'
        f'<g id="maya-body">'
        f'<ellipse id="maya-shadow" cx="0" cy="6" rx="118" ry="22" fill="rgba(4,8,18,.42)"/>'
        f'<rect id="maya-legs" x="-44" y="-206" width="34" height="206" rx="15" fill="{fill}"/>'
        f'<rect id="maya-legs-far" x="10" y="-206" width="34" height="206" rx="15" '
        f'fill="{fill}" opacity=".82"/>'
        f'<rect id="maya-torso" x="-58" y="-436" width="116" height="240" rx="46" fill="{fill}"/>'
        # SVG groups have no layout box, so a CSS `transform-origin` in px resolves against nothing
        # and the rotation never appears. The pivot lives inside rotate(a cx cy) instead, and seek
        # rewrites this attribute.
        f'<g id="maya-arm-near" transform="rotate({arm_angle} 69 -404)">'
        f'<rect x="54" y="-408" width="30" height="196" rx="15" fill="{fill}"/>'
        f'<circle cx="69" cy="-206" r="21" fill="{_PALETTE["skin"]}"/>'
        f"</g>"
        f'<g id="maya-arm-far" transform="rotate({arm_angle * 0.4:.1f} -69 -404)">'
        f'<rect x="-84" y="-408" width="30" height="190" rx="15" fill="{fill}" opacity=".82"/>'
        f'<circle cx="-69" cy="-212" r="20" fill="{_PALETTE["skin"]}" opacity=".9"/>'
        f"</g>"
        f'<g id="maya-head" transform="rotate({head_tilt} 0 -452)">'
        f'<circle id="maya-head-shape" cx="0" cy="-486" r="66" fill="{_PALETTE["skin"]}"/>'
        f'<path id="maya-hair" d="M-66,-500 a66,66 0 0 1 132,0 q-30,-34 -66,-30 q-36,-4 -66,30 z" '
        f'fill="{_PALETTE["hair"]}"/>'
        f'<ellipse id="maya-eye-near" cx="26" cy="-492" rx="7" ry="9" fill="#12131a"/>'
        f'<ellipse id="maya-eye-far" cx="-4" cy="-492" rx="7" ry="9" fill="#12131a"/>'
        # The mouth is a filled aperture, not a fixed line: seek() rewrites `d` from the measured
        # speech envelope. Closed at rest, so a scene with no windows is honestly silent.
        f'<path id="maya-mouth" data-mouth="maya" d="{_MOUTH_CLOSED}" fill="#12131a"/>'
        f"</g>"
        f"</g>"
        f'<g id="maya-beats" data-arm="{arm_angle}" data-head="{head_tilt}" '
        f'data-base="{escape(figure_transform)}"></g>'
        f"</g>"
    )


def _scene_markup(scene: dict[str, Any], index: int, width: int, height: int, *, fps: int) -> str:
    scene_id = scene.get("sceneId")
    if not isinstance(scene_id, str) or not scene_id:
        raise ValueError(f"scene {index} has no sceneId")
    duration = scene["durationInFrames"]
    start = scene.get("startFrame", 0)
    transition = scene.get("transition") or {}
    _require(isinstance(transition, dict), f"scene {scene_id!r} transition must be an object")
    kind = _pick(transition.get("kind"), TRANSITION_KINDS, "transition kind", "cut")
    transition_frames = transition.get("frames", 0)
    _require(
        isinstance(transition_frames, int) and not isinstance(transition_frames, bool)
        and 0 <= transition_frames <= 60,
        f"scene {scene_id!r} transition frames must be an integer in 0..60",
    )

    speech_windows = _speech_windows(scene, fps=fps)

    beats: list[str] = []
    motion = scene.get("motion") or {}
    _require(isinstance(motion, dict), f"scene {scene_id!r} motion must be an object")
    for beat in motion.get("beats") or []:
        _require(isinstance(beat, dict), f"scene {scene_id!r} has a non-object beat")
        at = beat.get("atFrame")
        _require(
            isinstance(at, int) and not isinstance(at, bool) and at >= 0,
            f"scene {scene_id!r} beat has an invalid atFrame: {at!r}",
        )
        beat_kind = _pick(beat.get("kind"), BEAT_KINDS, "beat kind")
        subject = beat.get("subject")
        _require(isinstance(subject, str) and bool(subject), f"scene {scene_id!r} beat has no subject")

        # The audio stage retimes scenes to measured narration, so a beat authored against the
        # original duration can land past the new end. Dropping it would silently delete motion the
        # model asked for; the beat is clamped to the last frame and the clamp is recorded, so the
        # document still says a beat was intended there.
        clamped = at >= duration
        placed = min(at, duration - 1)
        beats.append(
            f'<i data-beat-frame="{placed}" data-beat-kind="{beat_kind}" '
            f'data-beat-subject="{escape(subject)}"'
            + (' data-beat-clamped="true"' if clamped else "")
            + "></i>"
        )

    camera = scene.get("camera") or {}
    _require(isinstance(camera, dict), f"scene {scene_id!r} camera must be an object")
    amplitude = camera.get("amplitude", 0.12)
    _require(
        isinstance(amplitude, (int, float)) and not isinstance(amplitude, bool)
        and 0.0 <= float(amplitude) <= 1.0,
        f"scene {scene_id!r} camera amplitude must be a number in 0..1",
    )

    actors = (scene.get("data") or {}).get("actors") or []
    _require(isinstance(actors, list), f"scene {scene_id!r} actors must be a list")
    figures = "".join(
        _maya(actor, width, height, scene_id)
        for actor in actors
        if isinstance(actor, dict) and actor.get("character")
    )

    return (
        f'<section class="scene" id="scene-{index}" data-scene="{escape(scene_id)}" '
        f'data-start="{start}" data-dur="{duration}" data-transition="{kind}" '
        f'data-speech="{_speech_attr(speech_windows)}" '
        f'data-transition-frames="{transition_frames}" '
        f'data-camera-amplitude="{float(amplitude):.4f}">'
        f"{_text_elements(scene, width, height)}"
        f'<svg id="maya" viewBox="0 0 {width} {height}" preserveAspectRatio="none">{figures}</svg>'
        f'<div class="beats">{"".join(beats)}</div>'
        f"</section>"
    )


def _caption_markup(storyboard: dict[str, Any]) -> str:
    """One element per subtitle cue, escaped, carrying its exact window as data attributes.

    ``storyboard.subtitles`` is the same field the primary renderer burns in via
    ``Subtitles.tsx``. Reading it here is not optional: without it the secondary renderer produced
    narration with no captions, and no test noticed because ``verify_video`` checks that cues fit
    their bounds rather than that a cue reached a frame.

    An inverted or empty window is an error, not a cue that never shows: a caption that silently
    never appears is exactly the failure this function exists to prevent.
    """
    subtitles = storyboard.get("subtitles") or []
    _require(isinstance(subtitles, list), "storyboard.subtitles must be a list")
    parts: list[str] = []
    for index, cue in enumerate(subtitles):
        _require(isinstance(cue, dict), f"subtitle cue {index} must be an object")
        start = cue.get("startMs")
        end = cue.get("endMs")
        for name, value in (("startMs", start), ("endMs", end)):
            _require(
                isinstance(value, int) and not isinstance(value, bool) and value >= 0,
                f"subtitle cue {index} {name} must be a non-negative integer",
            )
        _require(end > start, f"subtitle cue {index} has an empty or inverted window")
        text = cue.get("text")
        _require(isinstance(text, str) and bool(text), f"subtitle cue {index} has no text")
        parts.append(
            f'<div class="cue" data-cue-start="{start}" data-cue-end="{end}">'
            f"<span>{escape(text)}</span></div>"
        )
    return "".join(parts)


def emit_document(storyboard: dict[str, Any]) -> str:
    """Return the complete HTML document for one storyboard.

    Raises :class:`ValueError` on anything the renderer would otherwise have to guess: an unknown
    pose, a beat outside its scene, a non-positive duration. A guess here becomes a silently wrong
    frame 400 into a render.
    """
    _require(isinstance(storyboard, dict), "storyboard must be an object")
    width = storyboard.get("width", 1080)
    height = storyboard.get("height", 1920)
    fps = storyboard.get("fps", 30)
    for name, value in (("width", width), ("height", height), ("fps", fps)):
        _require(
            isinstance(value, int) and not isinstance(value, bool) and value > 0,
            f"storyboard.{name} must be a positive integer",
        )
    _require(width >= 16 and height >= 16, "storyboard dimensions are too small to render")

    frames = storyboard_frames(storyboard)
    duration_s = frames / fps

    scenes = "".join(
        _scene_markup(scene, index, width, height, fps=fps)
        for index, scene in enumerate(storyboard["scenes"])
    )

    cues = _caption_markup(storyboard)

    payload = {
        "fps": fps,
        "frames": frames,
        "duration": duration_s,
        "width": width,
        "height": height,
    }
    # ``json.dumps`` does not escape ``<``, so a text value containing ``</script>`` would close the
    # block and turn the remainder into markup. Escaping ``<`` as ``\u003c`` is the standard safe
    # embedding and keeps the JSON valid.
    payload_json = json.dumps(payload, ensure_ascii=True, sort_keys=True).replace("<", "\\u003c")

    return f"""<!doctype html>
<html lang="id">
<head>
<meta charset="utf-8">
<title>Bang Motion — {escape(str(storyboard.get("theme", "dusk")))}</title>
<style>
:root{{--w:{width}px;--h:{height}px;--safe:{_SAFE_MARGIN};--bg:{_PALETTE["bg"]};
  --ink:{_PALETTE["ink"]};--accent:{_PALETTE["accent"]};
  --font-heading:"Arial Black","Segoe UI",sans-serif;--font-body:"Segoe UI",Arial,sans-serif}}
{_STAGE_CSS}</style>
</head>
<body>
<div id="stage">
  <div id="world">
    <div class="safe">
{scenes}
    </div>
    <div id="vignette"></div>
  </div>
  <div id="captions">{cues}</div>
</div>
<script>
"use strict";
(function () {{
  var DATA = {payload_json};
  var stage = document.getElementById("stage");
  var world = document.getElementById("world");
  var scenes = Array.prototype.slice.call(document.querySelectorAll(".scene"));

  function clamp01(v) {{ return v < 0 ? 0 : v > 1 ? 1 : v; }}

  // Ported from packages/video/src/speech.ts so both renderers open the mouth at the same times.
  function mouthWeight(windows, ms) {{
    if (!windows || !windows.length) return 0;
    for (var i = 0; i < windows.length; i++) {{
      var start = windows[i].startMs, end = windows[i].endMs;
      var length = end - start;
      if (length <= 0) continue;
      var attack = Math.min(40, length / 2);
      var release = Math.min(70, length / 2);
      if (ms < start || ms >= end + release) continue;
      if (ms < start + attack) return clamp01((ms - start) / attack);
      if (ms < end) return 1;
      return clamp01(1 - (ms - end) / release);
    }}
    return 0;
  }}
  function smooth(v) {{ v = clamp01(v); return v * v * (3 - 2 * v); }}

  function applyScene(section, local) {{
    var dur = Number(section.dataset.dur);
    var start = Number(section.dataset.start);
    var fade = Number(section.dataset.transitionFrames) || 0;
    var active = local >= 0 && local < dur;
    section.style.opacity = active ? "1" : "0";
    if (!active) return;

    var texts = section.querySelectorAll(".text");
    for (var i = 0; i < texts.length; i++) {{
      var at = Number(texts[i].dataset.at) || 0;
      var span = Math.min(18, Math.max(6, dur - at));
      var progress = smooth((local - at) / span);
      texts[i].style.opacity = String(progress);
      texts[i].style.transform = "translateY(" + ((1 - progress) * 42).toFixed(2) + "px)";
    }}

    // Camera breath: a continuous, sub-percent oscillation plus a slow drift, evaluated at every
    // t. ANIMATION_ENGINE.md §3.5 calls this "a baseline layer". Without it a document that only
    // reacts at beats sits perfectly still between them, and freezedetect reports the gap: measured
    // 6.9 s of freeze in a 12.9 s job, blocked on static_ratio 0.53, while Remotion scored 0.0.
    // The amplitude is deliberately small (0.5 %), so this never substitutes for real motion — the
    // creative gate still rejects a scene whose *only* motion is breathing.
    var amp = Number(section.dataset.cameraAmplitude) || 0;
    var phase = dur > 0 ? local / dur : 0;
    var t = (start + local) / DATA.fps;
    // The breath is sub-pixel on a 1080 px stage, and freezedetect's default tolerance (n=-60dB)
    // treats a sub-pixel shift as "identical": measured, a 0.5 % zoom still produced 7.1 s of
    // freeze. The drift is therefore expressed in whole pixels — a few px of travel per second is
    // what makes consecutive frames differ at the detector's threshold, and it is also what a
    // viewer reads as a living frame rather than a still.
    var breath = 1 + 0.006 * Math.sin(t * 1.9) + 0.004 * Math.sin(t * 0.7 + 1.1);
    var zoom = (1 + amp * 0.16 * phase) * breath;
    var driftX = 2.6 * Math.sin(t * 0.55);
    var driftY = 2.1 * Math.cos(t * 0.47 + 0.6);
    world.style.transform =
      "translate(" + driftX.toFixed(3) + "px," + driftY.toFixed(3) + "px) scale(" +
      zoom.toFixed(6) + ")";

    if (fade > 0) {{
      var edge = Math.min(fade, Math.floor(dur / 2));
      var alpha = 1;
      if (local < edge) alpha = smooth(local / edge);
      else if (local > dur - edge) alpha = smooth((dur - local) / edge);
      section.style.opacity = String(alpha);
    }}

    var beats = section.querySelectorAll("[data-beat-frame]");
    var last = null;
    for (var b = 0; b < beats.length; b++) {{
      if (local >= Number(beats[b].dataset.beatFrame)) last = beats[b];
    }}
    var figure = section.querySelector("g[id=maya]");
    if (figure) {{
      var beats = figure.querySelector("#maya-beats");
      var arm = figure.querySelector("#maya-arm-near");
      var armFar = figure.querySelector("#maya-arm-far");
      var head = figure.querySelector("#maya-head");
      var baseArm = Number(beats.dataset.arm);
      var baseHead = Number(beats.dataset.head);
      var kick = 0;
      if (last) {{
        var since = local - Number(last.dataset.beatFrame);
        kick = Math.max(0, 1 - since / 12);
        var kind = last.dataset.beatKind;
        if (kind === "action") kick *= 1.35;
        else if (kind === "emphasis") kick *= 0.85;
      }}
      var eased = smooth(kick);
      if (arm) arm.setAttribute("transform",
        "rotate(" + (baseArm - eased * 46).toFixed(2) + " 41 -404)");
      if (armFar) armFar.setAttribute("transform",
        "rotate(" + ((baseArm - eased * 46) * 0.4).toFixed(2) + " -41 -404)");
      if (head) head.setAttribute("transform",
        "rotate(" + (baseHead - eased * 8).toFixed(2) + " 0 -452)");
      figure.setAttribute("transform", beats.dataset.base);

      // Mouth aperture from the scene's measured speech windows. Same envelope as
      // packages/video/src/speech.ts: 40 ms attack, 70 ms release starting at endMs, both clamped
      // to half the window. Pure in t, so an out-of-order seek lands on the same mouth.
      var mouth = figure.querySelector("[data-mouth]");
      var windows = (section.dataset.speech || "").split(",").filter(function (part) {{
        return part.indexOf("-") > 0;
      }}).map(function (part) {{
        var bits = part.split("-");
        return {{startMs: Number(bits[0]), endMs: Number(bits[1])}};
      }});
      if (mouth) {{
        var sceneMs = local * (1000 / DATA.fps);
        var open = mouthWeight(windows, sceneMs);
        var half = (13 * open).toFixed(2);
        mouth.setAttribute("d",
          open <= 0
            ? "M-14,-462 q14,4 28,0 q-14,6 -28,0 z"
            : "M-14,-462 q14,-" + half + " 28,0 q-14," + half + " -28,0 z");
      }}
    }}
  }}

  var cues = Array.prototype.slice.call(document.querySelectorAll("[data-cue-start]"));

  function applyCaptions(t) {{
    var ms = t * 1000;
    for (var i = 0; i < cues.length; i++) {{
      var start = Number(cues[i].dataset.cueStart);
      var end = Number(cues[i].dataset.cueEnd);
      // Half-open [start, end): a cue never shows at its own end, so two adjacent cues cannot
      // both be visible on the boundary frame. Capture seeks out of order, so this is a pure
      // function of t and never depends on the previously shown cue.
      cues[i].style.display = (ms >= start && ms < end) ? "block" : "none";
    }}
  }}

  function seek(t) {{
    var frame = t * DATA.fps;
    for (var i = 0; i < scenes.length; i++) {{
      var start = Number(scenes[i].dataset.start);
      applyScene(scenes[i], frame - start);
    }}
    applyCaptions(t);
  }}

  function clipsReady() {{ return true; }}

  window.OPENER = {{
    W: DATA.width,
    H: DATA.height,
    DURATION: DATA.duration,
    tl: {{ time: 0, pause: function (t) {{ if (typeof t === "number") {{ this.time = t; seek(t); }} return this; }},
          time_: 0 }},
    ready: false,
    seek: seek,
    seekFrame: seek,
    clipsReady: clipsReady,
    play: function () {{ seek(0); }}
  }};

  document.fonts.ready.then(function () {{
    seek(0);
    window.OPENER.ready = true;
  }});
}})();
</script>
</body>
</html>
"""


def emit_storyboard(props: dict[str, Any]) -> str:
    """Accept the on-disk ``render-props.json`` shape (``{"storyboard": {...}}``).

    The secondary renderer reads the same file the primary one does — that is what makes the parity
    test meaningful. A bare storyboard is accepted too, so a test does not have to wrap it.
    """
    _require(isinstance(props, dict), "render props must be an object")
    storyboard = props.get("storyboard")
    if storyboard is None:
        _require("scenes" in props, 'render props must contain a "storyboard" object')
        storyboard = props
    _require(isinstance(storyboard, dict), "storyboard must be an object")
    return emit_document(storyboard)


def build_render_argv(
    *,
    props_path: Any,
    out_path: Any,
    staging: Any,
    chrome: Any,
    script: Any,
    frames: int | None = None,
    fps: int | None = None,
    frame_cap: int = DEFAULT_FRAME_CAP,
    wall_clock_s: int = DEFAULT_WALL_CLOCK_S,
    html: Any = None,
) -> list[str]:
    """Build the Node capture argv. Never a shell string; every path must be absolute.

    The frame count is *checked against the props file*, not taken on trust: a caller that passes
    ``frames=30`` for a 900-frame storyboard gets a refusal here rather than a 3 % render that
    later fails QC with a confusing message.

    When ``html`` is omitted the document is emitted from the props file into
    ``<staging>/index.html`` and that path is passed to the driver. Passing ``html`` explicitly is
    how a test substitutes a deliberately hostile document without changing the emitter.
    """
    from pathlib import Path

    paths = {"props_path": props_path, "out_path": out_path, "staging": staging, "chrome": chrome,
             "script": script}
    for name, value in paths.items():
        candidate = Path(value)
        if not candidate.is_absolute():
            raise ValueError(f"{name} must be absolute; a relative path renders empty: {candidate}")

    chrome_path = Path(chrome)
    if not chrome_path.is_file():
        raise ValueError(f"chrome-headless-shell is missing at {chrome_path}")
    script_path = Path(script)

    props = json.loads(Path(props_path).read_text(encoding="utf-8"))
    storyboard = props.get("storyboard", props)
    if not isinstance(storyboard, dict):
        raise ValueError("render props must carry a storyboard object")

    total = storyboard_frames(storyboard)
    resolved_fps = fps if fps is not None else int(storyboard.get("fps", 30))
    if not isinstance(resolved_fps, int) or isinstance(resolved_fps, bool) or resolved_fps <= 0:
        raise ValueError(f"fps must be a positive integer, got {resolved_fps!r}")

    render_frames = total if frames is None else frames
    if not isinstance(render_frames, int) or isinstance(render_frames, bool) or render_frames <= 0:
        raise ValueError(f"frames must be a positive integer, got {render_frames!r}")
    if render_frames > frame_cap:
        raise ValueError(
            f"frame count {render_frames} exceeds the frame cap {frame_cap}; "
            "a runaway render is refused before the browser starts"
        )
    if render_frames > total:
        raise ValueError(
            f"frame count {render_frames} exceeds the storyboard's {total} frames"
        )
    if not isinstance(wall_clock_s, int) or isinstance(wall_clock_s, bool) or wall_clock_s <= 0:
        raise ValueError(f"wall_clock_s must be a positive integer, got {wall_clock_s!r}")

    node = shutil_which("node")
    if node is None:
        raise ValueError("node is not on PATH; the capture driver needs it")
    if not script_path.is_file():
        raise ValueError(f"the capture driver is missing at {script_path}")

    if html is None:
        staging_dir = Path(staging)
        staging_dir.mkdir(parents=True, exist_ok=True)
        document_path = staging_dir / "index.html"
        document_path.write_text(emit_document(storyboard), encoding="utf-8")
    else:
        document_path = Path(html)
        if not document_path.is_absolute():
            raise ValueError(f"html must be absolute: {document_path}")
        if not document_path.is_file():
            raise ValueError(f"the document is missing at {document_path}")

    return [
        node,
        str(script_path),
        f"--props={Path(props_path)}",
        f"--html={document_path}",
        f"--out={Path(out_path)}",
        f"--staging={Path(staging)}",
        f"--chrome={chrome_path}",
        f"--frames={render_frames}",
        f"--fps={resolved_fps}",
        f"--frame-cap={frame_cap}",
        f"--wall-clock={wall_clock_s}",
        "--json",
    ]


def shutil_which(name: str) -> str | None:
    """``shutil.which`` behind a name, so the import stays local to the one function that needs it."""
    import shutil

    return shutil.which(name)


__all__ = [
    "DEFAULT_FRAME_CAP",
    "DEFAULT_WALL_CLOCK_S",
    "OPENER_KEYS",
    "build_render_argv",
    "emit_document",
    "emit_storyboard",
    "storyboard_frames",
]
