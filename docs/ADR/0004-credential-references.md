# ADR-0004 — Credentials are references, never values

**Status:** accepted

## Decision
A provider stores `credential: {"env": "NAME"}` or `{"dpapi": "id"}`. Values are resolved at call
time. DPAPI (`CryptProtectData`, current-user) seals local secrets into `data/secrets/*.bin` with
a DACL restricted to the user; implemented with `ctypes`, no third-party dependency.

## Origin binding
A credential is bound to `(scheme, host, port)`. Editing `base_url` to another origin withholds
the credential and sets `credential_origin_mismatch: true`.

## Why
"Editable base URL + server-side key" is an exfiltration primitive. The donor shipped that shape
and had to patch it (`config._resolve_key`). This ADR makes it structural.

## Consequences
Rotating a key means editing `.env` or re-sealing; there is no UI that displays a key, so there is
no UI that can leak one.
