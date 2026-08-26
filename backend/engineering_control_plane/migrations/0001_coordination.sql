-- Independent engineering control-plane coordination foundation.
-- This migration runs only against the dedicated engineering PostgreSQL service.
-- It must never be included by product Directus or product database migrations.

CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE TABLE control_plane_runtime_state (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    runtime_epoch bigint NOT NULL DEFAULT 0 CHECK (runtime_epoch >= 0),
    updated_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO control_plane_runtime_state (singleton) VALUES (true)
ON CONFLICT (singleton) DO NOTHING;

CREATE TABLE control_plane_resource_leases (
    lease_key text PRIMARY KEY,
    owner_key text NOT NULL,
    status text NOT NULL CHECK (status IN ('active', 'released', 'expired')),
    acquired_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    released_at timestamptz,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    CHECK (expires_at > acquired_at),
    CHECK ((status = 'released') = (released_at IS NOT NULL))
);

CREATE TABLE control_plane_resource_lease_items (
    lease_key text NOT NULL REFERENCES control_plane_resource_leases(lease_key) ON DELETE CASCADE,
    resource_key text NOT NULL,
    active_window tstzrange NOT NULL,
    status text NOT NULL CHECK (status IN ('active', 'released', 'expired')),
    PRIMARY KEY (lease_key, resource_key),
    EXCLUDE USING gist (
        resource_key WITH =,
        active_window WITH &&
    ) WHERE (status = 'active')
);

CREATE TABLE control_plane_runtime_operations (
    operation_key text PRIMARY KEY,
    requested_by text NOT NULL,
    operation_type text NOT NULL,
    status text NOT NULL CHECK (status IN ('queued', 'admitted', 'running', 'completed', 'failed', 'cancelled')),
    requested_at timestamptz NOT NULL,
    admitted_at timestamptz,
    completed_at timestamptz,
    admitted_runtime_epoch bigint CHECK (admitted_runtime_epoch >= 0),
    completed_runtime_epoch bigint CHECK (completed_runtime_epoch >= 0),
    failure_class text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE control_plane_runtime_operation_resources (
    operation_key text NOT NULL REFERENCES control_plane_runtime_operations(operation_key) ON DELETE CASCADE,
    resource_key text NOT NULL,
    PRIMARY KEY (operation_key, resource_key)
);

CREATE INDEX control_plane_runtime_operations_queue_idx
    ON control_plane_runtime_operations (requested_at, operation_key)
    WHERE status = 'queued';

CREATE TABLE control_plane_dispatch_requests (
    dispatch_key text PRIMARY KEY,
    fingerprint_sha256 char(64) NOT NULL,
    repository text NOT NULL,
    subject_commit text NOT NULL,
    test_selection jsonb NOT NULL,
    profile text NOT NULL,
    account_key text NOT NULL,
    mocks jsonb NOT NULL,
    required_services jsonb NOT NULL,
    runtime_epoch bigint NOT NULL CHECK (runtime_epoch >= 0),
    requested_by text NOT NULL,
    status text NOT NULL CHECK (status IN ('pending_canary', 'prevented', 'queued', 'running', 'succeeded', 'failed', 'cancelled', 'environment_interrupted')),
    reason text,
    requested_at timestamptz NOT NULL,
    started_at timestamptz,
    completed_at timestamptz,
    CHECK (jsonb_typeof(test_selection) = 'array'),
    CHECK (jsonb_typeof(mocks) = 'object'),
    CHECK (jsonb_typeof(required_services) = 'array')
);

CREATE UNIQUE INDEX control_plane_dispatch_requests_reuse_idx
    ON control_plane_dispatch_requests (fingerprint_sha256)
    WHERE status IN ('pending_canary', 'queued', 'running', 'succeeded');

CREATE TABLE control_plane_dispatch_canaries (
    dispatch_key text NOT NULL REFERENCES control_plane_dispatch_requests(dispatch_key) ON DELETE CASCADE,
    service_key text NOT NULL,
    healthy boolean NOT NULL,
    checked_at timestamptz NOT NULL,
    failure_class text,
    PRIMARY KEY (dispatch_key, service_key)
);

CREATE TABLE control_plane_session_events (
    cursor bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_key text NOT NULL UNIQUE,
    schema_version integer NOT NULL DEFAULT 1 CHECK (schema_version > 0),
    event_type text NOT NULL CHECK (event_type IN ('dispatch.changed', 'lease.changed', 'runtime.changed', 'task.changed')),
    target_type text NOT NULL CHECK (target_type IN ('session', 'task', 'dispatch', 'lease', 'runtime_operation')),
    target_key text NOT NULL,
    subject_key text NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    retain_until timestamptz NOT NULL DEFAULT (now() + interval '7 days'),
    CHECK (jsonb_typeof(payload) = 'object')
);

CREATE INDEX control_plane_session_events_target_cursor_idx
    ON control_plane_session_events (target_type, target_key, cursor);

CREATE TABLE control_plane_session_event_acknowledgements (
    event_key text NOT NULL REFERENCES control_plane_session_events(event_key) ON DELETE CASCADE,
    recipient_key text NOT NULL,
    acknowledged_at timestamptz NOT NULL,
    PRIMARY KEY (event_key, recipient_key)
);

