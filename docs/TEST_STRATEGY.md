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
| Types (py) | **none — gap** | mypy is undeclared and uninstalled, so the Python side has never been type-checked. Not a passing gate: an unrun one. See IMPLEMENTATION_ROADMAP's cross-cutting table for the eight modules in scope and what would make it runnable. | — |

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
- ffprobe: 1080×1920, 30 fps, h264/yuv420p, exactly one video + one AAC audio stream, frame count
  equals the audio-timed render props, final duration matches `audio.json` narration within 120 ms.
- `blackdetect`, `silencedetect`, `freezedetect` find nothing unexpected.
- Loudness within −16 LUFS ± 2.
- Subtitle cues are generated from ordered word boundaries, remain readable, and lie inside the
  narration duration and the rendered safe area.
- **"Cues fit their bounds" is not the same as "cues reached a frame."** `verify_video.py` can only
  prove the former: it reads `audio.json` and checks the windows. It cannot see whether a renderer
  drew the caption. That gap let a renderer ship with narration and no captions at all while the
  media gate stayed green. Every renderer therefore needs a pixel-level test: extract a frame inside
  a cue window and one outside it, crop the caption band (bottom 360 px of 1920, 90 px insets), and
  assert the band differs and the inside frame carries text
  (`test_bang_motion.py::test_captions_reach_pixels_inside_their_window`).
- **The same argument applies to the mouth.** A closed mouth renders a perfectly valid MP4, so no
  stream-level check can see it. The secondary renderer's aperture is driven by `scene.speech`
  (measured word windows, carried as `data-speech` on each scene and rewritten into `#maya-mouth`
  on every `seek`), using the primary renderer's envelope: 40 ms attack, 70 ms release, both clamped
  to half a word window, pure in `t`, and **closed at every `t` when there are no windows** — never
  a synthetic sine. The proof is a tight head crop, not the caption band:
  `test_bang_motion.py::test_the_mouth_reaches_pixels_inside_a_speech_window` renders 90 real
  frames, extracts frame 9 (inside a 200–1400 ms window) and frame 51 (past the 70 ms release),
  crops `200:160:440:820`, and asserts `YMAX > 60` and `YAVG > 1.0` on an `all_mode=difference`
  blend. Measured on this host: **YAVG 3.372, YMAX 160**. Those are a measurement from this fixture,
  not a universal threshold — the figure also drifts 2–3 px between the frames, so some delta
  exists regardless; the mouth's filled shape is what lifts the peak to 160.
- Speech windows are a trust boundary, tested as such: `_speech_windows` rejects unordered,
  overlapping, and past-scene-end windows with a `ValueError` naming `speech[index]` and the reason,
  and accepts an exact scene-end boundary as well as a window inside a fractional scene duration
  (`durationInFrames * 1000 / fps` is not rounded down). It does not sort, clamp, or drop.
  Tests: `test_unordered_speech_windows_are_rejected`,
  `test_overlapping_speech_windows_are_rejected`,
  `test_a_speech_window_past_the_scene_end_is_rejected`,
  `test_a_speech_window_ending_exactly_at_the_scene_end_is_accepted`,
  `test_a_speech_window_ending_inside_a_fractional_scene_duration_is_accepted`.
- **A file-existence assertion is not a motion assertion.** `is_file() and st_size > 1000` passes
  for two identical frames. Motion is measured over the **character box**, not the frame, because
  whole-frame `YAVG` stays under 1.0 for a visible arm swing in 1080×1920. Measured floors on this
  fixture: identical pair 0.000, idle 0.61 (Remotion) / 0.80 (Bang Motion), real action beat 0.99
  (Remotion) / 3.11 (Bang Motion); the assertion threshold is 1.5
  (`test_renderer_parity.py::test_matched_stills_at_a_character_beat`).
