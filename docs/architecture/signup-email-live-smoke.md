# Daily live-dev signup email health

The user-authorized live-service layer runs at 03:15 UTC through
`signup-email-live-smoke.yml`, alongside the existing 03:00 isolated daily tests.
It is not isolated product coverage and does not replace the CI coordinator.
GitHub runs the bounded Python probe directly against the deployed dev API;
there is no existing GitHub SSH transport to reuse. Credentials stay in the
ephemeral runner environment. No global OpenMates CLI state is accessed.

The existing first-party signup preflight is sessionless, Origin restricted,
and limited to five requests/minute. The probe sends one plaintext dedicated
inbox alias and its base64 SHA-256 hash, with the existing invite gate. It never
submits a confirmation code or creates an account. No credits are spent.
The worker's two alias-specific cache keys expire naturally after 20 minutes;
Gmail is read-only and no unrelated messages, cache keys or accounts are deleted.

Repository secrets: `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`,
`GMAIL_REFRESH_TOKEN`, `GMAIL_TEST_ADDRESS`, `E2E_SIGNUP_INVITE_CODE` when required,
and `BREVO_API_KEY` for independent transactional event observation. The latter
must correspond to the deployed worker's provider account. Missing provider
event credentials do not suppress independent inbox observation, but cannot
produce an overall pass. Missing/invalid Gmail read access prevents sending.

The workflow serializes executions, reserves the UTC day in Actions cache before
the live request, and refuses automatic/manual reruns that day. The script also
uses an exclusive receipt before submission; a network failure is never retried
as another signup request. Actions cache is a best-effort duplicate guard and
can be evicted/deleted; operators must not delete the daily reservation to retry.
The alias is deterministic per UTC day so evidence remains correlated.

Reports contain queue acknowledgement, a fresh exact-recipient Brevo `requests`
event with a message ID, and independent Gmail arrival with matching recipient,
timestamp and confirmation-template subject. Gmail metadata avoids reading
bodies/codes. Subject matching demonstrates the confirmation email kind, not
full rendered-body quality. Redis retrieval is never sending/delivery evidence.
The poll budget is 120 seconds with bounded HTTP calls and a six-minute job cap.
Provider acceptance with inbox timeout is a failure, as is inbox arrival without
provider observation. Provider `delivered` events are not inbox observation.

The redacted JSON report is retained seven days as a GitHub artifact and copied
to the job summary. Actions failure notifications use repository subscriptions;
no additional email notification integration is claimed. Reports bind the probe
source SHA, but do not attest the separately deployed live API's commit.

Local tooling validation: `python3 -m unittest discover -s scripts/tests -p test_signup_email_live_smoke.py`.
Actual health validation: dispatch `signup-email-live-smoke.yml` on `dev` once,
then inspect its redacted report. No browser or video is required.
