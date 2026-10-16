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

On the official cloud, new archive copies and pruning remain held while
`STORAGE_LOGICAL_S3_BILLING_ENABLED` is anything other than exactly `1`.
This includes an unset flag. The coordinator reports `storage_billing_disabled`
and retries; authorized reads, recovery and exports of existing archives remain
available. Self-host installations retain their independent archive behavior.
The hold does not set billing flags or waive any release, client, replica,
acknowledgement, generation or 24-hour source-retention fence.

For the first production rollout, reconcile the usage meter, user notices and
legal terms before persisting the approved logical billing flags in the existing
installation with `openmates server env set` using its registered `--path`.
Then run the standard `openmates server update` for that path. Once the new
containers have the approved flag and all existing eligibility evidence, the
coordinator advances qualified migration automatically. Do not enable the
flag solely to clear a migration pause.

Copying and verification preserve PostgreSQL source data. Supported message pages
and historical embed versions activate only with current release and client
evidence. The initial real cohort retains its source for 24 hours before eligible
per-unit pruning. Every pruning batch rechecks eligibility and the transactional
acknowledgement, generation and reference fences. Chat metadata and current embed
heads remain in PostgreSQL. Legacy whole-graph migration is held pending its
metadata retention policy. Updates never automatically restore a database backup
over newer writes.

## First upgrade from an older CLI

`openmates server update` updates server images or source; it does not upgrade
the globally installed CLI. The migration-aware host updater and monitor
installer are part of that CLI. Before the first rollout, publish and verify a
stable npm package containing these changes, then upgrade the CLI from the same
administrator environment that owns the registered installation:

```sh
openmates upgrade --channel stable
openmates version
```

For an older CLI without `upgrade`, use `npm install -g openmates@latest`
instead. Development installations can use `openmates upgrade --channel dev`
after verifying the intended alpha package. Preserve the existing registration
and `OPENMATES_STATE_DIR`; upgrading the executable does not transfer ownership
or recreate user data.

The main-branch CLI publication workflow skips a stable version already present
on npm. A release must therefore use a new configured stable version and verify
its publication; merging CLI source alone cannot replace an existing npm
version. Verify the intended backend images and exact-source eligibility are
available before the server update. Stable image updates resolve the published
GitHub release by default; source updates pull their registered branch. An
explicit immutable `--image-tag sha-<40-character-source>` can select the
intended published image, but it still needs its own release qualification.

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
