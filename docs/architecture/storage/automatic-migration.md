# Automatic archive migration

The supported unattended update path is `openmates server update` for registered
core installations using official images or source builds. Install and update require
host administrator privileges to write and enable systemd units. For a fresh install,
use an administrator shell with Node.js/npm and the global `openmates` executable
available; an executable depending on another user's Node installation is insufficient.
Existing installs retain their installation path and registered CLI state
(`OPENMATES_STATE_DIR` when configured). The updater installs
the runtime monitoring service, refreshes the actual serving API inventory after
health checks, and runs the migration coordinator. Monitoring renews that inventory
every minute; each inventory expires after three minutes. Fresh source-based
CLI starts build containers with the exact clean checkout revision before starting
them. Fresh CLI installs also provision monitoring automatically; the first
successful monitor run publishes the inventory after containers start. Installing
or renewing the monitor needs no separate manual step after successful install or
update. If monitor installation fails, the command reports failure/degraded state;
if renewal fails, archive advancement pauses when the 180-second lease expires.
Dirty or unknown source builds remain usable but receive no release
attestation, so migration advancement safely pauses.

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

## Supported commands

From the administrator shell, a fresh self-host installation using stable images is:

```sh
openmates server install --path /opt/openmates --role core --image-tag stable
openmates server start --path /opt/openmates --role core
```

Registered official production and self-host image installations use:

```sh
openmates server update --path /path/to/existing/install --role core --channel stable
```

A fresh source installation can clone a clean checkout, including `main`:

```sh
openmates server install --path /opt/openmates-source --role core --source-path /path/to/clean-main-checkout
openmates server start --path /opt/openmates-source --role core
openmates server update --path /opt/openmates-source --role core
```

Fresh starts wait for Compose's successful `cms-setup` dependency. Updates run and
verify target schema/index setup before starting target API and worker containers.
Storage schema/index setup is resumable and retains existing message data; a failed
required index migration stops setup and can be retried. Source builds attest only
the actual clean commit. Release eligibility is specific to that commit; eligibility
for `dev` does not authorize different `main` or stable-image code.

`server register` alone records an existing checkout; its next `server update`
provisions monitoring. Registration followed only by `server start` does not install
a missing monitor.

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
