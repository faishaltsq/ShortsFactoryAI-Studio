<#
.SYNOPSIS
    Every gate that defines "done" in AGENTS.md §2, in one command.

.DESCRIPTION
    Runs each gate, prints a PASS/FAIL line per gate, and exits non-zero if any failed. It does not
    stop at the first failure: a broken lint and a broken suite are both worth seeing in one run.

    The Python type gate is real: mypy runs strict over packages/core via [tool.mypy] in
    pyproject.toml. A clean run only means the declared modules typed-check; behavior is pytest's
    job, not this gate's.

    Parameters:
      -Quick   skip the suites that need a browser (video still-smoke, dashboard E2E)
      -Json    emit one JSON object instead of the human table

.EXAMPLE
    pwsh -File scripts/check.ps1
    pwsh -File scripts/check.ps1 -Quick
#>
[CmdletBinding()]
param(
    [switch]$Quick,
    [switch]$Json
)

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
# With -Json, stdout must carry the document and nothing else, so every progress line goes to
# stderr. [Console]::Error is used directly: a redirection operator on Write-Host is scoped to the
# statement and, inside a branch, swallowed the JSON that followed it.
function Write-Human { param([string]$Text, [string]$Color = 'Gray')
    $old = [Console]::ForegroundColor
    try { [Console]::ForegroundColor = $Color; [Console]::Error.WriteLine($Text) }
    finally { [Console]::ForegroundColor = $old }
}

Push-Location $root
$results = [System.Collections.Generic.List[object]]::new()

function Invoke-Gate {
    param(
        [string]$Name,
        [string]$Command,
        [scriptblock]$Action,
        [string]$Skip = ''
    )

    if ($Skip) {
        $results.Add([pscustomobject]@{ Gate = $Name; Status = 'SKIPPED'; Detail = $Skip })
        Write-Human ("SKIP  {0,-24} {1}" -f $Name, $Skip) DarkGray
        return
    }

    Write-Human ("....  {0,-24} {1}" -f $Name, $Command) DarkGray
    # Reset first: a stale $LASTEXITCODE from an earlier gate would make this one look green.
    $global:LASTEXITCODE = 0
    $output = & $Action 2>&1
    $code = $LASTEXITCODE
    if ($null -eq $code) { $code = 0 }
    $tail = ($output | Select-Object -Last 1)
    if ($code -eq 0) {
        $results.Add([pscustomobject]@{ Gate = $Name; Status = 'PASS'; Detail = "$tail" })
        Write-Human ("PASS  {0,-24} {1}" -f $Name, $tail) Green
    }
    else {
        $results.Add([pscustomobject]@{ Gate = $Name; Status = 'FAIL'; Detail = "$tail"; Output = ($output -join "`n") })
        Write-Human ("FAIL  {0,-24} exit {1}: {2}" -f $Name, $code, $tail) Red
    }
}

Invoke-Gate -Name 'ruff' -Command 'uv run ruff check .' -Action { uv run ruff check . }
Invoke-Gate -Name 'pytest' -Command 'uv run pytest -q' -Action { uv run pytest -q }
Invoke-Gate -Name 'dash-typecheck' -Command 'npm --prefix apps/dashboard run typecheck' -Action {
    npm --prefix apps/dashboard run typecheck
}
Invoke-Gate -Name 'dash-test' -Command 'npm --prefix apps/dashboard run test' -Action {
    npm --prefix apps/dashboard run test
}
Invoke-Gate -Name 'schemas' -Command 'uv run python scripts/export_schemas.py --check' -Action {
    uv run python scripts/export_schemas.py --check
}
Invoke-Gate -Name 'secrets' -Command 'uv run python scripts/scan_secrets.py' -Action {
    uv run python scripts/scan_secrets.py
}
Invoke-Gate -Name 'video-typecheck' -Command 'npm --prefix packages/video run typecheck' -Action {
    npm --prefix packages/video run typecheck
}
Invoke-Gate -Name 'video-adapter' -Command 'npm --prefix packages/video run test:adapter' -Action {
    npm --prefix packages/video run test:adapter
}
Invoke-Gate -Name 'video-beats' -Command 'npm --prefix packages/video run test:motion-beats' -Action {
    npm --prefix packages/video run test:motion-beats
}
$browserSkip = if ($Quick) { 'skipped by -Quick: needs a browser' } else { '' }
Invoke-Gate -Name 'still-smoke' -Command 'npm --prefix packages/video run still-smoke' -Skip $browserSkip -Action {
    $out = Join-Path ([System.IO.Path]::GetTempPath()) ("shorts-stills-" + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $out -Force | Out-Null
    npm --prefix packages/video run still-smoke -- $out
}
Invoke-Gate -Name 'e2e' -Command 'npm --prefix apps/dashboard run test:e2e' -Skip $browserSkip -Action {
    npm --prefix apps/dashboard run test:e2e
}

Invoke-Gate -Name 'mypy' -Command 'uv run mypy packages/core --strict'

$failed = @($results | Where-Object { $_.Status -eq 'FAIL' })
$skipped = @($results | Where-Object { $_.Status -eq 'SKIPPED' })
Pop-Location

if ($Json) {
    # stdout carries the document only; every progress line above went to stderr.
    ConvertTo-Json -InputObject @($results) -Depth 4
}
else {
    $passed = @($results | Where-Object { $_.Status -eq 'PASS' }).Count
    Write-Human ''
    Write-Human ("{0} passed, {1} failed, {2} skipped" -f $passed, $failed.Count, $skipped.Count)
}

if ($failed.Count -gt 0) { exit 1 }
exit 0
