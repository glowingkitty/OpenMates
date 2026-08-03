# Dev smoke suite (hourly)

Tiny, fast smoke suite that runs hourly on the **dev server** to catch urgent
regressions in signup/payments/chat within an hour instead of waiting for the
3 AM nightly full run.

Sibling to `tests/prod-smoke/` (which runs the same idea against the live
production server). Both suites are dispatched from the dev server's local
crontab via `scripts/tests.py run --hourly-dev` / `--hourly-prod` — **never**
from the GitHub Actions `schedule:` cron, which we found to silently skip runs
under load (see OPE-349).

## What runs hourly on dev (08–18 UTC)

| Spec | Lives in | Why |
| --- | --- | --- |
| `dev-smoke/dev-smoke-reachability.spec.ts` | this dir | Cheap pre-flight: root + login + signup pages render. Fails fast if dev is down. |
| `settings-buy-credits-stripe-managed.spec.ts` | `tests/` | Login → buy credits via Stripe (test card). Catches Stripe + checkout regressions. |
| `signup-flow-stripe-managed.spec.ts` | `tests/` | Cold-boot signup → managed Stripe checkout. Catches signup + payment regressions. |
| `chat-flow.spec.ts` | `tests/` | Login → send message → AI reply → cleanup. Catches end-to-end chat breakage. |

The list is hard-coded in `scripts/run_tests.py` (`CORE_JOURNEY_SPECS`) and also
drives `.github/workflows/release-core-journeys.yml`. Keep it
**short** — every spec adds ~2-5 min to the hourly wall time. Anything that is
not "core user flow that must keep working" belongs in the nightly run, not here.

## Required env vars

These must already be present in `/home/superdev/projects/OpenMates/.env` on
the dev server. The hourly cron sources `.env` before running.

- `PLAYWRIGHT_TEST_BASE_URL` — dev base URL (e.g. `https://app.dev.openmates.org`)
- `OPENMATES_TEST_ACCOUNT_*_EMAIL/PASSWORD/OTP_KEY` — used by chat-flow + Stripe specs
- `MAILOSAUR_API_KEY`, `MAILOSAUR_SERVER_ID`, `SIGNUP_TEST_EMAIL_DOMAINS` — used by managed Stripe signup
- `DISCORD_WEBHOOK_DEV_SMOKE` — failure notifications (post-on-failure only; silence = healthy)

## On failure

`scripts/tests.py run --hourly-dev` posts a red embed to the Discord webhook
specified by `DISCORD_WEBHOOK_DEV_SMOKE`. Successful runs post **nothing** —
intentional, because hourly green pings would flood the channel. A single
"all good" heartbeat is posted once per UTC day (first successful run of the
day) so we can tell the pipeline itself isn't dead.

## Manual operation

```bash
# Force a one-off run (ignores any commit gate, posts to Discord regardless)
python3 scripts/tests.py run --hourly-dev --force

# Just verify Discord wiring without dispatching specs
python3 scripts/tests.py run --hourly-dev --dry-run-notify
```

Results are archived to `test-results/hourly-dev/run-<UTC-timestamp>.json`
(rotated to last 7 days).

## Release gate

The same four specs form the advisory dev-to-main release gate. Before a manual
bootstrap run or promotion PR, prepare the Docker-backed dev services and publish
their exact-commit status:

```bash
python3 scripts/prepare_release_candidate.py --session <SESSION_ID> --expected-commit <FULL_SHA>
gh workflow run release-core-journeys.yml --ref dev -f checkout_ref=<FULL_SHA>
```

The first promotion that introduces the workflow to `main` must use the manual
dispatch because GitHub only loads `pull_request` workflows already present on
the base branch. Later dev-to-main PRs run it automatically. The aggregate check
remains advisory until repeated green runs justify a separate main-only ruleset.
