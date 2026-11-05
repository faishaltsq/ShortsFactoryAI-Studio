# Rendered-pixel semantic visual QA (V3-E)

## Ownership and evidence flow

The existing editorial stage extracts PNGs from the job's actual MP4, calls the existing vision resolver through `RecordingProvider` and the durable V3-D request journal, and commits the frames, `visual-evidence.json`, and `qc.json` through the normal stage transaction. No second transport, renderer, generic scene template, automatic approval, or paid repair path is introduced.

`packages/core/contracts/semantic.py` owns the typed evidence contracts. `media/qc.py` owns decoding and sample provenance. `agents/vision.py` owns interpretation of uploaded pixels. `orchestration/editorial.py::evaluate_job_readiness()` is the shared, read-only current-evidence check used by readiness and API approval/publishing. The API service owns explicit operator decisions and lease protection.

## Four separate decisions

| Axis | Meaning |
| --- | --- |
| `technical_ready` | Technical QC passed against the current inputs and the actual render checksum matches. |
| `semantic_status` | `PASS`, `FAIL`, or `UNVERIFIED` for the inspected semantic criteria. |
| `manual_review_eligible` | Technical/creative/checksum gates pass and either semantic evidence passes or a current explicit policy permits review of an unverified result. |
| Human approval | A separate operator action records `approval.json` and requests the existing validated state transition. Readiness and review permission never approve a job. |

Default behavior is fail-closed. A legacy `visual.status = passed`, matching extraction/inspection counters, missing semantic evidence, a cached readiness boolean, or a missing vision provider cannot establish semantic PASS. A semantic FAIL cannot be waived. Manual review permission never changes UNVERIFIED into PASS, never makes a mock job publishable, and never authorizes a model retry.

## Frame evidence

`visual-evidence.json` binds job ID, MP4 SHA-256, input fingerprint, and a separate semantic-context fingerprint. Each frame records its scene, absolute frame index/timestamp, roles, PNG filename/digest, `rendered_mp4` source, and a reference to its scene requirement. Requirements contain the available scene-bound narration, storyboard/visual beats, and audio/subtitle context. These are expectations, not proof of visible objects.

Sampling covers beginning/middle/end, quarter-action moments, declared motion beats (`atFrame` and neighboring frames), and both sides of scene transitions. Actual decoded frames are unique and timeline-ordered; shared roles do not imply separate images. The semantic path has no legacy six-frame contact-sheet cap. Short or insufficient causal coverage remains unverified. Invalid timing, media/probe mismatch, missing/changed render bytes, decoder failure, or missing output frames yields incomplete evidence rather than fabricated observations.

The manifest records `inspection_status`, provider/model when available, and `inspection_ref = qc.json#semantic`. Its immutable `evidence_payload()`/`evidence_hash()` excludes wall-clock `created_at` and the interpretation receipt. Regenerating the same evidence or adding the receipt therefore does not create a second logical model request. Ordered image digests and effective provider settings remain part of V3-D request identity.

## Interpretation and actionable findings

Every scene has exactly one criterion for each of:

1. `subject_fidelity`
2. `causal_fidelity`
3. `narration_alignment`
4. `spatial_continuity`
5. `composition`
6. `scientific_accuracy`
7. `typography_branding`
8. `visual_repetition`

Criteria record status, reason, observation, actual frame references, and declared model confidence. Confidence is not a calibrated probability or independent validation. Inspected conclusions require scene-local frame evidence and declared confidence of at least 0.75. Unknown references, malformed/incomplete coverage, insufficient evidence, or a provider error produce UNVERIFIED without an automatic repair completion. A causal PASS additionally requires distinct sampled states with beginning/middle/end/action roles. Narration alignment cannot pass without scene-bound narration.

A FAIL yields structured findings with scene/category, observation/reason, severity, frame IDs and evidence timestamps, likely affected artifact, and `repair_scope`: `storyboard`, `tsx`, or `asset_geometry`. UNVERIFIED uses `repair_scope = none`. V3-E defines this repair input; it does not implement V3-C's repair executor or authorize regeneration. B/M/E pixel deltas remain separate motion measurements, never semantic findings.

## Scientific and sampling limits

Current research artifacts contain model-authored source declarations, not independently retrieved source text, content digests and checked quotations. Consequently scientific accuracy is explicitly UNVERIFIED, even if the vision model claims PASS or FAIL. URLs and the model's prior knowledge do not certify science. Overall semantic PASS is therefore not currently produced by this inspector: otherwise acceptable jobs require explicit manual review permission. This is deliberate fail-closed behavior, not completed factual verification.

Sampling cannot prove every video frame, resolve all fast motion, establish exact font-file loading, or make a vision model infallible. The brand inspection checks visible Warm Editorial Light consistency; existing renderer/font tests remain separate technical evidence. Unit and wire fixtures prove contracts and integration, not production creativity, real-world model accuracy, or scientific truth.

## Criterion examples

Illustrative schema examples only: these IDs are not production evidence. A complete inspection
must contain all eight categories for every scene and bind references to actual extracted PNGs.

```json
[
  {"scene_id":"example-scene","category":"subject_fidelity","status":"PASS","reason":"Subject is recognizable in the cited sampled states","observation":"The required spindle and workpiece are visually distinguishable","frame_ids":["example-frame-1"],"confidence":0.85},
  {"scene_id":"example-scene","category":"composition","status":"FAIL","reason":"Label obscures the subject at the cited instant","observation":"A title covers the tool/workpiece contact point","frame_ids":["example-frame-2"],"confidence":0.85,"severity":"major","repair_scope":"tsx"},
  {"scene_id":"example-scene","category":"scientific_accuracy","status":"UNVERIFIED","reason":"No independently retrieved source/quote evidence","observation":"Visible interpretation cannot establish factual correctness","frame_ids":[],"confidence":0.0,"repair_scope":"none"}
]
```

## Explicit operator workflow

1. Inspect the actual MP4, frame manifest, per-scene semantic criteria and any blocking technical/creative findings.
2. If semantics are UNVERIFIED and the operator accepts manual review responsibility, send `POST /api/jobs/{job_id}/manual-review-policy` with explicit `operator`, nonblank `reason`, current `render_sha256`, and the JSON boolean `allow_unverified: true` (not a string or number). The service binds current inputs/context itself, holds a lease, records the policy and an audit event, and does not approve or run the job. It refuses a semantic/visual FAIL or a competing worker lease.
3. Resume the normal readiness stage if it was blocked. Review eligibility may now be true while semantic status remains UNVERIFIED and `human_approved` remains false.
4. Make the separate existing approve/reject decision. Approval recomputes current evidence; a named operator is required. Rejection also requires a reason. Publication retains its existing separate approval and private-upload controls.

A changed MP4, storyboard/timing, narration/script, research, visual plan, or audio context invalidates the old permission. Changed/missing PNGs invalidate inspected semantic evidence. A new permission is an explicit operator decision, not an automatic fallback. V3-D uncertain provider outcomes still require explicit operator authorization before any potentially duplicated paid request.

No live production benchmark, account connection, auto-approval, publication, or paid model call is needed to test this milestone.