- Render twice → identical frame hashes.
- Both renderers → both pass the same probe.
- **`static_ratio` is measured per renderer and the two values are not comparable.** The same
  storyboard scores 0.040 under Remotion and 0.166 under Bang Motion, because Remotion's
  compositions animate continuously while the Bang Motion document currently reacts only at
  `motion.beats` plus a detector-satisfying 2–3 px drift. **Do not compare figures across runs at
  all**: the offline voice produces a different narration length each time, which retimes the scenes
  and moves `static_ratio` on its own. The only comparable measurement is an A/B on one identical
  `render-props.json` — that pair is 0.1662 with captions vs 0.1803 without, so captions *reduce*
  static time by ~0.014. A green Bang Motion `static_ratio` means "not a still", not "animated"; see
  ADR-0012. Do not read the drift as authored motion.
- Parity between renderers is **structural, never visual**: same props, same probe, same frame
  count, same cut indices, per-renderer determinism. Cross-renderer PSNR is measured and printed but
  never asserted — it scores 14.34 dB between the two renderers and 14.38 dB against unrelated
  content, so it cannot distinguish parity from difference.

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

Every row names the exact check that must catch it, and the test that proves it. A fixture is only
worth keeping if removing the check makes its test fail.

| Fixture | Caught by | Test |
| --- | --- | --- |
| 3 s clip with a 1.03 s black span | `black_frames` | `tests/test_qc_detectors.py::test_a_black_interval_is_detected_by_the_real_filter` |
| digital silence (`anullsrc`) | `unexpected_silence` | `test_a_silent_audio_stream_is_detected` |
| one still looped 3 s | `frozen_frames` | `test_a_still_loop_is_detected_as_frozen` |
| 720×1280 | `resolution` | `tests/test_qc_evaluate.py::test_a_720p_render_fails_resolution` |
| 25 fps | `frame_rate` | `test_a_25fps_render_fails_frame_rate` |
| video only, no audio stream | `audio_stream_count`, `audio_codec` | `test_a_render_without_audio_fails_the_stream_and_codec_checks` |
| `yuvj420p` / full-range tag | `pix_fmt`, `color_range` | `test_yuvj420p_fails_the_pixel_format_check`, `test_a_full_range_tag_fails_the_color_range_check` |
| untagged stream (no `color_range`) | `color_range` | `test_a_missing_color_range_tag_fails_because_it_cannot_be_proven_limited` |
| a detector that did not run | `black_frames` (hard failure) | `test_a_detector_that_did_not_run_is_a_hard_failure_not_a_warning` |
| 416-frame render vs 434-frame props | `frame_count` | `test_frame_count_is_expected_from_the_timed_props_not_the_render` |
| 3 s render vs a 5 s narration | `duration` | `tests/test_technical_stage.py::test_a_render_shorter_than_its_narration_blocks_on_duration` |
| tampered `output.mp4` | `checksum` | `test_a_tampered_output_blocks_on_the_checksum` |
| missing / extra scene hash | `scene_hashes` | `test_scene_hash_keys_must_equal_the_storyboard_scene_ids` |
| cue past the narration / overlapping / 43 chars | `subtitle_bounds` | four tests in `test_qc_evaluate.py` |
| `-30 LUFS` / `+0.2 dBTP` | `loudness`, `true_peak` | `test_loudness_outside_minus_16_plus_minus_2_fails`, `test_a_true_peak_above_minus_one_db_fails` |
| 400 chars in 180 frames | `text_density` | `test_text_density_above_42_chars_per_second_fails` |
| one static still for the whole video | `static_ratio` | `test_static_ratio_above_0_45_fails` |
| every transition a 40-frame fade | `fade_ratio` | `test_fade_ratio_above_0_35_fails` |
| 3 scenes, one `data.shots` entry | `shot_variety` | `test_shot_variety_is_read_from_rendered_data_shots` |
| 3 scenes, one world | `repeated_world` | `test_one_world_across_three_scenes_fails_repeated_world` |
| `review.json` verdict `revise` | `hook`, `coherence` | `test_a_revise_verdict_fails_the_hook_and_coherence_checks` |
| a scene whose `segment` is not in the script | `segment_mapping` | `test_a_storyboard_scene_without_a_script_segment_fails_mapping` |
| no rendered `character` id | `character_consistency` | `test_character_consistency_requires_a_rendered_actor` |
| an unknown character id | `character_consistency` | `test_an_unknown_character_id_fails_consistency` |
| one scene taking 90 % of the narration | `pacing` | `test_pacing_fails_when_one_scene_dominates_the_timeline` |
| a prior job with the same worlds and shots | `repetition` | `test_repetition_fails_above_0_8_jaccard_against_history` |
| provider answers `passed` with `frames_inspected: 0` | `visual` → `failed` | `tests/test_vision_agent.py::test_a_pass_that_inspected_nothing_is_rejected` |
| provider answer ignores the sheet (wrong count) | `visual` → `failed` | `test_a_pass_that_claims_more_frames_than_were_extracted_is_rejected` |
| `blocker` or `major` finding | `visual` → `failed` | `test_a_blocker_finding_fails_the_pass` |
| no vision provider configured | `visual` → `skipped_no_vision_provider` | `test_no_vision_provider_is_a_skip_with_a_real_extracted_count` |
| `camera.move` without a target | `SceneSpec` validation | `tests/test_contracts_scene.py` |
| a mock job | `publishable: false` | `tests/test_api_approval_gate.py::test_a_mock_job_is_still_never_publishable` |
| stale `readiness.json` hash | `readiness_bound` | `test_a_readiness_artifact_bound_to_a_different_hash_blocks` |

