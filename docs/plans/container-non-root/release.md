# Release checks for non-root containers

Apply each changed service through the normal release. Use the reviewed merge
SHA for both the image and its Compose template. Record the previous healthy
image tag and template before starting so the normal CLI rollback restores
both together.

1. Use the matching server-management CLI and dry run the update for the
   affected services. Review setup-job order, mounted paths, ports, effective
   user and supplemental groups. Use the approved host paths and bind mounts.
   For example, preview a core update with
   `openmates server update --services api,task-worker --dry-run --json`.
2. Check backup and restore readiness before touching persistent data. Compare
   the expected UID and GID against each mounted directory and file. Prepare
   only the affected writable paths with their intended ownership and keep the
   original ownership available for rollback. Leave image code and read-only
   mounts read-only. Keep private token and unseal files restricted to their
   intended consumers and avoid printing their contents during checks.
3. Update one service at a time. Where a one-shot setup service provides runtime
   credentials, verify that setup exits successfully and that the dependent
   service can read its existing handoff before accepting the update. Preserve
   named volumes during restart and rollback.
4. Check container health and the numeric effective UID of the daemon and its
   children. Roll back the affected service, template and any ownership
   preparation if a startup, permission or functional check fails.

| Host | Service checks |
| --- | --- |
| Core | Check CMS and API health, Vault readiness and a real chat that receives an assistant reply. Exercise a Celery task after worker changes and encrypted chat read/write after API or credential-volume changes. |
| Upload | Include Vault setup and upload together when their handoff volume changes. Check the upload health endpoint, approved Origin preflights, rejection of unknown Origins and a real upload using the existing client encryption flow. Check ClamAV separately if its identity changes. |
| Preview | Check preview health, a cold-cache fetch and a cache hit, plus cache readability and writability under the preview UID. |
| Maintenance sidecar | Check the maintenance health endpoint and a scoped read-only Docker/log operation. Confirm Docker socket group access and checkout ownership for that server account. |

The CI Postgres schema carrier is released by its dev CI publisher and uses
fresh volumes. It has no production, upload or preview rollout step.

Directus runs its startup script as `node` (UID/GID 1000). Before rollout,
confirm that identity can write the mounted `/directus/uploads` directory.
New named volumes inherit the directory prepared in the image. For an
existing directory with a different owner, record the prior ownership and
prepare the mounted directory before starting the new image. The service
continues to listen on port 8055.

The Core Vault data directory must be writable by the upstream `vault`
account (UID 100, GID 1000), and its mounted configuration readable by that
account. Record the mounted volume's ownership before updating. Verify the
normal startup unseals Vault with its existing data and that the API returns
to healthy. The deployed file-storage configuration keeps mlock disabled.

Core API and Celery use UID/GID 1000. Check that existing API logs,
recommendation data and the Celery beat schedule are writable by this user.
Run the matching Vault setup before the API and workers so it assigns
application handoff files to UID 1000 and preserves their existing modes.
Verify worker heartbeats, a queued task and the scheduler after the update.

For source deployments with a checkout mounted into the maintenance sidecar,
set `OPENMATES_SIDECAR_UID` and `OPENMATES_SIDECAR_GID` to the non-root
checkout owner's numeric IDs. Set `DOCKER_GID` to the Docker socket's group.
The published image defaults to UID/GID 10005 for installations without a
checkout bind mount. Check the actual groups and a read-only log request
before attempting the next service update.

Promtail uses UID/GID 10006 with the Docker socket group and the core log
group 1000. Before updating, check it can read the mounted configuration
and API logs. After the update, check its readiness on port 9080 and that
new log entries reach OpenObserve.

Dragonfly starts as its upstream `dfly` account. Confirm the cache volume
is owned by UID/GID 999 on the release image. Save its current state to
the existing volume before recreating the service. Check authenticated
cache health and the core API afterward.

For upload Vault setup, prepare the existing private setup volume and separate
app handoff volume for UID/GID 10003 before the first start. Keep the directories
at mode 0700 and private credential files at 0600. Verify that the root token
is private to setup and the uploads app can read its scoped token through the
read-only mount. Fresh volumes inherit the directories prepared in the image.

ClamAV uses the upstream `clamav` account and unprivileged entrypoint. Check
ownership of the existing virus database before updating the scanner. Confirm
ClamAV health on port 3310, a benign-file scan and a successful signature
update under that identity before resuming upload checks.
[ClamAV container documentation](https://docs.clamav.net/manual/Installing/Docker.html).
