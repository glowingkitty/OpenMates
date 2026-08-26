# Engineering control plane

This compose project is private engineering infrastructure and is intentionally
separate from every OpenMates product and self-hosted compose project. It uses a
dedicated PostgreSQL volume, network, credential namespace, and lifecycle.

The service is the canonical private store for `scripts/tests.py` and the
durable coordination backend for `scripts/sessions.py`. Authenticated record,
lease, runtime-operation, dispatch, canary, and cursor-event routes are live;
the bounded Directus backfill is parity-checked before cutover.

This is an engineering-only deployment. It is not referenced by product or
self-host Compose manifests and is not required by the OpenMates CLI. The
source-checkout restart guard activates only when this repository's manager and
the host-only `~/.config/openmates/engineering-control-plane.env` both exist.

Legacy Directus collections remain a fenced rollback archive during the
observation window. Do not delete them until the independent backup/restore,
retention, status-projection, and final distribution-audit gates in the spec
are complete.
