# Test orchestration

New full-application testing uses one GitHub-hosted VM per browser spec. Each job
owns a disposable Docker backend/database stack, fresh accounts and a
runner-private localhost web process built from the exact source.
`ci_coordinator.py` splits multi-spec E2E submissions into separate jobs and owns
the durable queue, concurrency and GitHub polling budget; `ci_dispatch.py` selects
immutable source and supported coverage. Runtime admission and cutover readiness
remain enforced. Unsupported coverage is not a pass and must not fall back to
deploying or mutating the shared dev stack.

Prepare a source with `sessions.py ci-source`; dirty candidate bytes move through
a private expiring patch artifact, never a Git branch. Submit the matching supported
mode/spec, then use `ci_coordinator.py wait <id>`. Waiting reads the cache and
validates exact-source result artifacts once when a workflow succeeds. Status,
submission and result commands default to concise text; `--json` retains complete
programmatic receipts. Timeout, attention, cancellation and failure return a
non-success exit status.

Deployment is not test setup. Vercel readiness and `app.dev.openmates.org`
visual smoke happen only after isolated E2E when the accepted task requires a
deployed-dev check. Transient container-registry network failures receive bounded
stack-start retries; application health failures remain immediate failures.

`tests.py` retains historical test inventory, triage and explicitly requested
campaign records in the private engineering control plane. It is not a mandatory
second workflow for routine feature/fix work. Campaign worker identity uses the
Claude Code session (`CLAUDE_CODE_SESSION_ID`; legacy Codex variables as fallback);
no editor title polling, automatic chat spawning or idle-chat checkpointing is
part of the supported path. Keep history and ownership checks when inspecting old
campaigns. The installed OpenMates CLI owns engineering Task progress.

Update relevant E2E coverage for behavior changes and run focused local checks.
Preserve source/run identity and test assertions. Reassess after two unsuccessful
attempts on the same blocker and ask before unrelated infrastructure repair or
uncertain scope changes. Reuse existing logs/traces/screenshots/videos. Additional
edited/captioned proof-video production follows the accepted scope. Delivery of
selected existing web/component and CLI E2E recordings is required: retrieve the
source-bound artifact and link only the latest successful recording per requested
check/flow across retries/reruns, or its latest available failed recording if that
request never succeeded. Include distinct required views; omit duplicates and
superseded attempts, with no appendix of all recording links. Successful
`wait` downloads artifacts automatically; failed/cancelled runs with a run ID
need `ci_coordinator.py result <id>`. Concise result output exposes `directory`
and `ci_evidence_command`; run that command for selected runs and choose final
links from its media inventory under the rule above. Report missing capture,
expired artifacts or upload failures for selected evidence explicitly.
Retry uploads from retained artifacts without rerunning passing tests. See
`.claude/rules/testing.md` for waivers, privacy and delivery acknowledgements.

`scripts/ci_evidence.py` keeps the per-run inventory in `ci-evidence.json` next
to `receipt.json` (receipts and inventories written before the rename use
`codex_evidence_command` and `codex-evidence.json`; both are still read). Each
record is immutable per source commit, run, spec, attempt and profile. Uploads
reuse the private, expiring response-media S3 transport; a confirmed upload
removes only the local video, and later inventory passes reuse that record
instead of reporting a missing capture. Expiring links are renewed from the
saved bucket/key while S3 retains the object; an expired object is reported as
evidence expiry, never re-uploaded or rerun. `--ack` requires an actual
delivered chat message ID; Claude Code exposes none, so delivery stays pending
and disk cleanup retains such run directories.

Sources: `scripts/ci_coordinator.py`, `scripts/ci_results.py`,
`.github/workflows/isolated-tests.yml`, `.claude/rules/testing.md`.
