#!/usr/bin/env bash
# Every gate that defines "done" in AGENTS.md §2, in one command.
#
# Runs each gate, prints a PASS/FAIL line per gate, and exits non-zero if any failed. It does not
# stop at the first failure: a broken lint and a broken suite are both worth seeing in one run.
#
# The Python type gate is real: mypy runs strict over packages/core via [tool.mypy] in
# pyproject.toml. A clean run only means the declared modules typed-check; behavior is pytest's
# job, not this gate's.
#
#   scripts/check.sh            every gate
#   scripts/check.sh --quick    skip the gates that need a browser
set -uo pipefail

cd "$(dirname "$0")/.." || exit 2

quick=0
[ "${1:-}" = "--quick" ] && quick=1

pass=0
fail=0
skip=0
failed_names=""

gate() {
  local name="$1" cmd="$2" skip_reason="${3:-}"
  if [ -n "$skip_reason" ]; then
    printf 'SKIP  %-18s %s\n' "$name" "$skip_reason" >&2
    skip=$((skip + 1))
    return
  fi
  printf '....  %-18s %s\n' "$name" "$cmd" >&2
  local out code
  out=$(eval "$cmd" 2>&1)
  code=$?
  if [ $code -eq 0 ]; then
    printf 'PASS  %-18s %s\n' "$name" "$(printf '%s' "$out" | tail -1)" >&2
    pass=$((pass + 1))
  else
    printf 'FAIL  %-18s exit %s: %s\n' "$name" "$code" "$(printf '%s' "$out" | tail -1)" >&2
    printf '%s\n' "$out" | tail -20 | sed 's/^/        /' >&2
    fail=$((fail + 1))
    failed_names="$failed_names $name"
  fi
}

gate ruff        "uv run ruff check ."
# Quick mode never runs the real-browser/ffmpeg pytest tier either: it is not phase evidence.
if [ "$quick" -eq 1 ]; then gate pytest "uv run pytest -q -m \"not slow\""
else gate pytest "uv run pytest -q"; fi
gate dash-tsc    "npm --prefix apps/dashboard run typecheck"
gate dash-test   "npm --prefix apps/dashboard run test"
gate schemas     "uv run python scripts/export_schemas.py --check"
gate secrets     "uv run python scripts/scan_secrets.py"
gate video-tsc   "npm --prefix packages/video run typecheck"
gate video-adptr "npm --prefix packages/video run test:adapter"
gate video-beats "npm --prefix packages/video run test:motion-beats"

browser_skip=""
[ "$quick" -eq 1 ] && browser_skip="skipped by --quick: needs a browser"

gate still-smoke 'npm --prefix packages/video run still-smoke -- "$(mktemp -d)"' "$browser_skip"
gate template-stills 'npm --prefix packages/video run still-templates -- "$(mktemp -d)"' "$browser_skip"
gate e2e         "npm --prefix apps/dashboard run test:e2e" "$browser_skip"

gate mypy        "uv run mypy packages/core --strict"

printf '\n%s passed, %s failed, %s skipped\n' "$pass" "$fail" "$skip" >&2
[ "$fail" -gt 0 ] && printf 'failed:%s\n' "$failed_names" >&2
[ "$fail" -gt 0 ] && exit 1
exit 0
