# Production web app startup gate

Every production app release must be opened in a fresh real browser before the
live domain changes and again after it changes. HTTP 200 and Vercel Ready do not
prove that SvelteKit started. This includes CLI uploads, Git builds and hotfixes.

Keep **Auto-assign Custom Production Domains** disabled for the existing
`open-mates-webapp` project. Production builds remain staged at their immutable
Vercel URL. CLI builds must use `vercel --prod --skip-domain`.

After the release's existing backend compatibility gates, run:

```bash
python3 scripts/promote_production_webapp.py \
  --deployment <immutable-deployment-id> \
  --expected-version <exact-version-from-the-reviewed-build> \
  --out test-results/production-webapp/<unique-release-id>
```

The helper refuses automatic domain assignment, requires a Ready production
deployment in the existing app project, checks its startup, then assigns only
`app.openmates.org`. It repeats the browser check on that domain. Failed startup
blocks promotion; a failed live check restores the previous deployment unless
another operator has already changed the alias. Each check uses fresh desktop
and phone contexts, checks the exact version, loads and reloads the app, opens
the login dialog and checks the editable email input. Console errors and
unhandled exceptions fail the check. No login, signup, payment or AI request is
submitted. Receipts, screenshots and actual browser recordings stay in the
private evidence directory. Review the captures before reporting completion.

Before promotion the fresh browser serves actual public files fetched from the
immutable deployment at the production browser origin. This keeps production
API CORS checks intact without changing public traffic or mocking the API. The
receipt records both the deployed source URL and browser origin. The check after
promotion uses the real public domain directly, without request interception.

For a read-only verification or emergency restoration check:

```bash
python3 scripts/verify_production_webapp.py \
  --url https://app.openmates.org \
  --expected-version <exact-version> \
  --out test-results/production-webapp/<unique-check-id>
```

Install Playwright/browser dependencies through the existing tooling. A host
with a compatible existing browser can set `PLAYWRIGHT_CHROMIUM_EXECUTABLE`.
Keep records for failed checks and report the failure; do not substitute a build
status or bypass the gate. Ordinary application E2E continues to use isolated CI.

The `Production web app startup` GitHub workflow also checks successful Git-backed
Vercel production deployment events and supports explicit read-only dispatches.
It checks the immutable URL against the event's commit SHA. This monitor does
not replace staged promotion: CLI uploads may have no GitHub deployment event,
and a post-build check cannot stop an automatically assigned live domain.
