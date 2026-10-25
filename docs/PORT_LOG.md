# PORT_LOG — what came from the donor tree, and at which commit

Donor: `C:\Users\cubeb\OneDrive\Documents\coding\projects\ShortsFactoryAI`
Reference commit at audit: `cb85f1b` (branch `merge/pixel-studio-ui`, 51 uncommitted files).

A module is ported only when (a) it is re-argued against this brief, (b) its donor tests come with
it, and (c) it passes here. "The donor does it this way" is not a justification.

| Module | Donor path | Status | Notes |
| --- | --- | --- | --- |
| Job state allow-list | `packages/core/orchestration/states.py` | to port (P1.5) | Keep the shape; add `PAUSED` and the event-in-same-transaction rule. |
| Job store | `packages/core/orchestration/jobstore.py` (455 L) | to port (P1.5) | Keep `sqlite3`. Add migrations table. |
| Leases | `packages/core/orchestration/leases.py` | to port (P1.5) | Token ownership is correct and hard-won; keep. |
| Netguard CIDR list | `packages/core/research/retrieval.py:35-45` | port (P1.3) | Extracted into `security/netguard.py` and applied to providers, which the donor never did. |
| Provider protocol | `packages/core/providers/base.py` | rewrite (P1.4) | `ResolvedCall` frozen; no mutation. |
| OpenAI-compatible transport | `packages/core/providers/openai_compat.py` | port + fix (P1.4) | Keep the honest error text; add netguard and origin binding. |
| Mock provider | `packages/core/providers/mock.py` | port (P1.4) | Deterministic, seeded. |
| TTS adapter | `packages/core/providers/tts.py` | port (P2.4) | Word boundaries are the basis of subtitle timing. |
| Media probe/validation | `packages/core/media/render.py:20-41` | port (P2.3) | `validate_probe` is good; keep the checks verbatim. |
| Remotion compositions (7) | `packages/video/src/compositions/` | port + extend (P2.2) | Add `camera`/`motion` consumption. |
| Art kit | `packages/video/src/art/` | port (P2.2) | Keep `fit="box"`; the frame-coordinate trap is documented. |
| Character engine | `packages/video/src/character/` | port (P2.2) | One character `maya`: 7 poses, 9 expressions, 7 presets. |
| Storyboard normalisation | `packages/core/storyboard_normalize.py` (850 L) | port (P2.1) | The degradation strategy (keep the text, drop the invented facts) is right. |
| Event store / projection | `packages/core/observability/` | port (P1.6) | Monotonic cursor + replay is correct. |
| Publishing service | `packages/core/publishing/` | port (P4) | The pre-flight vs uncertain classification must come with it; it was a real bug. |
| Pixel office (2D) | `apps/dashboard/src/components/pixel/` | do not port | Replaced by the 3D studio; the 2D fallback is new work with the same state contract. |
| SQLAlchemy / APScheduler deps | `pyproject.toml` | do not port | Declared, never imported. |

## Known donor defects not carried forward

| Defect | Where | Fixed by |
| --- | --- | --- |
| Per-agent override mutates shared provider | `providers/router.py:202-209` | ADR-0003 |
| `base_url` editable with no SSRF check | `studio.py` validator | ADR-0005 |
| No `camera` in `SceneSpec` | `schemas.py:164` | ADR-0009 |
| Two declared, unused dependencies | `pyproject.toml` | ADR-0006 |
| Approval CLI-only in some branches | checkout-dependent | Phase 4 API routes |
