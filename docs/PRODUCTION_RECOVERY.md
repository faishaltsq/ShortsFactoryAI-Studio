# Production recovery

Acceptance recovery is an explicit operator action. It neither approves a video nor changes
9router's configuration, cooldowns, model locks or databases. Router incidents must be resolved
through the router's supported operator interface; then resume this application's job.

## Inspect without retrying

```bash
uv run python scripts/run_production_acceptance.py --job-id JOB_ID --list-uncertain
```

Inspect the provider's supported request/billing history when available. An unknown outcome is
not proof that a request was free or rejected. Keep the original journal row. Do not clear it,
mark it completed without a response, change request inputs merely to evade its key, or run an
acknowledgement loop.

## Authorize one possibly chargeable retry

Only after deciding that a duplicate charge is acceptable:

```bash
uv run python scripts/run_production_acceptance.py --job-id JOB_ID --authorize-retry --request-key REQUEST_KEY --attempt 1 --by operator --reason "Provider could not reconcile the request; duplicate cost accepted" --confirm-duplicate-cost
```

The named request must belong to that job and the supplied attempt must be its latest uncertain
attempt. Authorization is written through the existing request journal and is consumed by one
atomic claim. This command **does not execute inference**. Repeating authorization is refused by
the journal, not interpreted as another grant. A later uncertain attempt needs a new decision.

## Resume through the application pipeline

```bash
uv run python scripts/run_production_acceptance.py --job-id JOB_ID --resume --by operator --reason "Endpoint recovered; resume from validated artifacts"
```

One invocation calls the existing `run_job` once under a token-owned lease. Its existing artifact
validation, state-machine transitions, bounded repairs and request replay remain authoritative.
No `FAILED`/`BLOCKED` state is manually moved to QC. Missing recovery evidence stops execution;
restore valid evidence or use the application's explicit rework workflow instead of jumping
stages. A remaining unknown provider outcome stops again, without granting authorization.

The command exits successfully only when the job reaches `READY_FOR_APPROVAL`; human approval
is still required. Publishing, already approved and terminal jobs cannot be run by this helper.

## Audit and failure behavior

Every mutation requires a non-empty operator and reason. Lease-fenced `recovery-actions.json`
records intent before execution/authorization and a result afterward, with UTC timestamps and
redacted text. Invalid audit history blocks further recovery instead of resetting the log. An
interruption after intent is evidence of an incomplete operation, not evidence of success:
inspect the journal and job state before deciding what to do next. The journal remains the source
of truth for retry permission. Acquiring another worker's lease fails before any recovery write.

`--help` and invalid/missing action arguments do not construct the application runtime. The
inspection command exposes only request identifiers and provider/model metadata, not request
payloads, provider response bodies or credentials.

## Regression proof

`tests/test_production_recovery.py` exercises isolated real journals and job stores, including
unknown outcomes, explicit cost confirmation, cross-job authorization refusal, single-use retry
claims, preserved uncertain rows, no inference on authorization, failure-state preservation and
argument validation before runtime construction. `tests/test_request_journal.py` retains the
paid-call replay, atomic authorization and duplicate-prevention tests; `tests/test_runner.py`
retains state-machine and artifact validation coverage.
