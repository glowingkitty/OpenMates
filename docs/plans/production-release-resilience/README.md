# Production release resilience proposal

The deployment runbook now requires the stable CLI to be upgraded before a
server update and pins templates and images to the same release. That addresses
deployment drift, but it should become an enforced CLI preflight rather than
depend only on an operator following the runbook.

The [Plan](plan.yml) distinguishes safeguards already shipped from proposed
implementation. OpenMates Tasks owns execution status; future implementation
needs a selected, approved scope.

## Recommended order

1. **Enforce release compatibility before changing a server.** Bind supported
   CLI versions, templates, images and configured satellite roles to one release
   manifest. Fetch and validate templates during dry run. Preserve a known-good
   rollback bundle across all stages.
2. **Fix upload routing reconciliation.** Support its explicit production/dev
   routing profile and scoped Caddy matchers. Preserve Origin gates and trusted
   environment headers. Never replace that layout with a generic self-host
   template or mislabel the upload VM as a core cloud installation.
3. **Require critical user journeys.** Verify authenticated session authority,
   encrypted WebSocket sync, recording/upload/transcription, workflow saving,
   guest app answers and quota behavior. Natural-language focus activation uses
   an authenticated test account under the existing contract.
4. **Reconcile and prove alert delivery.** Treat Alertmanager delivery, CLI
   operational reports and independent fallback delivery as separate paths.
   Check target ports, real delivery receipts and recovery notifications. Use
   accessible monitoring links instead of internal container URLs.
5. **Reduce update and background-work impact.** Avoid redundant setup while
   preserving migrations, move storage reconciliation out of each task, and
   bound retry/queue growth. Audit generated state-file ownership.
6. **Repair release-gate debt.** Missing evidence must remain visible. Emergency
   exceptions should be narrow and expire; a healthy endpoint does not replace
   an authenticated or audio journey test.

## Already delivered

- Stable CLI-first deployment, immutable templates and effective CMS cache checks.
- A guarded update path that reuses setup only with exact target and healthy
  infrastructure proof, rechecked immediately before application replacement.
- Renewable scoped upload credentials and image dependency/import checks.
- Provider recovery without repeating tools, preserved guest results on quota
  exhaustion, and reconnect/workflow-state fixes.
- Last-good ranking protection, refresh deduplication and worker metrics-port fixes.
- Installer-owned private health receipts and focused regression coverage.

## Decisions and verification still needed

The operator should select the next implementation scope and an independent
alert fallback. A received Discord critical alert proves that path works; it
does not prove every CLI reporting path or fallback works. A fresh authenticated
recording confirmation remains separate from the successful isolated upload
service test. Guest quota and focus-availability changes are separate product
decisions.

Private incident details and runtime receipts are retained outside public release
notes. The proposal links focused CI evidence and does not claim that all broad
release gates passed.
