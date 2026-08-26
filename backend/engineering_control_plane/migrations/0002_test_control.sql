-- Canonical test coordination tables migrated from product Directus.
-- Stable string keys preserve compatibility while JSON fields remain bounded
-- to redacted engineering metadata and artifact references.

CREATE TABLE test_catalog (
    test_key text PRIMARY KEY,
    suite text,
    test_name text,
    file_path text,
    verification_command text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE test_runs (
    run_key text PRIMARY KEY,
    source text,
    external_run_id text,
    workflow text,
    status text,
    git_sha text,
    git_branch text,
    environment text,
    requested_tests jsonb NOT NULL DEFAULT '[]'::jsonb,
    campaign_key text,
    debug_group_key text,
    summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    record_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at text,
    updated_at_unix bigint
);

CREATE INDEX test_runs_updated_idx ON test_runs (updated_at_unix DESC);
CREATE INDEX test_runs_external_idx ON test_runs (source, external_run_id);

CREATE TABLE test_results (
    result_key text PRIMARY KEY,
    run_key text,
    test_key text,
    suite text,
    test_name text,
    status text,
    error_summary text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at text,
    created_at_unix bigint
);

CREATE INDEX test_results_test_created_idx ON test_results (test_key, created_at_unix);
CREATE INDEX test_results_run_idx ON test_results (run_key);

CREATE TABLE test_current_state (
    test_key text PRIMARY KEY,
    suite text,
    test_name text,
    stable_status text,
    stable_result_key text,
    stable_run_key text,
    active_status text,
    active_run_key text,
    triage_group_id text,
    error_summary text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at text,
    updated_at_unix bigint
);

CREATE INDEX test_current_state_status_idx ON test_current_state (stable_status, active_status);

CREATE TABLE test_claims (
    claim_key text PRIMARY KEY,
    lease_id text,
    group_id text,
    campaign_key text,
    debug_group_key text,
    status text,
    session_id text,
    worker_id text,
    leased_at text,
    expires_at text,
    expires_at_unix bigint,
    updated_at text,
    completed_at text,
    completed_commit text,
    commit text,
    released_at text,
    release_reason text,
    entry_json jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE UNIQUE INDEX test_claims_one_active_group_idx
    ON test_claims (group_id)
    WHERE status = 'active';
CREATE INDEX test_claims_expiry_idx ON test_claims (status, expires_at_unix);

CREATE TABLE test_debug_campaigns (
    campaign_key text PRIMARY KEY,
    title text,
    status text,
    session_id text,
    source_run_keys jsonb NOT NULL DEFAULT '[]'::jsonb,
    selected_test_keys jsonb NOT NULL DEFAULT '[]'::jsonb,
    selected_group_keys jsonb NOT NULL DEFAULT '[]'::jsonb,
    current_group_key text,
    completion_policy jsonb NOT NULL DEFAULT '{}'::jsonb,
    blocker jsonb,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at text,
    updated_at text,
    completed_at text
);

CREATE INDEX test_debug_campaigns_status_idx ON test_debug_campaigns (status, created_at);

CREATE TABLE test_debug_groups (
    group_key text PRIMARY KEY,
    campaign_key text,
    triage_group_id text,
    parent_group_key text,
    status text,
    member_test_keys jsonb NOT NULL DEFAULT '[]'::jsonb,
    observed_failure text,
    expected_behavior text,
    acceptance_criteria jsonb NOT NULL DEFAULT '[]'::jsonb,
    root_cause jsonb,
    attempts jsonb NOT NULL DEFAULT '[]'::jsonb,
    red_evidence jsonb,
    green_evidence jsonb,
    blocker jsonb,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    verification_command text,
    fixing_commit text,
    selected_at text,
    selected_at_unix bigint,
    updated_at text
);

CREATE INDEX test_debug_groups_campaign_idx ON test_debug_groups (campaign_key, selected_at_unix);

CREATE TABLE control_plane_audit_events (
    audit_key bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actor_key text NOT NULL,
    operation text NOT NULL,
    target_type text NOT NULL,
    target_key text,
    outcome text NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE status_projection_outbox (
    projection_key text PRIMARY KEY,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz,
    attempt_count integer NOT NULL DEFAULT 0,
    last_failure_class text
);

