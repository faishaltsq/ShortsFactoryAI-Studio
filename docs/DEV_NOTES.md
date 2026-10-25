# DEV_NOTES — host-specific traps that cost hours

Collected from the donor tree and the environment audit. Each one produced a failure that looked
like a code bug.

## Node / npm

- **`NODE_ENV=production` is exported in this shell.** A bare `npm install` therefore prunes every
  devDependency (vitest, typescript, tailwind) and silently breaks `test` and `typecheck`. Always
  `npm install --include=dev --no-audit --no-fund`.
- **Never pipe a node/python command into `tail`/`head`** on this host: it dies with
  `stdin is not a tty`. Run bare, redirect from `/dev/null`, read the whole output.

## Remotion

- Always pass an explicit `--port`. The preview server defaults to 3000, which collides with the
  dashboard. On Windows, a bind can "succeed" on a port another process already answers through a
  wildcard listener; Remotion then serves a bundle Chrome cannot reach and the failure reads as
  `window.getStaticCompositions is undefined`. A port that accepts a TCP connect is **not** free —
  probe with connect + `SO_EXCLUSIVEADDRUSE` bind.
- `--props` must be an **absolute** path. A relative path fails silently as an empty render.
- After `npm run build`, an already-running `next start` keeps serving the previous build's CSS
  chunks. Verify a CSS change by fetching the page, resolving the `_next/static/chunks/*.css` href
  and grepping it for the new rule; kill and restart the server if it is absent.

## Paths (MSYS vs native)

- `terminal` runs bash, but native tools (git, node, python, rg) do **not** get MSYS path
  translation. `git -C /c/Users/x` fails; use `C:/Users/x`. `cd /c/Users/x` works because `cd` is a
  shell builtin.
- For a native tool that must read a scratch file, use `$TMPDIR` (Hermes scratch) or
  `$LOCALAPPDATA/Temp`, never a bare `/tmp`.

## SQLite

- WAL is required for the API thread and the worker thread to coexist. Without `busy_timeout` a
  concurrent read during a write throws `database is locked` under load, not under test.

## Next.js dev

- Next serves `/_next/hmr` only to the host it printed. Opening `127.0.0.1:3000` when the server
  logged `localhost` kills the HMR socket, React never mounts, and the page sits on its loading text
  forever with **zero** API calls. That looks like a backend bug and is not one.

## PowerShell / cmd

- `taskkill /PID <pid> /T /F` — the MSYS `//PID` form is rejected; `cmd //c "taskkill ..."` can
  print the cmd banner and kill nothing. Use
  `powershell -NoProfile -Command "Stop-Process -Id N -Force"`.
- `wmic process where ... get CommandLine` prints an empty block on Windows 11 (removed). An empty
  `wmic` result is a dead tool, not a dead process. Use `Get-CimInstance Win32_Process`.

## Patch safety

- A patch tool can report success while writing a literal `***` over real code (a `|` mangled by
  sanitisation). After every patch: `grep -n '\*\*\*' <file>` and, for Python,
  `python -c "import ast;ast.parse(open(p,encoding='utf-8').read())"`. A compiled artifact is not
  proof — a stale `.pyc` keeps the old behaviour alive.

## GPU

- 6 GB VRAM. Remotion's Chrome, the 3D studio and the dashboard share it. Render concurrency stays
  at 1, and the studio pauses while a render is active with < 1 GB free.
