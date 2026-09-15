# Wrapper the Windows Task Scheduler calls once a day.
#
# WHY A WRAPPER AND NOT THE PYTHON COMMAND DIRECTLY
# The scheduler runs with no working directory, no console and no PATH you
# would recognise. Every one of those has to be pinned here, or the task
# "succeeds" daily while never actually having run. It also needs somewhere
# to write output: a scheduled job with nowhere to log is a job nobody can
# debug six weeks later when the history has a hole in it.
#
# WHAT IT RUNS
# --catch-up, not a fixed date. If the machine was off for a week, that week
# is fetched. See app/services/ingestion/schedule.py for which days are
# retried and which are left settled.
#
# Then matches new damage reports to roads and re-scores accessibility.
#
# EXIT CODES
# 0 for success and for "no report published" -- the latter is a normal
# outcome most of the year. Non-zero only for real failures, which is what
# makes Task Scheduler's Last Run Result worth looking at.

$ErrorActionPreference = "Stop"

# Repo root is two levels up from this script, whatever it was invoked as.
$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$ApiDir = Join-Path $RepoRoot "apps\api"
$LogDir = Join-Path $RepoRoot "logs"

if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$LogFile = Join-Path $LogDir ("ingestion-" + (Get-Date -Format "yyyy-MM") + ".log")

function Write-Log($Message) {
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -Path $LogFile -Value $line -Encoding utf8
    Write-Output $line
}

Write-Log "--- ingestion run starting ---"

if (-not (Test-Path $ApiDir)) {
    Write-Log "ERROR: expected the API at $ApiDir and it is not there."
    exit 1
}

Push-Location $ApiDir
try {
    # One entrypoint for every scheduler (app/jobs/daily.py): flood and
    # landslide catch-up, damage matching, then scoring. It exits non-zero if
    # any step failed, including the scorer refusing a stale report.
    Write-Log "running app.jobs.daily"
    $output = & python -m app.jobs.daily 2>&1
    $code = $LASTEXITCODE
    foreach ($line in $output) { Write-Log "  $line" }
    $failed = $code -ne 0
}
finally {
    Pop-Location
}

if ($failed) {
    Write-Log "--- finished WITH FAILURES ---"
    exit 1
}

Write-Log "--- finished ---"
exit 0
