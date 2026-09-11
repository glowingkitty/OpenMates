# Test orchestration

New full-application testing uses isolated GitHub Actions Docker and web runtimes.
`ci_coordinator.py` owns the durable queue, concurrency and GitHub polling budget;
`ci_dispatch.py` selects immutable source and supported coverage. Runtime admission
and cutover readiness remain enforced. Unsupported coverage is not a pass and
must not fall back to mutating the shared dev stack.

Prepare a source with `sessions.py ci-source`, submit the matching supported
mode/spec, then use `ci_coordinator.py wait <id>`. Waiting reads the cache and
validates exact-source result artifacts once when a workflow succeeds. Status,
submission and result commands default to concise text; `--json` retains complete
programmatic receipts. Timeout, attention, cancellation and failure return a
non-success exit status.

`tests.py` retains historical test inventory, triage and explicitly requested
campaign records in the private engineering control plane. It is not a mandatory
second workflow for routine feature/fix work. Campaign worker identity uses Codex;
no editor title polling, automatic chat spawning or idle-chat checkpointing is
part of the supported path. Keep history and ownership checks when inspecting old
campaigns. The installed OpenMates CLI owns engineering Task progress.

Update relevant E2E coverage for behavior changes and run focused local checks.
Preserve source/run identity and test assertions. Reassess after two unsuccessful
attempts on the same blocker and ask before unrelated infrastructure repair or
uncertain scope changes. Reuse existing logs/traces/screenshots/videos. Additional
proof-video production is required only by the accepted scope.

Sources: `scripts/ci_coordinator.py`, `scripts/ci_results.py`,
`.github/workflows/isolated-tests.yml`, `.claude/rules/testing.md`.
