# ADR-0001 — New repository, donor as reference

**Status:** accepted · **Date:** 2026-10-25

## Context
An existing tree at `OneDrive/Documents/coding/projects/ShortsFactoryAI` contains a working
pipeline: 22.5 kLOC Python, 11.3 kLOC TypeScript, 735 passing tests, a real 1080×1920 MP4.
The brief asks for a new product with an independent architecture.

## Decision
Start a new repository. Port donor modules one at a time, with their tests, after re-arguing
each against this brief.

## Alternatives
- **Rewrite from scratch.** Rejected: `packages/video` is 5.4 kLOC of React/Remotion reached
  through one subprocess call; a canvas rewrite means hand-reimplementing gradients, clip-path
  and transforms with visual regression on every template.
- **Fork and mutate in place.** Rejected: inherits 51 uncommitted files, a provider layer that
  mutates shared instances, and two declared-but-unused dependencies. No ability to say no.

## Consequences
Two trees exist and can drift (R-11). Mitigation: `docs/PORT_LOG.md` records the donor commit per
ported module; the donor is frozen except critical fixes, which are ported forward.
