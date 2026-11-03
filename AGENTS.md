# AGENTS.md — rules for a coding agent working in this repository

This file is for the **coding agent**, not the product's agents. The product's agent inventory,
contracts and failure taxonomy live in `docs/AGENT_CONTRACTS.md`; read that before touching
`packages/core/agents/`.

Product: ShortsFactoryAI Studio — a local-first animation production system for YouTube Shorts.
Windows 11, no Docker, no VPS. Python 3.12 + FastAPI + SQLite on the back, Next.js + React Three
Fiber on the front.

---

## 1. Read before you write

| Order | File | Why |
| --- | --- | --- |
| 1 | `docs/IMPLEMENTATION_ROADMAP.md` | What phase we are in and what its exit gate is |
| 2 | `docs/ARCHITECTURE.md` | Layering, and the eleven decisions you must not undo |
| 3 | `docs/DATA_CONTRACTS.md` | Every artifact schema — the boundary between model output and code |
| 4 | `docs/TEST_STRATEGY.md` | What a passing test is worth here |
| 5 | `docs/DEV_NOTES.md` | Host-specific traps that look like code bugs |

`docs/PORT_LOG.md` records what came from the donor tree and at which commit. **"The donor does it
this way" is not a justification.** Every ported module is re-argued against this repo's brief.

## 2. The commands that define "done"

```bash
pwsh -File scripts/check.ps1           # every gate below, one PASS/FAIL line each
bash scripts/check.sh                  # same, for a POSIX shell

uv run ruff check .                    # 0 findings
uv run pytest -q                       # all green
npm --prefix apps/dashboard run typecheck
npm --prefix apps/dashboard run test
npm --prefix apps/dashboard run test:e2e
```

`scripts/check.ps1` / `check.sh` run all of those plus the schema diff, the secret scan and the
video suites, and exit non-zero if any gate failed. Use `-Quick` / `--quick` to skip the two gates
that need a browser. Reach for the individual commands when you are iterating on one gate.

A change is not done because it compiles. Run the suite. If you cannot run a command, say so
plainly and leave the tree working — do not claim a result you did not observe.

**The Python type gate runs.** `uv run mypy packages/core --strict` exits 0 over all 56 core source
files; mypy 1.18.2 is in the `dev` dependency group, `[tool.mypy]` sets `strict = true`, and both
`scripts/check.ps1` and `check.sh` invoke it as a gate alongside ruff, pytest and the schema diff.
Keeping it green means no blanket `# type: ignore` and no per-module `ignore_errors`; the one
tolerated escape hatch is a single ignore with a written reason in `docs/IMPLEMENTATION_ROADMAP.md`.
Note the narrowing trap: `x = value if isinstance(value, dict) else {}` on an `Any` is inferred as
`Any | dict[Any, Any] | None`, so annotate the target (`x: dict[str, Any] = …`) instead.

Three consecutive green runs are required before a phase gate is declared passed. One flake is a
failure: quarantine it with a written cause in `docs/TEST_STRATEGY.md`.

## 3. Non-negotiables

These are enforced by tests or by structure. Breaking one is a bug even if the suite stays green —
and if you break one, add the test that would have caught it.

1. **No unverified success.** A stage may only report `completed` after its artifact exists on disk
   and validates against its contract. `packages/core/orchestration/runner.py` enforces this; do
   not add a path around it.
2. **No silent mock.** A job records `provider_mode` at creation. A live job that cannot reach a
   provider raises `NoProviderAvailable`; it never degrades to mock. A mock job is
   `publishable: false` at the approval gate, permanently.
3. **No credential in an output.** Not in a response, a log line, an event row, an artifact, or
   git. Credentials are *references* (`{"env": NAME}` or `{"dpapi": ID}`) resolved at call time.
   `/api/providers` returns `has_credential`/`credential_source` and nothing else.
4. **Model output never reaches privileged code.** The model writes `SceneSpec` JSON. It never
   writes JSX, CSS, HTML, or a shell string. No `eval`, no `shell=True`, no f-string command.
5. **Outbound URLs go through `packages/core/security/netguard.py`.** No exceptions, including
   "it's just a local health check". `allow_private_hosts` is a per-provider opt-in.
6. **The studio is a projection.** It reads persisted events and writes nothing. No character may
   animate `working` unless a persisted event says `working` and the lease is live.
7. **Private upload first.** Public release is a separate, explicit, confirmed action. A scheduled
   task may never bypass approval.

## 4. Layering — checked by `tests/test_architecture.py`, not by convention

```
apps/*  →  core/orchestration  →  core/agents  →  core/providers  →  core/contracts
```

- `core/contracts` imports nothing else from this project.
- `packages/core/**` never imports `fastapi`, `starlette`, `next`, or `uvicorn`. Domain code must
  run from a CLI and a test without a web server.
- `apps/dashboard/**` never imports `packages/core/**`. The browser talks HTTP.
- `packages/video/**` is reached only through one subprocess call in `media/render.py`.

If your change needs a new edge in that graph, write an ADR in `docs/ADR/` first.

## 5. Working style

- **Vertical slices.** Database → API → UI for one feature, working, before the next feature. No
  unrelated UI mockups.
- **Contract before implementation.** Add or change the Pydantic model and its rejection tests
  before writing the code that consumes it.
- **A test for a failure path must be proven to fail without the fix.** If the fixture already
  provides what the guarded code is supposed to be missing, delete that provision and re-run.
  `pytest.raises` alone proves nothing.
- **Leave the tree green.** Never hand back a broken build, a half-applied edit, or a red suite.
- **Small commits, by name.** `git add <file>`, never `git add -A` — `config/studio.json`,
  `config/studio-history/`, `data/jobs/*`, `data/secrets/*` are operator runtime state and must
  stay untracked.

## 6. Host traps that have already cost hours (full list: `docs/DEV_NOTES.md`)

- `NODE_ENV=production` is exported in this shell. A bare `npm install` **prunes every
  devDependency** and silently breaks `test`/`typecheck`. Always
  `npm install --include=dev --no-audit --no-fund`.
- Never pipe a `node`/`python` command into `tail`/`head` here — it dies with `stdin is not a tty`.
  Run bare and read the full output.
- Native tools (git, node, python, rg) do **not** get MSYS path translation. `git -C /c/Users/x`
  fails; use `C:/Users/x`. `cd /c/Users/x` works because `cd` is a shell builtin.
- Remotion: always an explicit `--port` (3000 collides with the dashboard, and on Windows a bind
  can "succeed" on an occupied port) and an **absolute** `--props` path (a relative path fails
  silently as an empty render).
- A patch tool can report success while writing a literal `***` over real code. After every patch:
  `grep -n '\*\*\*' <file>` and `python -c "import ast;ast.parse(open(p,encoding='utf-8').read())"`.
  A compiled artifact is not proof — a stale `.pyc` keeps the old behaviour alive.

## 7. What is out of scope unless the operator asks

- Paid image/video generation services.
- Publishing anything, connecting a YouTube account, or scheduling a remote action.
- Changing machine-wide settings, installing global tools, or touching another Hermes profile.
- Rewriting the Python orchestrator in another language.
