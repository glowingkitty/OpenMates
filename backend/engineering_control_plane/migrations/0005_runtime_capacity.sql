-- One authoritative resource ledger per host, alongside existing runtime leases.
-- All admission/release transitions lock this row before reading measurements.
-- No product data or credentials are stored here.
CREATE TABLE control_plane_runtime_capacity (
    host_key text PRIMARY KEY,
    state jsonb NOT NULL DEFAULT '{"version":1,"requests":[]}'::jsonb,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (jsonb_typeof(state) = 'object')
);
