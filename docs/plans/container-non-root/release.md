# Release checks for non-root containers

Apply each changed service through the normal release. Use the reviewed merge
SHA for both the image and its Compose template. Record the previous healthy
image tag and template before starting so the normal CLI rollback restores
both together.

1. Use the matching server-management CLI and dry run the update for the
   affected services. Review setup-job order, mounted paths, ports, effective
   user and supplemental groups. Use the approved host paths and bind mounts.
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
