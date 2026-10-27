# THIRD_PARTY — licences and obligations

| Component | Version | Licence | Obligation / note |
| --- | --- | --- | --- |
| Remotion | 4.0.537 | Remotion licence | **Free** for individuals and for-profit orgs with **up to 3 employees**; non-profits also free. Larger orgs need a paid licence. Re-check if headcount grows. |
| React / React DOM | 18.3.1 (video), 19.3.1 (dashboard) | MIT | attribution |
| Next.js | 16.4.2 | MIT | attribution |
| Three.js | 0.186.x | MIT | attribution |
| @react-three/fiber | 9.8.x | MIT | requires React ≥19 <19.4 |
| @react-three/drei | 10.7.x | MIT | requires three ≥0.159 |
| Tailwind CSS | 4.x | MIT | attribution |
| FastAPI / uvicorn | 0.150 / 0.54 | MIT / BSD | attribution |
| Pydantic | 2.14.1 | MIT | attribution |
| Windows SAPI (System.Speech) | OS component | OS licence | Narration runs through the offline `scripts/sapi_tts.ps1` helper: no network, no third-party package. The `edge-tts` dependency was removed because nothing imported it. |
| GSAP | not vendored | Standard licence | **Not vendored, and not needed.** ADR-0012 makes the secondary renderer emit its own document, so no GSAP is shipped, loaded or fetched. The licence note stays for the day someone ingests the upstream starters: free for commercial use since 3.13 (Webflow relicensed, 2025), and if that path is taken GSAP plus the named woff2 subsets must be vendored locally at ingest, never loaded from a CDN at render time. |
| bang-motion | 1.19.0 (`c1aa65e`) | MIT © 2026 Bang Tutorial | **Design reference only, no code shipped.** ADR-0012: the `window.OPENER` interface, the 9:16 layout law and the seek→2×rAF→screenshot technique are reused as knowledge; zero upstream executable lines are copied and no starter HTML is ingested, so there are no CDN references to rewrite. |
| Chrome for Testing (`chrome-headless-shell`) | 157.0.8080.0 | BSD-3 (Chromium) | Already present under `packages/video/node_modules/.remotion/`; used for motion-skill frame capture. No extra download. |

## Fonts

Bundled with the video package (SIL OFL / Apache-2.0 per family). No runtime fetch: a fetched font
makes a render non-reproducible and breaks offline operation.

## Explicitly not used

- No paid image or video generation service.
- No cloud render farm.
- No telemetry or analytics SDK.