Two rules that the table encodes:

1. **A detector that did not run is a failure.** The standalone `scripts/verify_video.py` reports
   it as WARN, which is honest for a human reading a terminal; the pipeline treats an unmeasured
   file as unproven. `verify_video.py` also parses real event markers (`black_start:`,
   `freeze_start:`, `silence_start:`) rather than the filter's own banner, because `name in log`
   matched every invocation.
2. **A skip is not a pass.** `skipped_no_vision_provider` reaches `READY_FOR_APPROVAL` — it is
   visible and non-passing — while `failed` blocks it. The contract refuses a skip that names a
   provider or claims inspected frames.

## 6. Running

```bash
uv run pytest -q                       # python suite
uv run pytest -q -k "not slow"         # fast loop
npm --prefix apps/dashboard run test   # vitest
npm --prefix apps/dashboard run test:e2e
npm --prefix packages/video run test:adapter        # product storyboard -> donor contract
npm --prefix packages/video run test:render-props   # props resolution in calculateMetadata
npm --prefix packages/video run still-smoke -- <abs-output-dir>   # 7 stills, needs a browser
npm --prefix packages/video run still-templates -- <abs-output-dir>  # camera-reach stills x2 per template, needs a browser
uv run python scripts/verify_video.py <job_id>       # media gate; --json for a machine gate
uv run python scripts/scan_secrets.py                # secrets gate; 0 findings required
uv run python scripts/export_schemas.py --check      # schema gate; no diff required
```

Both gate scripts are exit-code contracts, and both are proven in `tests/test_gate_scripts.py`
with a clean run and a planted defect:

| Command | 0 | 1 | 2 |
| --- | --- | --- | --- |
| `scan_secrets.py [path]` | no credential-shaped string | at least one finding, printed as `path:line: pattern-name` | the path does not exist |
| `export_schemas.py --check` | committed schemas are exactly what the models produce | any difference: `stale`, `missing`, or `orphaned` | the export itself could not run |

**Serial tests.** `tests/test_audio_timing.py` and the two real-SAPI tests in
`tests/test_media_tts.py` shell out to Windows PowerShell SAPI and are marked `serial`. They must not
run concurrently with each other: three concurrent pytest processes make `sapi_tts.ps1` fail with
`NamedParameterNotFound`, because several processes binding the same SAPI COM object are not
isolated. A CI runner that parallelises at process level must map `serial` to a single worker
(`pytest -m serial` runs alone). The marker is distinct from `slow`, which describes duration, not
concurrency. `tests/test_sapi_serial_marker.py` fails if the registration or an annotation is lost.

