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
# WHICH DATABASE
# By default, whatever apps/api/.env says (the local database). To keep the
# DEPLOYED database current -- the reason this runs on a machine in India at
# all, since the ASDMA portal does not answer from abroad -- set a user
# environment variable once:
#
#   [Environment]::SetEnvironmentVariable("SETUNER_DATABASE_URL", "<neon pooled url>", "User")
#
# It lives in your Windows user profile, never in the repo or a script. Log
# lines never print it.
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

# Target the deployed database when configured (see WHICH DATABASE above).
# Environment variables override apps/api/.env, so nothing on disk changes.
$Target = [Environment]::GetEnvironmentVariable("SETUNER_DATABASE_URL", "User")
if ($Target) {
    $env:DATABASE_URL = $Target
    Write-Log "target: deployed database (SETUNER_DATABASE_URL)"
} else {
    Write-Log "target: local database (apps/api/.env)"
}

# Rainfall comes from NASA and needs a free Earthdata login (see
# app/services/weather/imerg.py). Loaded from the user profile explicitly
# rather than trusting the scheduler to pass it through; never logged.
foreach ($Name in "EARTHDATA_USERNAME", "EARTHDATA_PASSWORD") {
    $Value = [Environment]::GetEnvironmentVariable($Name, "User")
    if ($Value) { Set-Item -Path "Env:$Name" -Value $Value }
}
if ($env:EARTHDATA_USERNAME -and $env:EARTHDATA_PASSWORD) {
    Write-Log "rainfall: Earthdata login found"
} else {
    Write-Log "rainfall: EARTHDATA_USERNAME / EARTHDATA_PASSWORD not set -- rainfall step will fail"
}

if (-not (Test-Path $ApiDir)) {
    Write-Log "ERROR: expected the API at $ApiDir and it is not there."
    exit 1
}

Push-Location $ApiDir
try {
    # One entrypoint for every scheduler (app/jobs/daily.py): flood and
    # landslide catch-up, damage matching, then scoring. It exits non-zero if
    # any step failed, including the scorer refusing a stale report.
    #
    # Output is logged line by line as it arrives, not collected and written
    # at the end: a run killed halfway (laptop shut, window closed) used to
    # leave only "starting" in the log, with no trace of how far it got.
    # -u keeps Python from buffering it. Stop would turn any stderr line into
    # a terminating error in Windows PowerShell, so it is relaxed here only.
    Write-Log "running app.jobs.daily"
    $ErrorActionPreference = "Continue"
    & python -u -m app.jobs.daily 2>&1 | ForEach-Object { Write-Log "  $_" }
    $code = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
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
