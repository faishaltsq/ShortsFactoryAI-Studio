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
| edge-tts | 7.3.1 | LGPL-3.0 | Used as a library, not modified. Network required (Microsoft Edge TTS endpoint). Not usable offline. |
| GSAP | ≥3.12.5 | Standard licence | **Free for commercial use** since 3.13 (Webflow relicensed, 2025). Vendored locally, not CDN. |
| bang-motion | 1.19.0 (`c1aa65e`) | MIT © 2026 Bang Tutorial | Design law and frame-export technique reused with attribution; CDN references rewritten to local vendored copies. |
| Chrome for Testing (`chrome-headless-shell`) | 157.0.8080.0 | BSD-3 (Chromium) | Already present under `packages/video/node_modules/.remotion/`; used for motion-skill frame capture. No extra download. |

## Fonts

Bundled with the video package (SIL OFL / Apache-2.0 per family). No runtime fetch: a fetched font
makes a render non-reproducible and breaks offline operation.

## Explicitly not used

- No paid image or video generation service.
- No cloud render farm.
- No telemetry or analytics SDK.