`scan_secrets.py` scans the working tree, excluding `.venv`, `node_modules`, `data`, `.git` and the
build/cache directories — vendored code and runtime state are not this repository's source, and a
gate that is permanently red is a gate that gets bypassed.

**Two decisions a future maintainer will be tempted to undo.** Both exist because the obvious
version is wrong:

1. **It reports the pattern name, never the matched value.** A scanner that echoes the secret into
   CI logs has moved the leak, not found it. `test_the_matched_value_is_never_printed` asserts that
   neither the value nor a fragment of it appears in stdout or stderr.
2. **The SENTINEL allowlist is scoped to `tests/test_redact.py` only — not to `tests/`.** That file
   asserts redaction on credential-shaped fixtures, so its values are exempt *there*. Exempting
   `tests/` would hide a real key committed next to a fixture, which is exactly the mistake this
   gate exists to catch. The exemption is a path plus a value, not a directory.

The secondary renderer's suites (all need Node, `chrome-headless-shell` and ffmpeg; they skip with a
stated reason when a tool is missing, never pass silently):

```bash
uv run pytest tests/test_bang_motion.py -q          # document emitter + CDP capture; 7 of 35 are `slow`
uv run pytest tests/test_renderer_dispatch.py -q    # payload -> renderer, unknown value refused
uv run pytest tests/test_renderer_parity.py -q      # both renderers, one props file, one gate
uv run pytest tests/test_renderer_parity.py -q -m slow -s   # same, and prints the measured PSNR
```

`test_bang_motion.py` and `test_renderer_parity.py` drive a real browser and are marked `slow`
(registered in `pyproject.toml`); `uv run pytest -q -k "not slow"` skips them and leaves the pure
emitter, dispatch and mux logic covered. `test_renderer_parity.py` prints
`[parity] cross-renderer mean PSNR …` and does not assert it — see the Media caveat above.

`scripts/verify_video.py` resolves the job directory from `Settings.from_env()`, so
`SHORTS_DATA_DIR` / `SHORTS_JOBS_DIR` work exactly as they do for the API. Its exit codes are the
contract: **0** every hard check passed, **1** at least one hard check failed, **2** the job
directory or `output.mp4` does not exist. A check it cannot perform (no `color_range` tag, no
`render.json` to compare frames against, a detector that failed to run) is printed as `WARN` and
does not fail the gate; a check that fails is printed as `FAIL` with the observed value.

A real render proof (a job with `render_video: true`) needs `packages/video/node_modules` plus the
Remotion headless browser, so it is a manual verification, not part of the default pytest suite.

Three consecutive green runs are required before a phase gate is declared passed. One flake is a
failure, quarantined with a written cause.

### E2E harness contract

`apps/dashboard/playwright.config.ts` owns both servers: the API on `127.0.0.1:8019` with
`SHORTS_DATA_DIR`, `SHORTS_DB_PATH`, `SHORTS_JOBS_DIR`, `SHORTS_SECRETS_DIR` and
`SHORTS_STUDIO_CONFIG` all under `data/e2e/` (deleted when the API starts), and the dashboard on
`3018` with `STUDIO_API_ORIGIN=http://127.0.0.1:8019`. `data/e2e/` and `test-results/` are
gitignored. `SHORTS_MOCK_DELAY_MS` (default `0`, digits only; anything else raises `ValueError`)
slows the mock transport so a test can observe a running job; it does not change provider
resolution and never makes mock reachable for a live job. The studio assertion compares each
rendered `data-state` against the persisted snapshot, not the DOM alone.

The spec also proves the 2D path is genuinely mounted rather than merely present: it waits for a
zone heading (`Ruang Direktur`) that only `StudioFallback` emits, since `StudioScene` is a canvas
and renders no DOM headings. Character parity is then checked per agent by reading `data-agent`
and comparing its `data-state` to `characterState` of the same snapshot agent.
