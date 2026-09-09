# Daily dev-host CLI signup email health

The existing 03:00 dev-server cron invokes `scripts/run-tests-daily.sh`.
It runs the bounded local `signup_email_live_smoke.py --dev-host` health check,
then dispatches ordinary isolated GitHub tests even when local health fails.
The real Brevo check never runs in GitHub. The former GitHub live workflow was
explicitly disabled and removed after the user clarified this boundary.
Its previous run is not acceptable proof of the requested architecture.

The probe requires hostname `dev-server` and rejects `GITHUB_ACTIONS`. It uses
only the global installed `openmates` CLI against the explicit dev API target.
The installed CLI supports an absolute `OPENMATES_STATE_DIR`; each attempt uses
a temporary directory and a subprocess environment without personal API keys,
profiles or signup-code shortcuts. It supplies a random throwaway password
through the supported environment input, waits for `Email verification code:`,
then terminates the CLI without providing a code. This acknowledges the signup
request only, not email sending. No registration is completed. The temporary
state is removed; the global personal engineering login is untouched.

The existing first-party signup route is sessionless, Origin restricted and
limited to five requests/minute. CLI supplies the normal normalized address,
hash and invite-gate fields. No new route or product behavior is introduced.
The email worker, template and Brevo path remain the deployed dev services.
No credits are spent. Alias-specific cache keys expire naturally after 20 minutes;
no Redis lookup is counted as sending or delivery evidence. No account or inbox
messages are deleted, and the Gmail client is read-only.

Local configuration uses the established `run_tests.py` environment helper:
`GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`, and
`GMAIL_TEST_ADDRESS`. Configure these securely on the dev host with readonly
access to the existing dedicated inbox. The invite code can use
`E2E_SIGNUP_INVITE_CODE` or `SIGNUP_TEST_INVITE_CODE` when needed. Existing local
`BREVO_API_KEY` may support optional read-only event observation; do not copy
credentials from GitHub or add a new provider credential requirement.
Missing or invalid local inbox access prevents signup execution entirely.

One UTC-day alias and exclusive local receipt prevent duplicate requests. The
receipt is reserved before starting the CLI, and network/CLI errors never resend.
The prior 2026-09-09 attempt also has a local reservation; do not delete it to
retry. `--observe-since <unix-timestamp>` only reads the same alias's existing
mail/events and never starts signup or changes the send reservation.

The redacted local report at `logs/nightly-reports/signup-email-live-smoke.json`
keeps queue acknowledgement, optional Brevo acceptance, and actual inbox arrival
separate. Exact recipient and freshness checks must match the existing English
signup subject `Your code: {six digits}`; the heading inside the email is not its
subject. Codes, addresses, bodies, provider receipts and tokens are never logged.
A matching email received within 120 seconds proves delivery even without
independent Brevo events. Provider acceptance alone cannot pass. Read-only later
observation checks the original arrival timestamp against the original deadline.
CLI submission is bounded to 30 seconds; HTTP calls have ten-second timeouts;
the outer daily invocation has a 240-second cap. Failures remain visible and do
not suppress isolated daily CI. No extra notification sending is introduced.

Local tooling checks: `python3 -m unittest discover -s scripts/tests -p test_signup_email_live_smoke.py`.
Actual proof must be a dev-host installed-CLI attempt with controlled inbox
arrival. No browser, GitHub live email job, or video is part of this health layer.
