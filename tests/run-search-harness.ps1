<#
Run the direct Search UI harness and keep an inspectable result report.

The Python suite contains assertions for every case. This wrapper also fails if
the suite exits non-zero or does not emit its explicit 20-test success marker.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot 'build_venv\Scripts\python.exe'
$harness = Join-Path $PSScriptRoot 'search_ui_harness.py'
$resultsDirectory = Join-Path $projectRoot 'test-results'
$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$report = Join-Path $resultsDirectory "search-harness-$timestamp.txt"
$latest = Join-Path $resultsDirectory 'search-harness-latest.txt'

if (-not (Test-Path -LiteralPath $python)) {
    throw "Python environment not found: $python"
}
New-Item -ItemType Directory -Force -Path $resultsDirectory | Out-Null

$env:QT_QPA_PLATFORM = 'offscreen'
"Search UI Harness Report`nStarted: $(Get-Date -Format o)`n" | Set-Content -LiteralPath $report -Encoding utf8
& $python $harness *>> $report
$exitCode = $LASTEXITCODE
$content = Get-Content -LiteralPath $report -Raw
$passed = $exitCode -eq 0 -and $content -match 'SEARCH_UI_HARNESS_OK tests_run=20'
$status = if ($passed) { 'PASS' } else { 'FAIL' }
"`nRESULT: $status`nExit code: $exitCode`nReport: $report" | Add-Content -LiteralPath $report -Encoding utf8
Copy-Item -LiteralPath $report -Destination $latest -Force
Get-Content -LiteralPath $report

if (-not $passed) {
    Write-Error "Search UI harness failed. See $report"
    exit 1
}
exit 0
