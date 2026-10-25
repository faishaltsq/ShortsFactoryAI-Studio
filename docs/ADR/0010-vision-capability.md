# ADR-0010 — Vision QA requires a declared `vision` capability

**Status:** accepted

## Decision
The visual QA pass resolves a provider with `vision` in its capabilities. If none exists, the
artifact records `visual.status = "skipped_no_vision_provider"` — a distinct, visible, non-passing
state. There is no default and no fallback to a text model.

## Why
The failure mode is not "QA is skipped"; it is "QA is claimed". A text model asked to review frames
will confidently describe a video it never saw. Making the capability explicit and the absence
visible is the only structural defence.
