---
issue_id: 6e0933d1-c968-499f-8e21-cc602c164525
env: prod
status: open
title: "keinen code bekommen"
reported_at: 2026-06-20T12:59:04Z
github: []
linear: []
cluster_key: title:keinen-code-bekommen
resolved_by: []
verified_by: []
---

# keinen code bekommen

## Summary

The user attempted signup and reached the confirm-email code screen, but the
submitted email matched an existing account. Production returned the generic
anti-enumeration success response and did not create a verification code or
enqueue a signup verification email. The later confirm-code attempts failed
because there was no code in cache for that email.

## Symptoms

- User reported `keinen code bekommen` (`did not receive a code`) at
  `2026-06-20T12:59:04Z`.
- The S3 issue report action history shows the user submitted signup around
  `2026-06-20T12:54:24Z`, landed on the 6-digit code input, then interacted
  with resend/text links before reporting the issue.
- Client console logged `ConfirmEmail` retrying because the code was not in
  cache.

## First Anomaly

- `2026-06-20T12:54:25Z`: production API logged
  `Signup email-code request matched an existing email; returning generic response`.
- No `Submitting email verification task to Celery` log appears near the signup
  attempt. The nearest verification-email enqueue logs in the inspected window
  were unrelated earlier successful requests.

## Root Cause Hypothesis

High confidence: this is not a Brevo/email-provider delivery failure. The signup
address was already registered, so `request_confirm_email_code` intentionally
returned generic success for enumeration hardening and skipped the verification
email Celery task. The frontend still advanced the user into a state that implies
a code was sent, leaving them waiting for an email that the backend never queued.

Relevant source path: `backend/core/api/app/routes/auth_routes/auth_email.py`.
Lines `146-151` return generic success for existing emails without queuing
`generate_and_send_verification_email`; lines `231-240` later reject confirm-code
checks when no cache entry exists.

## Related Reports

- Cluster key: `title:keinen-code-bekommen`
- Related URL: `none`

## Related Commits

- `59f63f60d fix: harden auth enumeration responses` touched the generic
  response behavior in `auth_email.py`.

## Attempts

- `python3 scripts/issues.py show 6e0933d1-c968-499f-8e21-cc602c164525 --env prod`
- `python3 scripts/issues.py findings 6e0933d1-c968-499f-8e21-cc602c164525 --env prod`
- `python3 scripts/issues.py timeline 6e0933d1-c968-499f-8e21-cc602c164525 --env prod`
- `docker exec api python /app/backend/scripts/debug.py issue 6e0933d1-c968-499f-8e21-cc602c164525 --production`
- Queried production logs for existing-email signup matches, no-code verify
  attempts, and verification-email enqueue/task lifecycle records.

## Tests Run

Investigation only; no product code changed and no tests run.

## Current Status

Root cause identified. Open remediation: preserve anti-enumeration guarantees
while changing the signup UX so users are not stranded on the code screen when
the backend returned generic success for an already-registered email.

## Next Step

Add or update a signup flow test for an already-registered email, then adjust
the UX to show a generic account/help state with a clear login path instead of
implying a verification code was sent.
