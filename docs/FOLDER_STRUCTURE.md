# FOLDER STRUCTURE

Ownership is explicit; a file in the wrong layer is an architecture violation, not a style issue.

```
ShortsFactoryAI-Studio/
├── apps/
│   ├── api/                       HTTP only. No domain rules.
│   │   ├── main.py                app factory, middleware, route mounting
│   │   ├── routes_jobs.py         job CRUD, run, cancel, artifacts, video
│   │   ├── routes_providers.py    provider CRUD, test, models, bindings
│   │   ├── routes_studio.py       snapshot, stream (SSE), history
│   │   ├── routes_publishing.py   connect, upload, schedule, reconcile
│   │   └── deps.py                auth token, job store, settings
│   └── dashboard/                 presentation only.
│       ├── src/app/               one folder per route
│       ├── src/components/        shared UI; pixel/ = 2D fallback
│       ├── src/three/             R3F scene, zones, characters, materials
│       ├── src/lib/               api client, hooks, formatters
│       └── e2e/                   Playwright specs
├── packages/
│   ├── core/
│   │   ├── contracts/             Pydantic + JSON Schema. Imports nothing local.
│   │   ├── security/              netguard, secretstore (DPAPI), redact
│   │   ├── providers/             base, openai_compat, anthropic, ollama, cli, mock, resolve, usage
│   │   ├── agents/                one module per agent
│   │   ├── orchestration/         states, jobstore, leases, runner, scheduler, planner, budget
│   │   ├── media/                 ffmpeg, audio, render bridge, scene_data, thumbnail
│   │   ├── motion/                registry, bang_motion ingest, rules (anti-PPT), brief
│   │   ├── observability/         events, projection, stream, schedule
│   │   └── publishing/            oauth, youtube, transport, service, reconcile
│   └── video/                     Node/Remotion. Reached only via subprocess.
│       ├── src/compositions/      7 scene templates + Short + Thumbnail
│       ├── src/art/               Stage, Figure, Prop, Camera, Effects, palette, rng
│       ├── src/character/         rig, poses, expressions, motion, mouth, assets/maya
│       └── scripts/               still-smoke, free-port, frame-capture
├── config/
│   ├── schemas/                   generated JSON Schema (checked in)
│   ├── studio.json                operator config (gitignored)
│   └── studio-history/            rollback snapshots (gitignored)
├── data/
│   ├── jobs/<job_id>/             artifacts + output.mp4 (gitignored)
│   ├── motion-skills/             vendored skills (gitignored)
│   ├── secrets/                   DPAPI blobs (gitignored)
│   └── factory.db                 SQLite, WAL (gitignored)
├── docs/
│   ├── ADR/                       one decision per file
│   ├── superpowers/plans/         phase plans
│   └── *.md                       the twelve planning artifacts
├── scripts/                       operator CLIs (run, verify, publish, export, scan)
├── tests/                         python suite, mirrors package layout
└── vendor/bang-motion/<version>/  pinned skill copy with local assets
```

## Rules

| Rule | Reason |
| --- | --- |
| `contracts/` imports nothing from this project | It is the shared vocabulary; a cycle here poisons everything |
| `packages/core/**` never imports `fastapi`, `starlette`, `next` | Domain code must be runnable from a CLI and a test without a web server |
| `apps/dashboard/**` never imports `packages/core/**` | The browser talks HTTP, not Python |
| `packages/video/**` is reached only through `media/render.py` | One process boundary, one place to sandbox |
| Generated files live under `data/`, never beside source | `git status` stays meaningful |
| Every `tests/test_x.py` has a matching `packages/.../x.py` | A test that names no module is testing a wish |
