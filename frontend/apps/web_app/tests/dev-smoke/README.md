# Dev smoke suite (hourly)

Tiny, fast smoke suite that runs hourly on the **dev server** to catch urgent
regressions in signup/payments/chat within an hour instead of waiting for the
3 AM nightly full run.

Sibling to `tests/prod-smoke/` (which runs the same idea against the live
production server). Both suites are dispatched from the dev server's local
crontab via `scripts/run_tests.py --hourly-dev` / `--hourly-prod` — **never**
from the GitHub Actions `schedule:` cron, which we found to silently skip runs
under load (see OPE-349).

## What runs hourly on dev (08–18 UTC)

| Spec | Lives in | Why |
| --- | --- | --- |
| `dev-smoke/dev-smoke-reachability.spec.ts` | this dir | Cheap pre-flight: root + login + signup pages render. Fails fast if dev is down. |
| `settings-buy-credits-stripe.spec.ts` | `tests/` | Login → buy credits via Stripe (test card). Catches Stripe + checkout regressions. |
| `signup-flow-polar.spec.ts` | `tests/` | Cold-boot signup → Polar checkout. Catches Polar + signup regressions. |
| `chat-flow.spec.ts` | `tests/` | Login → send message → AI reply → cleanup. Catches end-to-end chat breakage. |

The list is hard-coded in `scripts/run_tests.py` (`HOURLY_DEV_SPECS`). Keep it
**short** — every spec adds ~2-5 min to the hourly wall time. Anything that is
not "core user flow that must keep working" belongs in the nightly run, not here.

## Required env vars

These must already be present in `/home/superdev/projects/OpenMates/.env` on
the dev server. The hourly cron sources `.env` before running.

- `PLAYWRIGHT_TEST_BASE_URL` — dev base URL (e.g. `https://app.dev.openmates.org`)
- `OPENMATES_TEST_ACCOUNT_*_EMAIL/PASSWORD/OTP_KEY` — used by chat-flow + Stripe specs
- `MAILOSAUR_API_KEY`, `MAILOSAUR_SERVER_ID`, `SIGNUP_TEST_EMAIL_DOMAINS` — used by Polar signup
- `DISCORD_WEBHOOK_DEV_SMOKE` — failure notifications (post-on-failure only; silence = healthy)

## On failure

`scripts/run_tests.py --hourly-dev` posts a red embed to the Discord webhook
specified by `DISCORD_WEBHOOK_DEV_SMOKE`. Successful runs post **nothing** —
intentional, because hourly green pings would flood the channel. A single
"all good" heartbeat is posted once per UTC day (first successful run of the
day) so we can tell the pipeline itself isn't dead.

## Manual operation

```bash
# Force a one-off run (ignores any commit gate, posts to Discord regardless)
python3 scripts/run_tests.py --hourly-dev --force

# Just verify Discord wiring without dispatching specs
python3 scripts/run_tests.py --hourly-dev --dry-run-notify
```

Results are archived to `test-results/hourly-dev/run-<UTC-timestamp>.json`
(rotated to last 7 days).
