# Scheduling the daily ingestion

Without this, the hazard data only updates when somebody remembers to run a
command — and the freshness endpoint honestly reports it going stale while
nothing does anything about it.

Everything here runs `--catch-up`, which asks *what days are we missing*
rather than blindly fetching yesterday. A machine that was off for a week
recovers that week on its next run instead of leaving a permanent hole. See
`app/services/ingestion/schedule.py` for which days get retried.

After ingesting, the same run matches new damage reports to roads and
re-scores `current_accessibility` from the newest report (`docs/decisions/0010`).
The scorer refuses a report more than three days old and exits non-zero, so
a portal outage shows up as a failed run instead of a map quietly showing
last week's forecast as today's.

## Where it has to run: India

The ASDMA portal answers from India in under a second and does not answer
GitHub's (or most cloud providers') US machines at all. So the daily job runs
on a machine in India -- this one -- and writes to whichever database it is
pointed at. When the PC is off, nothing is lost: the next run's catch-up
fetches every day it missed (up to 14).

### Point it at the deployed database (once)

In PowerShell, with the Neon **pooled** connection string:

```powershell
[Environment]::SetEnvironmentVariable("SETUNER_DATABASE_URL", "<neon pooled url>", "User")
```

This stores it in your Windows user profile -- not in the repo, not in a
script. The task picks it up; logs say `target: deployed database` without
printing it. To go back to the local database, remove it:

```powershell
[Environment]::SetEnvironmentVariable("SETUNER_DATABASE_URL", $null, "User")
```

### Rainfall login (once)

The job also fetches daily rainfall from NASA (`docs/decisions/0014`), which
needs a free Earthdata account: register at
https://urs.earthdata.nasa.gov/users/new, then in the profile under
Applications → Authorized Apps approve **NASA GESDISC DATA ARCHIVE** (without
this the server refuses even a correct password). Then:

```powershell
[Environment]::SetEnvironmentVariable("EARTHDATA_USERNAME", "<username>", "User")
$p = Read-Host "Earthdata password" -AsSecureString; [Environment]::SetEnvironmentVariable("EARTHDATA_PASSWORD", [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($p)), "User"); Remove-Variable p
```

The second line keeps the password off the screen and out of PowerShell's
history. `run_ingestion.ps1` loads both itself and logs only whether they
were found. Check the login works with
`python -m app.services.weather.check` from `apps/api`.

NASA's daily file for day D appears around 20:00 IST on D+1, so the 07:30
run always finds yesterday's rain missing and fetches it the next morning.
That is expected, and it is why the model lags rain by one day.

## Windows (this machine)

Register the task once, as the user who owns the database:

```powershell
$Repo = "C:\Users\Mohit\OneDrive\Desktop\sih26002-scaffold\setuner"
$Action = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Repo\scripts\scheduling\run_ingestion.ps1`""
$Trigger = New-ScheduledTaskTrigger -Daily -At 7:30am
$Settings = New-ScheduledTaskSettingsSet `
  -StartWhenAvailable `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -MultipleInstances IgnoreNew `
  -ExecutionTimeLimit (New-TimeSpan -Hours 1)
Register-ScheduledTask -TaskName "SetuNER daily hazard ingestion" `
  -Action $Action -Trigger $Trigger -Settings $Settings
```

The settings matter more than the schedule:

- **`-StartWhenAvailable`** runs a missed trigger once the machine is back.
  Without it, a laptop that was asleep at 07:30 simply skips that day.
- **`-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries`** override
  Windows' defaults, which on a laptop silently skip the run when unplugged
  and kill it if the charger is pulled mid-run. The run is a few minutes of
  network I/O; battery is not a reason to lose a day. An existing task can be
  changed in place:
  `Set-ScheduledTask -TaskName "SetuNER daily hazard ingestion" -Settings $Settings`
- **`-MultipleInstances IgnoreNew`** stops a slow catch-up from overlapping
  the next day's run. Ingestion is idempotent so an overlap would not corrupt
  anything, but two runs hitting a government portal at once defeats the
  crawl delay.
- **`-ExecutionTimeLimit`** kills a hung run rather than leaving it holding
  a `running` row forever. Catch-up marks such a day as still owed, so the
  next run picks it up.

**07:30 is chosen, not arbitrary.** The report quotes the CWC bulletin
issued at 8 AM IST and is compiled from district submissions through the
day, so the run targets *yesterday*, which is settled by then.

Check it:

```powershell
Get-ScheduledTask -TaskName "SetuNER daily hazard ingestion" | Get-ScheduledTaskInfo
```

Logs land in `logs/ingestion-YYYY-MM.log`.

## Linux / cron

```cron
30 7 * * * cd /srv/setuner/apps/api && /usr/bin/python3 -m app.services.ingestion.run --hazard flood --catch-up >> /var/log/setuner-ingestion.log 2>&1
35 7 * * * cd /srv/setuner/apps/api && /usr/bin/python3 -m app.services.ingestion.run --hazard landslide --catch-up >> /var/log/setuner-ingestion.log 2>&1
```

Five minutes apart rather than chained, so a slow flood run does not delay
the landslide one — and never in parallel, for the crawl-delay reason above.

## Docker

`docker-compose.yml` defines an `ingestion` service. It is in the
`scheduling` profile, so a normal `docker compose up` does not start it:

```bash
docker compose --profile scheduling up -d ingestion
```

It loops with a sleep rather than using cron, which keeps the container
single-purpose and its logs in the usual place.

## Verifying it is actually working

Ask the API rather than the scheduler — the scheduler only knows whether a
process exited, not whether data arrived:

```bash
curl http://localhost:8000/api/v1/hazards/freshness
```

`status` should be `fresh`. Anything else, check `recent_runs` in the same
response for the failure, then the log file.

## What this does not do

There is no alerting. A run that fails is recorded in `ingest_runs` and
visible in `/hazards/freshness`, but nothing pages anybody. For a tool meant
to be used during a disaster that is a real gap, and the gap-analysis
(`0001` section 5) already names alerting as missing. Wiring the freshness
status to a webhook is the obvious next step and is not built.
