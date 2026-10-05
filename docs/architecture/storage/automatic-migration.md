# Automatic archive migration

The supported unattended update path is `openmates server update` for registered
core installations using official images or source builds. The updater installs
the runtime monitoring service, refreshes the actual serving API inventory after
health checks, and runs the migration coordinator. Monitoring renews that inventory
every minute; each inventory expires after three minutes.

The coordinator fetches the signed eligibility certificate for the exact installed
source. Public verification keys ship in the runtime. No installation needs its
own reviewed receipt or signing key. Missing certificates or runtime compatibility
evidence pause advancement and retry automatically. Existing archived reads remain
available when further pruning pauses. Explicit archive feature settings of `0`
remain emergency opt-outs.

Copying and verification preserve PostgreSQL source data. Supported message pages
and historical embed versions activate only with current release and client
evidence. The initial real cohort retains its source for 24 hours before eligible
per-unit pruning. Every pruning batch rechecks eligibility and the transactional
acknowledgement, generation and reference fences. Chat metadata and current embed
heads remain in PostgreSQL. Legacy whole-graph migration is held pending its
metadata retention policy. Updates never automatically restore a database backup
over newer writes.

## Direct Compose installations

A direct `docker compose` or `git pull` does not install the host monitoring
service. Use the registered CLI update path, or keep the shipped host coordinator
running under your service manager with the exact Compose deployment file:

```sh
python3 scripts/storage_runtime_inventory.py refresh --compose-file /path/to/compose.yml --loop
```

The helper enumerates every API container and its actual serving Uvicorn processes,
validates a coherent source revision, and publishes a short shared Redis lease. It
prints only bounded status and source/instance identifiers. Custom Compose override
files or project selection require an equivalent complete enumeration using
`refresh_host_inventory`; enumerating a subset cannot prove deployment compatibility.
If refresh stops or verification fails, migration pauses when the inventory expires.
`openmates server status` reports migration progress and the current pause reason.
