# Export the corridor database for loading into a hosted Postgres.
#
# WHY A DUMP AND NOT A REBUILD
# The road graph, terrain samples, and 313 days of DRIMS history took hours
# of throttled fetching from OSM, Copernicus and the ASDMA portal to build.
# Rebuilding them on a hosting platform would repeat all of that load on
# public services for no gain. The dump is ~50 MB compressed and restores in
# minutes.
#
# WHAT IS LEFT OUT (schema kept, rows not)
#   field_reports, reporters             local test submissions
#   recommendations, recommendation_overrides   local test plans
# Production should start those empty rather than inherit test data that
# would look like real operator activity.
#
# USAGE (from the repo root)
#   .\scripts\deploy\export_data.ps1
#   .\scripts\deploy\export_data.ps1 -Output data\deploy\setuner.dump
#
# Then load it -- see docs/deployment.md, "Load the data".

param(
    [string]$Output = "data\deploy\setuner.dump",
    [string]$PgBin = "C:\Program Files\PostgreSQL\16\bin",
    [string]$DbHost = "localhost",
    [string]$DbName = "sih26002",
    [string]$DbUser = "sih26002"
)

$ErrorActionPreference = "Stop"

$pgDump = Join-Path $PgBin "pg_dump.exe"
if (-not (Test-Path $pgDump)) {
    Write-Error "pg_dump not found at $pgDump. Pass -PgBin with your PostgreSQL bin directory."
    exit 1
}
if (-not $env:PGPASSWORD) {
    Write-Error "Set PGPASSWORD for user $DbUser first (it is not taken as an argument, so it stays out of shell history)."
    exit 1
}

$dir = Split-Path -Parent $Output
if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }

& $pgDump `
    --host $DbHost --username $DbUser --dbname $DbName `
    --format custom --compress 6 `
    --no-owner --no-acl `
    --exclude-table-data field_reports `
    --exclude-table-data reporters `
    --exclude-table-data recommendation_overrides `
    --exclude-table-data recommendations `
    --file $Output

if ($LASTEXITCODE -ne 0) {
    Write-Error "pg_dump failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

$sizeMb = [math]::Round((Get-Item $Output).Length / 1MB, 1)
Write-Output "Wrote $Output ($sizeMb MB). data/ is gitignored; do not commit it."
