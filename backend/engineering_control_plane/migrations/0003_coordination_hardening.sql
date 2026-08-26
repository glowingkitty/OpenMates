-- Runtime-operation lifecycle states and coordination query indexes.

ALTER TABLE control_plane_runtime_operations
    DROP CONSTRAINT control_plane_runtime_operations_status_check;

ALTER TABLE control_plane_runtime_operations
    ADD CONSTRAINT control_plane_runtime_operations_status_check
    CHECK (status IN (
        'queued', 'admitted', 'draining_tests', 'restarting', 'verifying',
        'completed', 'failed', 'cancelled'
    ));

CREATE INDEX control_plane_resource_lease_items_active_resource_idx
    ON control_plane_resource_lease_items (resource_key, lease_key)
    WHERE status = 'active';

CREATE INDEX control_plane_runtime_operation_resources_resource_idx
    ON control_plane_runtime_operation_resources (resource_key, operation_key);

