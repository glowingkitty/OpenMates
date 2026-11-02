# Agent workflow

`CLAUDE.md` is the concise entry point. Claude Code owns conversations; the installed
OpenMates CLI owns Tasks and synchronization; GitHub CI owns isolated application
stacks and E2E runs. Repository helpers own workspace safety and scoped publishing.

1. Read relevant source/tests. First mutation: `python3 scripts/sessions.py start
   --mode bug --task "<outcome>"`. Reuse its workspace and binding.
2. Implement and update relevant E2E coverage. Run focused local checks. Publish
   an immutable source with `sessions.py ci-source`, submit through
   `ci_coordinator.py submit`, and wait with `ci_coordinator.py wait <id>` or use
   existing completion events. JSON is opt-in when another program needs it.
   Retrieve existing web/CLI E2E recordings and run the selected run receipt's
   `codex_evidence_command`. A failed/cancelled run with a run ID needs
   `ci_coordinator.py result <id>` first. Final chat links only the latest successful
   recording per requested check/flow across retries/reruns, or its latest available
   failed recording if that request never succeeded. Include distinct required
   views; omit duplicates and superseded attempts, with no appendix of all links.
   Report missing capture/upload failures for selected evidence. Follow
   `.claude/rules/testing.md` for the complete delivery policy.
3. Publish with `sessions.py deploy --title "type: description" --message "why"`.
   Use `--session` for SSH/manual work. For frontend readiness use
   `sessions.py wait-deploy --commit <sha>` and wait on that process.

Update OpenMates Tasks only at meaningful changes; successful acknowledged writes
need no follow-up read. Preserve queued deliveries. Handoffs contain the outcome,
Task, binding, owned paths, evidence and unresolved decisions in 100–200 words.
Parallel implementation streams each run in their own Claude Code conversation;
the workspace binding follows `CLAUDE_CODE_SESSION_ID`.

The repository has exactly two branches: `dev` and `main`. Sessions use detached
managed worktrees. `ci-source` transports candidate bytes through a private,
expiring, SHA-verified artifact; it never creates a branch. Do not create task,
candidate, hotfix, automation, or dependency branches. Audit the invariant with
`python3 scripts/branch_invariant.py audit`.

Read `.claude/rules/testing.md` for E2E maintenance and bounded debugging. Ask
before a materially broader or uncertain repair. Explicit user waivers persist.
Skills, agents and hooks live only in `.claude/`; edit them in place. Review
changed hook definitions with `/hooks`. Rules use `paths:` frontmatter so they
load only for matching files; keep `CLAUDE.md` short because it always loads.

Legacy conversation records are historical data, not executable workflow rules.
See `docs/architecture/codex-task-cache.md` for task transport and recovery.

