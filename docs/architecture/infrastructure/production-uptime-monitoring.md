# Production uptime monitoring

The external status VPS observes public HTTP endpoints, synthetic journeys,
provider status feeds and production integration summaries. The dev host runs
the GitHub-hosted browser and CLI smoke schedules, polls production Brevo
outcomes in the production OpenObserve logs, checks public TLS, and cross-checks
the status page. Smoke outcomes describe the specific journeys they exercised.
Prometheus infrastructure diagnostics, deploy verification and backup job
notices are independent of these uptime probes.

Both monitors retain one open incident per observed service in SQLite. A
failed sample opens a record. Two consecutive real failures and fresh
evidence at or beyond ten minutes are required for the first 🚨. The default
reminders are thirty minutes after that message and hourly thereafter.
The monitor waits three minutes after recovery before closing the incident,
so a failure during that interval merges into the same incident. It sends one
✅ only when a down notice was delivered. Missed probes are checker
diagnostics. Observed durations are bounded by each check's cadence.

The policy is configurable through `UPTIME_FIRST_ALERT_SECONDS` (minimum
600), `UPTIME_FIRST_REMINDER_SECONDS` (default 1800) and
`UPTIME_REPEAT_SECONDS` (default 3600). The host does its lightweight checks
every five minutes and retries active smoke suites at that cadence when an
earlier run has finished. GitHub dispatch and runner failures are retried once
per scheduled run. Cached integration states count as consecutive failures
only after the originating probe has had time to refresh.

The dev host database is `logs/uptime/incidents.sqlite3`. On the VPS it is
`uptime.sqlite3` inside the agent state volume. The records retain start,
end, duration, check and error. Checker failures have their own history.
The daily briefing adds the last 24 hours of closed short blips across both
hosts. Only aggregate counts and durations leave the external monitor on the
public status JSON.

## Rollout

The dev branch publishes the code and a status image. Roll out to live
monitoring only after owner authorization. First confirm the dev host's
read-only production log query shows production Brevo account probes and send
outcomes, and that the configured webhooks point to the production ops channel.
Install the managed schedule from `scripts/test_schedule_setup.py` and set
`OPENMATES_PROD_UPTIME_ENABLED=1` on the dev host to switch the existing
production cron and the status cross-check to the new policy. Deploy the
approved image on the external status server. Delegate backend integration
transition notices with the existing
`OPENMATES_HEALTH_ALERTS_DELEGATED=true` setting after the external monitor is
healthy. Schedule the cutover when there is no active legacy outage so the
next recovery is paired with a notice from the same monitor.

The production Brevo account checks use production's Vault key in the backend
and their observed results are read from OpenObserve. The dev host needs its
own configured admin-debug credential for this read. `BREVO_API_KEY` on dev
is optional and only adds statistics diagnostics. A timeout or missing key
in that secondary poll does not page for email.
