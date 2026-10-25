# TEST_STRATEGY

## 1. Principle

A test exists to make a specific failure impossible to ship. "Coverage" is not a goal; a test
that would pass with the feature deleted is worse than no test, because it manufactures
confidence.

Every regression test for a failure path must be **proven to fail without the fix**. The donor's
own lesson: a preflight test that reused a token-seeded fixture uploaded successfully and still
"passed", hiding a second lock on the retry path — the fixture made the guarded branch
unreachable. Rule: if the fixture already provides what the guarded code is supposed to be
missing, delete that provision in the test and re-run.

## 2. Layers

| Layer | Tool | Scope | Runtime budget |
| --- | --- | --- | --- |
| Unit (py) | pytest | contracts, netguard, providers, state machine, leases | < 30 s |
| Integration (py) | pytest + local stub HTTP server | provider transports, orchestrator resume, event replay | < 90 s |
| Contract | pytest + JSON Schema diff | artifact schemas match models | < 5 s |
| Unit (ts) | vitest | state derivation, formatters, hooks | < 20 s |
| E2E | Playwright | real browser against a real API in mock mode | < 3 min |
| Render | node script | every template at 1080×1920, one still each | < 4 min |
| Media | pytest + ffprobe/ffmpeg | a produced MP4 satisfies every technical requirement | < 5 min |
| Visual | vision inspection | rendered stills actually contain what they should | manual, per phase gate |

## 3. What must be tested, by invariant

### Security
- A planted sentinel secret never appears in: API responses, log output, event rows, job
  artifacts, error messages. Grep-based, one test, run over a full job.
- Each denied CIDR range is rejected by `netguard`; a hostname resolving to a denied address is
  rejected; a hostname that resolves public-then-private is rejected on the pinned IP (no second
  resolution).
- A credential bound to origin A is withheld when `base_url` moves to origin B.
- A 3xx from a provider endpoint is an error, not a follow.
- Generated motion HTML is loaded only in an isolated process with no network: a page that
  attempts `fetch('http://169.254.169.254')` must fail to reach it.

### Durability
- Illegal state transitions raise; the allow-list table is tested pair by pair.
- A job killed mid-stage resumes and produces exactly one provider call per stage (counter
  assertion, not a log assertion).
- Two `JobStore` instances: the second cannot steal a live lease; a stale worker that lost its
  lease never writes a state transition.
- Reconnect after disconnect: no event gap, no duplicate event, snapshot equals replay.
- A completion marker is never written before its data files (assert file mtimes/order).

### Honesty
- A stage cannot report `completed` without an artifact that validates.
- `progress` is only emitted from real counters; a cached stage emits `artifact_reused`, never a
  synthetic `working` at 100 %.
- A live job with no available provider raises; it does not fall back to mock.
- Visual QA without a `vision` provider records `skipped_no_vision_provider`.
- A mock job is `publishable: false`.

### Media
- ffprobe: 1080×1920, 30 fps, h264/yuv420p, exactly one video + one audio stream, frame count ==
  sum of scene durations, duration matches narration within 120 ms.
- `blackdetect`, `silencedetect`, `freezedetect` find nothing unexpected.
- Loudness within −16 LUFS ± 2.
- Subtitle cues lie inside the safe area and inside the duration.
- Render twice → identical frame hashes.
- Both renderers → both pass the same probe.

### UI
- Every visible character state equals the persisted event status (Playwright reads
  `data-state` and compares to the API response).
- No control is decorative: every button in the E2E run has an observable effect.
- Empty, loading, error, and success states render for each page.
- The 2D fallback keeps every route reachable.
- No horizontal overflow at 390 px width; the job list scrolls rather than growing the page.

## 4. Fixtures and test doubles

- `StubTransport` — an in-process HTTP server with scripted responses; used for every provider
  test. No real network, no real key.
- `RecordingProvider` — records calls for assertions about duplicates and budgets.
- `FakeClock` — lease expiry and backoff without sleeping.
- Golden artifacts in `tests/fixtures/` for contract validation; never regenerated automatically
  (a regenerated golden hides a breaking change).

## 5. Negative fixtures (must fail)

| Fixture | Must be caught by |
| --- | --- |
| black.mp4 | `black_frames` |
| silent.mp4 | `unexpected_silence` |
| frozen.mp4 | `frozen_frames` |
| 720×1280.mp4 | `resolution` |
| 25fps.mp4 | `frame_rate` |
| no_audio.mp4 | `audio_stream_count` |
| text_wall.json | `text_density` |
| slideshow.json | `static_ratio` |
| one_theme.json | `repeated_world` |
| camera_no_target.json | contract validation |
| mock_job.json | `publishable: false` |

## 6. Running

```bash
uv run pytest -q                       # python suite
uv run pytest -q -k "not slow"         # fast loop
npm --prefix apps/dashboard run test   # vitest
npm --prefix apps/dashboard run test:e2e
npm --prefix packages/video run still-smoke
uv run python scripts/verify_video.py <job_id>
```

Three consecutive green runs are required before a phase gate is declared passed. One flake is a
failure, quarantined with a written cause.
