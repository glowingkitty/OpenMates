# Example-chat failures and notification gap — 2026-09-10

Status: investigation in progress; notification contract drafted, implementation not started.

## Established findings

The September 8 candidate records show multiple distinct technical failures producing `chat.an_error_occured`, including tasks whose envelope reported completed. Candidate retries exposed successive compatibility failures rather than establishing a successful end-to-end run.

- Astra catalog configured unsupported `max`; `a8162d625` changed it to `xhigh`.
- The local adapter then rejected `xhigh`; `f42e33579` updated validation.
- Reasoning with tools subsequently failed on Chat Completions; `de40ae665` added the stateless Responses adapter.
- Responses lifecycle/tool progress was discarded, causing false inactivity timeouts; `9767f60af` forwards actual progress.
- Missing preprocessing output did not activate fallback; `2418c1bf4` repaired recovery and sealed simple errors.
- Sequential attempts consumed the entire preprocessing budget; `c203154e1` reserves time for remaining configured providers.
- Consent and embed-save completion recovery received further changes in `fe098001a`.

Sources: `docs/plans/landing-example-quality-campaign/evidence/example-astra-worker.md`, `docs/plans/preprocessing-failure-recovery/plan.yml`, and the cited commit diffs. The recent shared CLI recovery Codex task was interrupted with uncommitted investigation work; its status is not proof of resolution.

## Current verification

On source `36750c21a`, focused pytest across preprocessing retries, OpenAI Responses, and stream-consumer recovery produced **52 passed, 1 failed**. The failure is `test_sub_chat_parent_continuation_does_not_inherit_recovery_identity`. It expects cleared inference identity, while source preserves it. This line changed in `565162b78` during assistant-speech work and the request model explicitly describes reuse for internal continuation. Resolve that contract/test conflict before changing either side. This result alone does not establish a fresh production bug.

The earlier plan explicitly records pending runtime/integration verification and excluded this same failure. Therefore reliable deployed resolution is not yet established.

`debug.py trace errors --last 24h` inside the API container failed with name-resolution failure reaching OpenObserve. Its subsequent “No trace data found” is not a healthy result. Session context also reports disconnected production logs; no production health conclusion is justified.

## Notification design

Extend the approved operational-monitoring bundle, rather than adopting the wider draft AI-observability bundle. The latter specifies Discord-first email fallback, which does not satisfy independent chat-failure email. Existing weekly error digests are not prompt per-failure notifications.

Proposed behavior: official dev/prod only, configured admin email, five per server per UTC day, atomic shared allowance and duplicate suppression, technical terminal failures including error-as-completed, no private content or identifiers, explicit transport/queue/limiter outcomes, no recursive alerts. No new REST endpoint or client changes are proposed; this is internal backend processing.

## Remaining work

1. Resolve recovery test semantics and inspect current deployed code plus bounded failure evidence.
2. Run source-bound isolated CI for actual request/provider and recovery paths; unit success cannot substitute for integration evidence.
3. Obtain exact-PDF approval of the notification contract, implement through existing email/edition utilities, and exercise concurrency, restart/day rollover, self-host exclusion, privacy, and transport failures.
4. Verify actual dev email delivery; prepare production rollout separately for explicit production approval.

## Approved implementation follow-up

The user approved notification specification fingerprint `5809705a199bfc279eb33393031b83ced565689134dd983fce569a6fb60e9e5c`, requested implementation/deploy, and waived E2E on September 10. The recovery test conflict was resolved as stale test semantics: internal continuation must preserve the original durable inference identity while obtaining a new execution identity. The updated test verifies both and calls the request's actual identity resolver; no recovery product code was changed.

Focused notification, preprocessing, Responses, and recovery suites now pass all 70 checks. Alert tests execute the actual Lua reservation script in isolated fakeredis, including concurrent requests and day/environment isolation. This is unit evidence only. Deployed chat reliability and actual mail delivery remain unverified under the E2E waiver.
