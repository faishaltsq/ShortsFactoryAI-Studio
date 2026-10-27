# Continuation Plan — ShortsFactoryAI Studio

Date: 2026-10-27. Basis: `docs/IMPLEMENTATION_ROADMAP.md` (checked/unchecked state verified
against the tree on this date), the suite (`52` test files, all gates green as of the commits
below), and the API/UI surface walk (`apps/api/main.py`, `apps/dashboard/src/lib/api.ts`,
`apps/dashboard/src/app/*`).

Ordering rule: vertical slices, DB → API → UI, one feature working before the next. Blocked
items are listed last and get no code until their unblock arrives.

## Where the product stands

- Phases 1–3 exit gates: **passed with evidence** (roadmap marks them `[x]` with test names).
- Phase 4 offline half: **complete** (scheduler claim/refusal, discovery, metadata, thumbnail,
  publish/reconcile against the stub, usage accounting).
- The gap that remains inside completed phases is polish-with-evidence, listed below as R1.
- The genuinely missing product components are R2–R5, then the operator-blocked tier.

## R1 — Close the remaining in-phase gaps (all provable offline)

1. **Per-scene rerender (FR-5.4).** `render.json.scene_hashes` exists, nothing consumes it.
   Slice: `packages/core/media/render.py` gets a cache-lookup path keyed by
   `(scene_hash, renderer, theme, width, height)`; cached scenes are spliced from
   `data/render-cache/<job>/<scene>.mp4`-style part files, re-encoded pass-through into the
   container. Test: change one scene in a two-scene storyboard, re-render, assert the unchanged
   scene's bytes were not re-encoded (framemd5 equal AND env probe counting renderer invocations
   == 1). Acceptance: roadmap 2.3 last checkbox flips to `[x]`, parity suite still green.
2. **Dashboard: Job detail artifacts + publish surface.** `api.ts` has no `publish`,
   `reconcile`, or `metadata` calls; the Jobs page calls only
   `jobs/job/createJob/runJob/cancelJob/approve/reject`. Slice: add client methods + a publish
   panel on the job detail (state-gated: visible at `APPROVED`, calls `POST
   /api/jobs/{id}/publish` with `transport: "stub"`, shows `uncertain → reconcile` flow), plus
   the artifact viewer for `metadata.json` at the approval gate. Tests: Vitest for the panel's
   state gating; Playwright: approve → publish → published badge on the mock-mode path
   (stub transport is the only one, so this stays local-only).
3. **Usage page block for a single job** (API `/api/usage/job/{id}` exists, unused by the UI).
   Small: a per-job cost row in the job detail header. Vitest only.
4. **Dashboard: remaining honest placeholders.** Sidebar advertises `/create`, `/storyboard`,
   `/assets`, `/agents`, `/skills`, `/calendar`, `/settings` with no pages. Do **not** build all
   seven blindly: `/create` (topic + provider_mode form calling `createJob`) and `/calendar`
   (read-only schedule proposal list from `upcoming()`) are product-real; the rest stay
   placeholders until their phase. Update `fallback-routes.spec.ts` in the same commit (it fails
   the suite when a page appears).
5. **Vision-provider negative drill** (Phase 2 "not proven" line): a contract test that a
   malformed/blocked vision response lands `BLOCKED` with a recorded finding, using a scripted
   HTTP stub, so the `passed` branch's counterpart is tested without cloud access.

Order within R1: 1 → 2 → 3 → 4 → 5 (1 is the only core algorithm; 2–4 are one UI slice each;
5 is a single test module).

## R2 — Production calendar + queue semantics

`jobs` is a persistent store with no queue semantics (roadmap Phase 4, unchecked). Slice:
- `JobStore`: `claim_next` gains priority + a `calendar_slots` minimal table (migration 3) —
  planned publish time, created by the operator at approval.
- `SchedulerLoop` last-claim wins unchanged; slots only *gate* `READY_FOR_APPROVAL → publish`
  eligibility, never bypass approval (invariant 7 re-tested).
- UI: `/calendar` becomes the slot editor (already listed in R1.4).
- Tests: slot passes `due` ordering, a slot in the future blocks publish, deleting a slot
  unblocks, crash mid-slot-edit leaves no partial row.
- Exit: roadmap Phase 4 "Persistent queue, production calendar" checkbox.

## R3 — Thumbnail/Final cut QC wiring completeness

`build_thumbnail_stage` runs inside publish, but `technical-qc.json` does not check the
thumbnail (dimensions, non-blank). Slice: one QC check + negative fixture (blank PNG caught).
Half-day slice, closes "QC is only about the video" asymmetry.

## R4 — Topic → published E2E demo script (offline, stub transport)

A `scripts/demo_phase4.py` in the same assert-listing style as `demo_phase1.py`: topic
discovery → job → run → approve → publish (stub) → reconcile no-op, across a simulated
restart, asserting zero duplicate renders/uploads. This is the reproducible proof for the
Phase 4 verify line's offline half, currently spread across six test modules.

## R5 — Docs/architecture debt

- `docs/AGENT_CONTRACTS.md`: add `DiscoveryAgent` attribution note (`DirectorAgent`-attributed
  discovery stage exists; the contracts doc doesn't list the discovery event kind).
- `PRODUCT_REQUIREMENTS.md` FR-5.4 mark implemented when R1.1 lands.

## Blocked tier (do not start; each needs its unblock named)

| Item | Unblock |
| --- | --- |
| YouTube OAuth installed-app flow end-to-end (listener, browser launch, `videos.insert`) | Operator's Google Cloud OAuth client + account consent; never test against a real channel |
| Thumbnail **upload** transport (`POST /api/thumbnail` endpoint → real target) | Same YouTube client as above (M7, operator decision) |
| Cloud vision provider exercise (`passed` branch against OpenAI/Anthropic) | Operator's paid API key, `config/studio.json` declaration |
| Music/SFX acquisition | Real licensed asset path decision |

## Commit discipline

Each item above is at least one commit named for the roadmap checkbox it closes. `data/`,
`config/studio.json`, `factory.db`, `secrets/` stay untracked. Run `scripts/check.ps1
-Quick` before each yield; the full suite (both browser gates) before declaring R1.done.
