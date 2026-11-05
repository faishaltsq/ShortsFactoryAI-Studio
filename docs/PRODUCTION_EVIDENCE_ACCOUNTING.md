# Production Evidence & Accounting Integrity (V3-D)

## Ownership and request lifecycle

`RecordingProvider` owns the shared text/vision request lifecycle; editorial QC injects the
existing job `RequestJournal`. There is no second journal or execution service.

A vision request identity includes the job, agent/ordinal, task, prompts, effective provider,
transport, origin/model/generation settings and the ordered image SHA-256 digests/media types.
Image bytes and credentials are not stored in that identity's audit payload. Timeout, retry
budget and price changes do not create a new logical request. Existing text request keys remain
compatible.

The journal claims an attempt atomically, reserves the existing budget allowance, and records
`sent` before transport work. Completed results replay locally, including across restart and
when the new-call budget is exhausted. Errors after dispatch retain an uncertain outcome; startup
reconciliation converts interrupted `sent` attempts into `uncertain`. Neither case authorizes a
new billable attempt. The existing explicit, single-use operator authorization remains required.
See `PRODUCTION_RECOVERY.md` for the separate authorization and resume actions.

OpenAI-compatible, Anthropic and Ollama inference POSTs disable HTTP-layer retries, for both text
and vision. Otherwise one journal attempt could hide several charged requests. Read-only health
probes retain their existing retry policy. Anthropic health now uses its existing models GET
path, not a one-token message that would generate unjournaled usage. An older proxy lacking that
endpoint is reported unavailable; it is not tested by generating a paid message.

Completed journal rows retain the served provider/model, timestamps, usage availability, rate
snapshot, estimated cost when available, response text and observed transport latency. Vision
results also retain image digests for audit. A reservation is a budget hold, not billed spend.
Provider invoices are not available and are never invented.

## Usage availability

`Usage.from_provider` distinguishes explicit integer token counts (including real zero) from
absent or malformed counts. Omitted usage is not a zero-cost completion. The usage ledger marks
such calls `usage_unavailable`, while the journal records `reported: false`, null cost and an
unavailable cost source. Historical rows without the new availability field are not retroactively
asserted to have reported usage. No database schema migration or operator-history rewrite is
required.

## Benchmark reports

The existing benchmark runner now:

- validates recorded artifacts against their existing contracts without treating model defaults
  as observations from the source file;
- checks complete B/M/E scene coverage, explicit boolean/status agreement, measured finite deltas
  and consistent static observations; missing or incomplete evidence is `UNVERIFIED`;
- requires actual media checksum and technical/readiness input bindings before a positive overall
  evidence verdict, and separately rejects a known renderer mismatch or forbidden fallback;
- records artifact filenames and SHA-256 values, metric source fields, and the inspected job ID;
- distinguishes recorded metadata, measured invocation time, rate-table estimates and unavailable
  values; verify-existing never invents elapsed production time;
- reports a complete cost estimate only when every journaled attempt has reported usage and a
  recorded estimate; an unresolved/legacy/unpriced attempt makes the total unavailable;
- keeps billed cost unavailable without an invoice source;
- labels storyboard declarations as intent, not rendered semantic verification;
- refuses to upgrade legacy cached `ok`/B/M/E booleans into a verified V3-D verdict.

The CLI uses existing `Settings.from_env` boundaries. It no longer reads another application's
credential configuration or substitutes a hard-coded database location. Resume does not create a
fresh replacement job implicitly.

A report PASS certifies recorded evidence under these checks, not scientific correctness or a
publish recommendation. Semantic visual QA and creative repair remain separate work. No live
production benchmarks were started for this change.

## Verification

Regression coverage is in `tests/test_vision_journal.py` and `tests/test_benchmark_evidence.py`.
Failures were reproduced before fixes: absent vision journal rows; duplicate HTTP POSTs; missing
usage availability; a paid health probe; absent evidence becoming a successful benchmark; null
metrics crashing the report; malformed JSON/structures; and incomplete storyboard coverage.

The affected provider, journal, HTTP, vision-agent/integration and editorial suites pass: **207
tests**. CLI help/dry-run checks pass: **3 tests**. Ruff, strict mypy, schema diff (18 current
schemas) and secret scan pass. Offline standalone proof also observes one transport call/one
usage row for replay, a blocked uncertain restart without a second send, and unavailable values
for an evidence-only inspection with no artifacts. The old V3-A/V3-B frozen full snapshots were
not re-run.

## Integration

V3-A PR #2 was explicitly merged as `5b07fdda60d259f734e5ffbaa5fc01f93a659b67` after reviewing the
recovery diff and verifying that the landing tree equals the already-tested `5cd1767` tree.
There are no hosted checks configured for that PR; prior frozen local regression is the evidence.
V3-B PR #3 was retargeted to master, retaining its tested `7a38ead` head and focused five-file QC
diff. V3-D remains stacked on V3-B. No automatic merge, job approval or publishing is enabled.
