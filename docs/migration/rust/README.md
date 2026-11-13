# Rust migration status files

Machine-readable status of the Rust migration. Generated files carry a `GENERATED` header and are
rewritten by `python3 scripts/rust_migration_yaml.py` (deploy and `ci-source` run `--check`).
Human report: `docs/architecture/platforms/rust-migration-status.md`.

## Progress metric: capabilities at rust-only (current)

The migration follows "one Rust client core, three thin shells"
(`specifications/architecture/client-core/`, plan
`docs/plans/client-core-one-core-three-shells/plan.yml`, rule `.claude/rules/client-core.md`).
Progress is counted per capability and per shell (web, Apple, TUI/CLI) with the status
`ts-only | swift-only | rust-twin | rust-default | rust-only | stays-shell`. A cell is done
at `rust-only` (old shell implementation deleted, that shell's existing suite green on the
exact deployed commit) or `stays-shell` (legitimate UI/platform/credential-storage work).
Progress = done cells / all cells. The curated `capabilities.yml` here is authoritative (id, per-shell
status, old paths, note, last_commit); `rust_migration_yaml.py --check` validates the enum and that a
`rust-only` cell lists no existing old path, and `overview.yml` shows per-shell status counts.
A lane moves its cell and `last_commit` in the same deploy that deletes the old code.

| File | Kind | Content |
|---|---|---|
| `capabilities.yml` | curated | One entry per capability with web/apple/tui status, old paths, note, last commit |
| `overview.yml` | generated | Area percents, per-shell capability counts, `overall` weighted percent, `performance`, `perf_attention` |
| `web-app.yml`, `shared-client.yml`, `cli.yml`, `sdk.yml` | generated | Per-area detail |
| `performance-history.yml` | curated, append-only | Bench results (`scripts/record_perf_measurement.py`) |
| `web-lanes.yml`, `web-app-curated.yml`, `spec-links.yml` | curated | Lane plan, per-namespace evidence, spec links |

## Overall and performance

- `overall.percent` = 0.4 web_app + 0.2 shared_client + 0.25 cli + 0.15 sdk (sdk = mean of the three
  SDK percents); weights decided 2026-11-08 (`scripts/rust_migration_rollup.py`).
- `performance.latest` is the last history entry per (flow, metric). `stale` = more than 24 h older
  than the `as_of` date of `capabilities.yml` (day granularity; no git calls, so `--check` works in shallow clones).
- `perf_attention` lists latest `rust_worse` entries and known problems not yet recorded
  (`UNRECORDED` in `rust_migration_rollup.py`; drop a line once its measurement is in the history).
