# Vendored fonts

These woff2 files are vendored so Remotion rendering is fully offline and deterministic
(see ADR 0014). All three families are licensed under the SIL Open Font License, Version 1.1;
the full license text is included per family next to the files.

| Family | Files | Role | License |
| --- | --- | --- | --- |
| Fraunces | `Fraunces-Regular.woff2`, `Fraunces-SemiBold.woff2`, `Fraunces-SemiBoldItalic.woff2` | display serif | `LICENSE-Fraunces.txt` (Copyright 2018 The Fraunces Project Authors) |
| Manrope | `Manrope-Regular.woff2`, `Manrope-Medium.woff2`, `Manrope-SemiBold.woff2`, `Manrope-Bold.woff2`, `Manrope-ExtraBold.woff2` | body / captions | `LICENSE-Manrope.txt` (Copyright 2018 The Manrope Project Authors) |
| IBM Plex Mono | `IBMPlexMono-Regular.woff2`, `IBMPlexMono-Medium.woff2`, `IBMPlexMono-SemiBold.woff2` | numbers / technical labels | `LICENSE-IBMPlexMono.txt` (Copyright 2017 IBM Corp.) |

Latin subsets only. `src/fonts.ts` loads them via `@remotion/fonts`; no runtime network fetch.
