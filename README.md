# ShortsFactoryAI Studio

Local-first autonomous animation studio for YouTube Shorts. A topic goes in; a validated
1080×1920 MP4 comes out, produced by specialised agents, inspected by QA, approved by you.

Windows 11 · Python 3.12 · Node 22+ · SQLite · FastAPI · Next.js · Remotion · React Three Fiber
No Docker. No VPS. No mandatory cloud.

## Status

**Phase 1 (foundation) — backend complete, dashboard in progress.** Nothing here is claimed to
work until its gate passes; see `docs/IMPLEMENTATION_ROADMAP.md` for the exact state of every task.

What is verified today:

| Area | State | Evidence |
| --- | --- | --- |
| Contracts | done | 34 tests, incl. camera-target and contiguous-scene rejection |
| Netguard + redaction | done | CIDR deny, resolve-then-pin, DNS-rebinding, redirect refusal |
| Credentials | done | DPAPI round-trip on this host; sentinel never appears in output |
| Providers | done | 5 transports, immutable resolution, capability-before-call |
| Orchestration | done | WAL jobstore, atomic artifacts, token-owned leases, honest runner |
| Events + studio projection | done | stale worker reads `waiting`, never `working` |
| API | done | jobs, cancel, approve/reject gate, Range video, providers, SSE |
| Pipeline | done to `STORYBOARD_READY` | 5 agent stages, real usage attribution, resume with 0 duplicate calls |
| Dashboard | **in progress** | shell, tokens, api client, proxy, 3D scene, 2D fallback written; pages next |
| Render / audio / QA / publishing | not started | Phase 2 and 4 |

205 Python tests, ruff clean.

## Read first

| Document | Why |
| --- | --- |
| `PRODUCT_REQUIREMENTS.md` | What the product must do, with measurable success criteria |
| `docs/ARCHITECTURE.md` | Layering, and the eleven decisions that shape it |
| `AGENTS.md` | Rules for the coding agent working in this repo |
| `docs/AGENT_CONTRACTS.md` | The product's agent inventory, rules, failure taxonomy |
| `docs/DATA_CONTRACTS.md` | Every artifact schema; the boundary between model output and code |
| `docs/PROVIDER_SYSTEM.md` | Transports, capabilities, credentials, SSRF policy |
| `docs/ANIMATION_ENGINE.md` · `docs/MOTION_SKILLS.md` · `docs/CHARACTER_SYSTEM.md` | How pixels are made |
| `docs/STUDIO_3D.md` | The virtual studio, and why it can never lie |
| `docs/TEST_STRATEGY.md` | What must be tested, and what a passing test is worth |
| `docs/RISK_REGISTER.md` | 18 risks with mitigations, and the assumption log |
| `docs/ADR/` | One page per significant decision |

## Layout

```
apps/
  api/            FastAPI: HTTP surface, SSE, worker thread
  dashboard/      Next.js: studio, jobs, providers, skills, calendar, settings
packages/
  core/
    contracts/    Pydantic models + JSON Schema. Imports nothing from this project.
    security/     netguard, DPAPI secret store, redaction
    providers/    transports, immutable resolution, capability validation, usage
    agents/       one class per agent, typed in / typed out
    orchestration/ state machine, job store, leases, scheduler, budgets
    media/        ffmpeg/ffprobe, TTS, render bridge, per-scene rerender
    motion/       MotionSkillRegistry, bang-motion ingest, anti-PPT rules
    observability/ events, projection, SSE
    publishing/   YouTube OAuth, private-first upload, reconciliation
  video/          Remotion compositions + art kit + character engine (Node)
config/
  schemas/        generated JSON Schemas (checked in, diff must be empty)
  studio.json     operator runtime config (gitignored)
data/
  jobs/<id>/      artifacts per job (gitignored)
  motion-skills/  vendored motion skills (gitignored)
  secrets/        DPAPI-sealed credentials (gitignored)
docs/
scripts/
tests/
```

## Run

```bash
# install
uv sync
npm install --prefix apps/dashboard --include=dev --no-audit --no-fund
npm install --prefix packages/video  --include=dev --no-audit --no-fund

# check
uv run ruff check .
uv run pytest -q
npm --prefix apps/dashboard run typecheck
npm --prefix apps/dashboard run test

# run
start-studio.bat          # API :8018 + dashboard :3018
```

`start-studio.bat --check` verifies prerequisites without starting anything.

## Non-negotiables

1. Never claim a stage succeeded without an artifact on disk that validates.
2. Never let a mock job look publishable.
3. Never put a credential in a response, a log, an artifact, or git.
4. Never let model output reach privileged code.
5. Never show work in the studio that is not happening.
6. Private upload first; public release only on an explicit, confirmed instruction.
