# ADR-0002 — Layering and dependency direction

**Status:** accepted

## Decision
`apps/*` → `core/orchestration` → `core/agents` → `core/providers` → `core/contracts`, with
`core/media`, `core/motion`, `core/observability`, `core/publishing` as siblings under
`orchestration`. `contracts` imports nothing from the project. Nothing imports `apps/*`.

## Enforcement
`tests/test_architecture.py` parses the import graph with `ast` and fails on a violation. Rules
are checked, not documented-and-ignored: a comment saying "don't import fastapi in core" has
never stopped anyone.

## Consequences
`core` cannot use FastAPI's `HTTPException`, so domain errors are plain exceptions mapped at the
API boundary. That is the correct direction anyway.
