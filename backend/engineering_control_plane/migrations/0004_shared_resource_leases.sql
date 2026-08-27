-- Allow concurrent read/test leases while keeping runtime mutations exclusive.
-- Repository transactions take advisory locks per resource before admission, so
-- this migration removes the older all-exclusive range constraint.

ALTER TABLE control_plane_resource_leases
    ADD COLUMN mode text NOT NULL DEFAULT 'exclusive'
    CHECK (mode IN ('shared', 'exclusive'));

ALTER TABLE control_plane_resource_lease_items
    DROP CONSTRAINT control_plane_resource_lease_it_resource_key_active_window_excl;

CREATE INDEX control_plane_resource_lease_items_active_window_idx
    ON control_plane_resource_lease_items USING gist (resource_key, active_window)
    WHERE status = 'active';
