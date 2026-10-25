# ADR-0006 — `sqlite3`, WAL, forward-only migrations, no ORM

**Status:** accepted

## Context
The donor declares `sqlalchemy==2.1.5` and `apscheduler==3.11.3` and imports neither. Persistence
is 455 lines of `sqlite3` over three tables.

## Decision
Raw `sqlite3`. `journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout=5000`, `foreign_keys=ON`.
A `schema_migrations(version, applied_at)` table and ordered migration functions. No ORM.

## Consequences
No dependency, no mapping layer, no lazy-loading surprises in a background thread. Cost: hand-
written row mapping, which for six tables is a `dict(row)` call.
