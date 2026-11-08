# Rust migration status files

Machine-readable status of the Rust migration. Generated files carry a `GENERATED` header and are
rewritten by `python3 scripts/rust_migration_yaml.py` (deploy and `ci-source` run `--check`).
Human report: `docs/architecture/platforms/rust-migration-status.md`.

| File | Kind | Content |
|---|---|---|
| `overview.yml` | generated | Area percents, `overall` weighted percent, `performance` (latest per flow/metric, stale flags), `perf_attention` |
| `web-app.yml`, `shared-client.yml`, `cli.yml`, `sdk.yml` | generated | Per-area detail |
| `web-port-ledger.yml` | curated | Which portable TS functions route to shared Rust (the web_app numerator) |
| `performance-history.yml` | curated, append-only | Bench results (`scripts/record_perf_measurement.py`) |
| `web-lanes.yml`, `web-app-curated.yml`, `spec-links.yml` | curated | Lane plan, per-namespace evidence, spec links |

## Web app percent

`web_app.percent` = ported / portable TS code lines, measured by `scripts/rust_web_port_ledger.py`:

- **Portable** = `.ts` under `frontend/packages/ui/src/{services,utils,stores}` minus tests, the
  Rust bridge (`services/rustCore/**`, `*Rust.ts`) and the `non_portable` list (each entry has a
  reason: audio, DOM, view state, synchronous render helpers, ...). Svelte components are out of scope.
- **Ported** = code lines of the functions listed in ledger slices. Each listed function must read
  the flag, a flag constant or a bridge import (it routes to Rust); a function over 80 code lines
  counts only its flag decision sites.
- **Proof** per slice: `e2e-flag-on` (a `web-rust-core-*` spec is listed), `vectors` (a parity test is
  listed) or `none`. A listed spec means coverage exists, not that its latest run was green.
- Installed Worker namespaces are kept as `worker_namespaces_installed_not_progress`; they are not progress.

## Lane procedure: append a ledger slice

Every web slice that routes TS to Rust appends one entry to `web-port-ledger.yml` in the same deploy:

1. `python3 scripts/rust_web_port_ledger.py --suggest` prints a stub for each routing function no
   slice lists yet (uncommitted work shows as `TODO-uncommitted`).
2. Give the stub a unique `id`, `date: 'YYYY-MM-DD'`, `commit: null` (= the commit that adds the entry;
   find it later with `git log -S'id: <id>' -- docs/migration/rust/web-port-ledger.yml`), the Rust
   modules, vector tests and flag-on E2E specs.
3. If the new code is in a file that should not count, add a `non_portable` entry with a reason instead.
4. `python3 scripts/rust_migration_yaml.py` then `--check`. `--check` fails on a routing function
   without a ledger entry, a listed function that does not route, duplicate claims or missing files.

## Overall and performance

- `overall.percent` = 0.4 web_app + 0.2 shared_client + 0.25 cli + 0.15 sdk (sdk = mean of the three
  SDK percents); weights decided 2026-11-08 (`scripts/rust_migration_rollup.py`).
- `performance.latest` is the last history entry per (flow, metric). `stale` = more than 24 h older
  than the newest ledger slice date (day granularity; no git calls, so `--check` works in shallow clones).
- `perf_attention` lists latest `rust_worse` entries and known problems not yet recorded
  (`UNRECORDED` in `rust_migration_rollup.py`; drop a line once its measurement is in the history).
