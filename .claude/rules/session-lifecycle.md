---
paths:
  - "scripts/sessions.py"
  - "scripts/ci_coordinator.py"
---
# Session lifecycle

- Read-only work needs no session. First mutation:
  `sessions.py start --mode <bug|feature|docs|testing> --task <outcome>`; it
  reuses an existing binding for this Claude terminal. Sub-agents share it.
  SSH/manual work passes the returned `--session`.
- Parallel lanes: the parent runs `python3 scripts/lane_start.py --task "<outcome>"`
  per lane (fresh session, `lane-open` flag so the edit gate admits sub-agents
  in that worktree only) and gives each agent its `session=` and `worktree=`.
  Lane agents `cd` into the worktree, pass `--session <id>` and never run
  `start`/`end`. `start` refuses a stale or ended binding; use `start --new`.
  `lane_start.py` retries up to 3 times and rolls back each failed attempt's
  half-created session; it then exits with the last error. Leftover orphans
  (no worktree, no modified files, no write claim) are removed by
  `sessions.py cleanup-orphans [--session <id>] [--dry-run]
  [--min-age-seconds N]`; sessions with a worktree or changes are never touched.
- Lanes never hand-regenerate or stage generated outputs
  (`specifications/generated/*`, `docs/migration/rust/{overview,web-app,
  shared-client,cli,sdk}.yml`): deploy rebuilds them in the integration
  checkout. To catch up with dev run `sessions.py worktree refresh-base
  --rebase --session <id>`: it 3-way merges lane edits that overlap dev
  changes, rebuilds generated files, and first pins all lane edits under
  `refs/openmates/rebase-backups/<worktree>` (restore: `git checkout <ref> --
  <path>`). On a true conflict it changes nothing and lists files and hunks;
  make each lane file its intended final content and rerun. Deploy also
  auto-fast-forwards a stale lane (overlaps stay on the recorded base) and
  recreates empty or stale checkpoints; never delete checkpoint refs by hand.
- `sessions.py ci-source` rebuilds stale Specification artifacts (including
  `assertion-index.yml` when an edit moves a test line) and generated Rust YAML
  itself for the candidate (restored in the lane afterwards); a generator
  failure refuses with its cause. Never run `specifications.py generate` by
  hand or hand-edit/stage `specifications/generated/*`. `ci-source` and
  `deploy --only` auto-track new (Git-untracked, non-ignored) files in the
  lane's own worktree, so no manual `track` is needed. `--only` and
  `--exclude` are repeatable (`--only a --only b` or `--only a b`; exact
  paths). Files named in `--only` count as tracked (no `track`/
  `--allow-untracked`); a file another session also tracks only prints an
  advisory. Deploy refuses when `--only` leaves out dirty session files and
  lists them: add each with `--only`, or leave it out on purpose with
  `--exclude <path>`. Rust YAML regenerates on any generator input (see
  `scripts/rust_migration_inputs.py`), e.g. `config/cli-command-catalog.json`.
- Saved patches: the rtk filter turns `git diff` into a stat summary; use
  `rtk proxy git diff --binary`.
- Other running Claude chats (task, workspace, recent files) are injected at
  session start and whenever they change (`.claude/hooks/peer-chats.sh`).
  Inspect one with `python3 scripts/agent_peers.py history <chat-id>`.
- Re-read files before editing; preserve other tasks' edits and edit leases.
  Do not create another worktree after deployment to continue the same task.
- `sessions.py deploy --title <title> --message <why>` validates, serializes and
  pushes the scoped diff to `dev`. Use `prepare-deploy` only to inspect scope.
  Keep the canonical checkout on `dev`.
- Shared dev runtime mutations: `sessions.py docker restart --session <id>
  --service <name>` with its resource leases; not a substitute CI runner.
- OpenMates Tasks owns status; no local task ledgers. `sessions.py end` is
  optional maintenance and invents no proof or approval requirements.
