"""Redaction for anything that leaves the process: logs, errors, API responses.

The rule is subtractive, not additive: known credential values are removed wherever they appear,
and error bodies are truncated to one line. A provider error body is genuinely useful
(``[429] usage limit reached, reset after 18m``), so it is surfaced — after redaction. CLI stdout
is never surfaced at all, because a CLI can echo a token in a way no pattern would catch.
"""

from __future__ import annotations

import re

REDACTED = "[redacted]"

# Two pattern families, deliberately separate:
#
# * Whole-match patterns redact the entire match and therefore contain no capture groups. Using
#   one group's index as "the secret" is how a redactor replaces a key's prefix and leaves the
#   rest of the key in the message.
# * Assignment patterns (api_key=...) redact only the value, so the field name survives and the
#   error stays readable.

# The whole match is the credential. No capture groups: the entire match is replaced.
_WHOLE_MATCH = (
    re.compile(r"\b(?:sk|rk|pk)-[A-Za-z0-9_\-]{8,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{8,}", re.IGNORECASE),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b"),
)

# Only the value is the credential; the field name is kept so the message still reads.
_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret|password|passwd)\b"
    r"(\s*[:=]\s*)"
    r"(['\"]?)([^\s'\"]{6,})\3"
)


def redact(text: str, *, secrets: tuple[str, ...] = (), limit: int = 240) -> str:
    """Remove known secret values and credential-shaped strings; collapse to one line."""
    if not text:
        return ""
    out = str(text)

    # Known values first: an exact string we were told about beats any pattern.
    for secret in secrets:
        if secret and len(secret) >= 4:
            out = out.replace(secret, REDACTED)

    for pattern in _WHOLE_MATCH:
        out = pattern.sub(REDACTED, out)

    out = _ASSIGNMENT.sub(
        lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}{REDACTED}{m.group(3)}", out
    )

    out = " ".join(out.split())
    if len(out) > limit:
        out = out[: limit - 1] + "\u2026"
    return out


def redact_url(url: str) -> str:
    """Strip userinfo and any credential-looking query value from a URL for display."""
    if not url:
        return ""
    out = re.sub(r"//[^/@]*@", "//", url)
    out = re.sub(r"(?i)([?&](?:api[_-]?key|token|key|secret)=)[^&]*", r"\1" + REDACTED, out)
    return out
