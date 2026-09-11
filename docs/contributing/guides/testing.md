# Testing

Maintain relevant E2E coverage for behavior fixes/features, adding a focused case
when missing. Preserve contract/assertion markers. A waiver of test execution
does not waive coverage updates unless explicitly stated by the user.

Run relevant unit, lint and build checks locally. Full product browser, REST,
WebSocket and CLI/SDK E2E run with isolated Docker and web apps in GitHub CI. Use
`sessions.py ci-source` to prepare the source, then `ci_coordinator.py submit`
with the matching supported mode/spec. `ci_coordinator.py wait <id>` waits on the
coordinator cache; `result <id>` retrieves evidence. Use `--json` only for parsers.
Retain source/run identity when reporting a pass. Unsupported coverage or a
queue timeout is not a passing result.

Keep investigation tied to the original acceptance criteria. Inspect the first
useful failure, rerun only after a relevant change or new evidence, and reassess
after two unsuccessful attempts with the same approach. Ask before debugging
unrelated infrastructure, uncertain expected behavior, or a materially expanded
scope. Preserve the patch and evidence while that decision is pending.

Review visible UI changes in the relevant viewports. Reuse screenshots, traces,
logs and useful videos from the existing run. A separate proof-video production
workflow is needed only when requested or part of the accepted scope. Use
`response_media.py` to publish reviewed private expiring evidence if needed.

Platform-specific checks belong to their relevant skills (for example `ios`).
Shared policy and exception handling: `.claude/rules/testing.md` and `AGENTS.md`.
