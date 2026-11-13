# Browse: production enablement

Status: prepared, not applied. Browse stays disabled in production until the
owner picks the release that carries the switch below.

## The switch

Production reads `backend/config/backend_config.yml`. Browse is off there
through two feature overrides:

```yaml
feature_overrides:
  disabled:
    # Browse is still in development; search and public page reading remain enabled.
    - "skill:web:browse"
    - "embed:web:browse"
```

Enabling Browse removes exactly these two entries (and the comment). Nothing
else changes: the dev override file already leaves Browse on, the skill, embed,
routes, billing and safety code are the same on both servers. Rollback is the
reverse change, or an admin override `skill:web:browse` in the same list, plus
an api / app-ai-worker restart.

Remove `embed:web:browse` together with the skill: with the skill on and the
embed off, saved Browse cards could not render.

## Production prerequisites (before the switch ships)

1. **Template.** Build a fresh template from the release commit with
   `backend/scripts/build_web_browse_template.py --execute --name <versioned alias>`
   in the production api container (it copies `web_browse_runtime.py` from that
   container, so the runtime matches the release). Run
   `backend/scripts/test_web_browse_runtime.py` against it. The runtime protocol
   stays `preboot-v2`, so the dev template and the production template are
   interchangeable with the same backend.
2. **Environment** on production:
   - `E2B_BROWSE_TEMPLATE=<new template id>`
   - `E2B_BROWSE_PREBOOTED=true` (the builder publishes a prebooted template)
   - `E2B_BROWSE_POOL_SIZE=0` for the first week. Pooled browsers are paused
     VMs that are paid for by the platform; enable a small pool only after
     real usage shows start time matters.
3. **Secrets.** The E2B API key already used by code execution must be in
   production Vault; Browse reads it through the same helper.
4. **Text helper models.** Planner, extraction and quote review use the
   existing text-helper route; no new provider, so no privacy policy change.

Without the template variable a Browse start fails with "The E2B browser
template has not been configured" and charges nothing. That is a failure, not a
safe off state, which is why the feature override, not a missing template, is
the switch.

## One real production smoke run

After the release with the switch is live and the environment is set:

1. Owner account only, one new chat, model left on automatic routing.
2. Prompt: "Use web.browse to open https://httpbin.org/html and return the
   exact main heading and source URL as JSON." (public test page, no shop, no
   sign-in, no personal data).
3. Pass when all of these hold:
   - the chat shows the Browse card, it reaches *Completed*, and the reply
     contains `Herman Melville - Moby-Dick` with the source URL;
   - opening the card shows the live viewer, then *Close browser* closes it;
   - the usage ledger for that chat shows one Browse entry and one assistant
     entry, together under 30 credits, with no pending accounting;
   - the E2B dashboard (production scope) shows no running sandbox five
     minutes after close.
4. Fail on anything else: disable again with the override above, restart, and
   keep the chat for diagnosis. Do not retry with other sites on production.

## Cost check

Rates (from `backend/apps/web/app.yml` and the billing record in
`measurements.md`): compute is billed per elapsed resource second at
0.092 credits/second (5.52 credits per minute; 1 credit = $0.001), paused time
costs nothing, and internal model calls are billed at twice their supplier
tariff. Supplier compute is $0.000046/second for the 2-vCPU, 4-GiB template.

Per-run guards (defaults in `backend/apps/web/skills/browse_skill.py`): at most
40 steps, 180 seconds and 250 credits ($0.25) per run; a run stops at its
credit cap.

Measured on dev (real runs, this feature):

| Flow | Credits |
|------|---------|
| Public page to JSON | 5 to 19 |
| Missing fact (truthful stop) | 0 |
| Own site, partial results | 35 to 47 |
| Product catalogue, two pages | 72 to 83 |
| Shop listing with prices (run 10) | 39 |
| Longest observed multi-run chat | 138 |

Platform exposure: each credit charged covers twice its supplier cost, so the
platform carries no loss on billed runs. Costs not passed to users are the
blank pool (zero while `E2B_BROWSE_POOL_SIZE=0`) and template builds (one per
release that changes the runtime). A run that fails before the browser starts
charges nothing.
