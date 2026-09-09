-- User task hot-path indexes.
-- These keep task list/board/retention queries bounded as completed tasks and
-- key wrappers grow. All statements are idempotent for Directus setup reruns.

UPDATE user_tasks
SET assignee_type = CASE
        WHEN external_chat_provider = 'opencode' THEN 'external_ai'
        ELSE 'openmates'
    END,
    assignee_identity = CASE
        WHEN external_chat_provider = 'opencode' THEN 'opencode'
        ELSE 'openmates'
    END,
    assignee_hash = NULL
WHERE assignee_type = 'ai';

CREATE INDEX IF NOT EXISTS user_tasks_owner_status_position_idx
    ON user_tasks (hashed_user_id, status, position, created_at);

CREATE INDEX IF NOT EXISTS user_tasks_owner_priority_idx
    ON user_tasks (hashed_user_id, priority DESC, position, created_at);

CREATE INDEX IF NOT EXISTS user_tasks_team_admission_idx
    ON user_tasks (hashed_team_id, status, assignee_type, priority DESC, position, created_at)
    WHERE hashed_team_id IS NOT NULL;

DROP INDEX IF EXISTS user_tasks_ai_admission_idx;
CREATE INDEX IF NOT EXISTS user_tasks_openmates_admission_idx
    ON user_tasks (status, assignee_type, due_at, priority DESC, position, created_at)
    WHERE assignee_type = 'openmates' AND status IN ('todo', 'in_progress', 'blocked');

CREATE INDEX IF NOT EXISTS user_tasks_owner_completed_idx
    ON user_tasks (hashed_user_id, completed_at)
    WHERE completed_at IS NOT NULL;

DROP INDEX IF EXISTS user_tasks_due_ai_idx;
CREATE INDEX IF NOT EXISTS user_tasks_due_openmates_idx
    ON user_tasks (due_at, position, created_at)
    WHERE assignee_type = 'openmates' AND due_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS user_tasks_owner_chat_idx
    ON user_tasks (hashed_user_id, hashed_primary_chat_id, position, created_at)
    WHERE hashed_primary_chat_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS user_tasks_owner_external_chat_idx
    ON user_tasks (hashed_user_id, external_chat_provider, external_chat_lookup_hash, position, created_at)
    WHERE hashed_team_id IS NULL
      AND external_chat_provider IS NOT NULL
      AND external_chat_lookup_hash IS NOT NULL;

CREATE INDEX IF NOT EXISTS user_tasks_project_hashes_gin_idx
    ON user_tasks USING GIN ((linked_project_hashes::jsonb) jsonb_path_ops);

CREATE INDEX IF NOT EXISTS user_tasks_label_hashes_gin_idx
    ON user_tasks USING GIN ((label_hashes::jsonb) jsonb_path_ops);

CREATE INDEX IF NOT EXISTS user_task_key_wrappers_task_owner_idx
    ON user_task_key_wrappers (hashed_task_id, hashed_user_id);

UPDATE user_task_activity AS activity
SET hashed_task_id = encode(digest(activity.task_id, 'sha256'), 'hex'),
    hashed_user_id = tasks.hashed_user_id,
    hashed_team_id = tasks.hashed_team_id,
    entry_id = COALESCE(activity.entry_id, activity.id::text),
    kind = COALESCE(activity.kind, 'lifecycle_update'),
    source_surface = COALESCE(activity.source_surface, 'system')
FROM user_tasks AS tasks
WHERE activity.task_id = tasks.task_id
  AND (
      activity.hashed_task_id IS NULL
      OR activity.hashed_user_id IS NULL
      OR activity.entry_id IS NULL
      OR activity.kind IS NULL
      OR activity.source_surface IS NULL
  );

DROP INDEX IF EXISTS user_task_activity_task_created_idx;

CREATE UNIQUE INDEX IF NOT EXISTS user_task_activity_task_entry_uq
    ON user_task_activity (hashed_task_id, entry_id);

CREATE INDEX IF NOT EXISTS user_task_activity_personal_created_idx
    ON user_task_activity (hashed_task_id, hashed_user_id, created_at, entry_id)
    WHERE hashed_team_id IS NULL;

CREATE INDEX IF NOT EXISTS user_task_activity_team_created_idx
    ON user_task_activity (hashed_task_id, hashed_team_id, created_at, entry_id)
    WHERE hashed_team_id IS NOT NULL;

CREATE OR REPLACE FUNCTION record_user_task_lifecycle_activity()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO user_task_activity (
            id, task_id, hashed_task_id, entry_id, hashed_user_id, hashed_team_id,
            kind, actor_type, event_type, source_surface, previous_status,
            next_status, created_at, embed_refs
        ) VALUES (
            gen_random_uuid(), NEW.task_id, encode(digest(NEW.task_id, 'sha256'), 'hex'), gen_random_uuid()::text,
            NEW.hashed_user_id, NEW.hashed_team_id, 'lifecycle_update', 'system',
            'created', 'system', NULL, NEW.status, NEW.created_at, '[]'::json
        );
    ELSIF TG_OP = 'UPDATE' AND NEW.status IS DISTINCT FROM OLD.status THEN
        INSERT INTO user_task_activity (
            id, task_id, hashed_task_id, entry_id, hashed_user_id, hashed_team_id,
            kind, actor_type, event_type, source_surface, previous_status,
            next_status, created_at, embed_refs
        ) VALUES (
            gen_random_uuid(), NEW.task_id, encode(digest(NEW.task_id, 'sha256'), 'hex'), gen_random_uuid()::text,
            NEW.hashed_user_id, NEW.hashed_team_id, 'lifecycle_update', 'system',
            'status', 'system', OLD.status, NEW.status, NEW.updated_at, '[]'::json
        );
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS user_tasks_lifecycle_activity_trigger ON user_tasks;
CREATE TRIGGER user_tasks_lifecycle_activity_trigger
AFTER INSERT OR UPDATE OF status ON user_tasks
FOR EACH ROW EXECUTE FUNCTION record_user_task_lifecycle_activity();

CREATE OR REPLACE FUNCTION delete_user_task_activity_with_task()
RETURNS trigger AS $$
BEGIN
    DELETE FROM user_task_activity WHERE task_id = OLD.task_id;
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS user_tasks_activity_cleanup_trigger ON user_tasks;
CREATE TRIGGER user_tasks_activity_cleanup_trigger
AFTER DELETE ON user_tasks
FOR EACH ROW EXECUTE FUNCTION delete_user_task_activity_with_task();

CREATE INDEX IF NOT EXISTS user_task_archives_owner_archived_idx
    ON user_task_archives (hashed_user_id, archived_at DESC);

CREATE INDEX IF NOT EXISTS user_tasks_task_hash_lookup_idx
    ON user_tasks ((encode(digest(task_id, 'sha256'), 'hex')));

-- Task sync metadata is integration state, not a second Task model. The
-- per-workspace clock is locked until commit, so cursors follow commit order
-- (a sequence alone could skip an older, still-uncommitted transaction).
CREATE TABLE IF NOT EXISTS project_task_sync_clocks (
    scope text PRIMARY KEY,
    revision bigint NOT NULL DEFAULT 0,
    epoch uuid NOT NULL DEFAULT gen_random_uuid()
);
CREATE TABLE IF NOT EXISTS project_task_sync_changes (
    scope text NOT NULL,
    revision bigint NOT NULL,
    task_id text NOT NULL,
    project_hashes jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (scope, revision)
);
CREATE INDEX IF NOT EXISTS project_task_sync_retention_idx
    ON project_task_sync_changes (created_at);

CREATE OR REPLACE FUNCTION record_project_task_sync_change(task_record jsonb, previous_projects jsonb DEFAULT '[]'::jsonb)
RETURNS void AS $$
DECLARE
    scope_key text;
    next_revision bigint;
    projects jsonb;
BEGIN
    IF task_record IS NULL OR task_record->>'task_id' IS NULL THEN RETURN; END IF;
    scope_key := CASE WHEN task_record->>'hashed_team_id' IS NOT NULL
        THEN 'team:' || (task_record->>'hashed_team_id')
        ELSE 'personal:' || (task_record->>'hashed_user_id') END;
    IF scope_key IS NULL THEN RETURN; END IF;
    SELECT COALESCE(jsonb_agg(DISTINCT value), '[]'::jsonb) INTO projects
    FROM jsonb_array_elements(COALESCE(NULLIF(task_record->'linked_project_hashes', 'null'::jsonb), '[]'::jsonb)
                             || COALESCE(NULLIF(previous_projects, 'null'::jsonb), '[]'::jsonb));
    INSERT INTO project_task_sync_clocks(scope, revision) VALUES(scope_key, 1)
    ON CONFLICT(scope) DO UPDATE SET revision = project_task_sync_clocks.revision + 1
    RETURNING revision INTO next_revision;
    INSERT INTO project_task_sync_changes(scope, revision, task_id, project_hashes)
    VALUES(scope_key, next_revision, task_record->>'task_id', projects);
    -- PostgreSQL delivers this hint only after commit. Replay remains durable
    -- if the receiver is offline, restarts, or loses a hint.
    PERFORM pg_notify('openmates_task_sync', scope_key);
END;
$$ LANGUAGE plpgsql;

-- Only an explicit Task dependency wait can clear automatically. Human/approval
-- blockers, encrypted free-text blockers and linked Plan approval stay intact.
CREATE OR REPLACE FUNCTION release_task_dependency_wait(waiting_task_id text)
RETURNS void AS $$
BEGIN
    UPDATE user_tasks t SET status = 'todo', queue_state = 'none',
        blocked_reason_code = NULL, ai_execution_state = NULL,
        version = version + 1, updated_at = extract(epoch FROM now())::bigint
    WHERE t.task_id = waiting_task_id AND t.status = 'blocked'
      AND t.assignee_type = 'external_ai' AND t.assignee_identity = 'codex'
      AND t.external_chat_provider = 'codex'
      AND t.blocked_reason_code = 'external_dependency'
      AND t.encrypted_blocked_reason IS NULL AND t.plan_id IS NULL
      AND EXISTS (SELECT 1 FROM user_work_dependencies d WHERE d.source_kind = 'task' AND d.source_id = t.task_id)
      AND NOT EXISTS (
        SELECT 1 FROM user_work_dependencies d
        LEFT JOIN user_tasks target ON d.target_kind = 'task' AND target.task_id = d.target_id
        WHERE d.source_kind = 'task' AND d.source_id = t.task_id
          AND (d.target_kind <> 'task' OR target.task_id IS NULL OR target.status <> 'done'
            OR target.hashed_team_id IS DISTINCT FROM t.hashed_team_id
            OR (t.hashed_team_id IS NULL AND target.hashed_user_id IS DISTINCT FROM t.hashed_user_id))
      );
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION project_task_sync_task_changed()
RETURNS trigger AS $$
DECLARE dependent jsonb; changed_id text;
BEGIN
    changed_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.task_id ELSE NEW.task_id END;
    IF TG_OP = 'UPDATE' AND OLD.primary_chat_id IS NOT NULL AND NEW.primary_chat_id IS NULL THEN
        DELETE FROM user_task_key_wrappers WHERE key_type = 'chat'
            AND hashed_task_id = encode(digest(NEW.task_id, 'sha256'), 'hex')
            AND hashed_chat_id = encode(digest(OLD.primary_chat_id::text, 'sha256'), 'hex');
        DELETE FROM user_task_execution_contexts
            WHERE hashed_task_id = encode(digest(NEW.task_id, 'sha256'), 'hex')
              AND hashed_chat_id = encode(digest(OLD.primary_chat_id::text, 'sha256'), 'hex');
    END IF;
    -- Refresh dependent Task rows as well, so their embedded dependency states
    -- change without a worker fetching each dependency separately.
    IF TG_OP = 'DELETE' OR (TG_OP = 'UPDATE' AND NEW.status IS DISTINCT FROM OLD.status) THEN
        FOR dependent IN SELECT to_jsonb(t) FROM user_tasks t
            JOIN user_work_dependencies d ON d.source_id = t.task_id AND d.source_kind = 'task'
            WHERE d.target_kind = 'task' AND d.target_id = changed_id
            ORDER BY t.task_id
        LOOP
            PERFORM record_project_task_sync_change(dependent);
            PERFORM release_task_dependency_wait(dependent->>'task_id');
        END LOOP;
    END IF;
    IF TG_OP = 'DELETE' THEN
        PERFORM record_project_task_sync_change(to_jsonb(OLD));
        RETURN OLD;
    END IF;
    IF TG_OP = 'UPDATE' AND (OLD.hashed_user_id IS DISTINCT FROM NEW.hashed_user_id
        OR OLD.hashed_team_id IS DISTINCT FROM NEW.hashed_team_id) THEN
        -- The former workspace must receive a removal even after the record
        -- becomes inaccessible there. Never leave moved content in its cache.
        PERFORM record_project_task_sync_change(to_jsonb(OLD));
    END IF;
    PERFORM record_project_task_sync_change(to_jsonb(NEW),
        CASE WHEN TG_OP = 'UPDATE' THEN to_jsonb(OLD)->'linked_project_hashes' ELSE '[]'::jsonb END);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS project_task_sync_task_trigger ON user_tasks;
CREATE TRIGGER project_task_sync_task_trigger AFTER INSERT OR UPDATE OR DELETE ON user_tasks
FOR EACH ROW EXECUTE FUNCTION project_task_sync_task_changed();

CREATE OR REPLACE FUNCTION project_task_sync_activity_changed()
RETURNS trigger AS $$
DECLARE task_record jsonb; activity_record jsonb;
BEGIN
    activity_record := CASE WHEN TG_OP = 'DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
    SELECT to_jsonb(t) INTO task_record FROM user_tasks t
    WHERE t.task_id = activity_record->>'task_id';
    PERFORM record_project_task_sync_change(task_record);
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS project_task_sync_activity_trigger ON user_task_activity;
CREATE TRIGGER project_task_sync_activity_trigger AFTER INSERT OR UPDATE OR DELETE ON user_task_activity
FOR EACH ROW EXECUTE FUNCTION project_task_sync_activity_changed();

CREATE OR REPLACE FUNCTION project_task_sync_dependency_changed()
RETURNS trigger AS $$
DECLARE task_record jsonb; edge jsonb;
BEGIN
    IF TG_OP = 'UPDATE' AND OLD.source_kind = 'task' THEN
        SELECT to_jsonb(t) INTO task_record FROM user_tasks t WHERE t.task_id = OLD.source_id;
        PERFORM record_project_task_sync_change(task_record);
    END IF;
    edge := CASE WHEN TG_OP = 'DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
    IF edge->>'source_kind' = 'task' THEN
        SELECT to_jsonb(t) INTO task_record FROM user_tasks t WHERE t.task_id = edge->>'source_id';
        PERFORM record_project_task_sync_change(task_record);
        PERFORM release_task_dependency_wait(edge->>'source_id');
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS project_task_sync_dependency_trigger ON user_work_dependencies;
CREATE TRIGGER project_task_sync_dependency_trigger AFTER INSERT OR UPDATE OR DELETE ON user_work_dependencies
FOR EACH ROW EXECUTE FUNCTION project_task_sync_dependency_changed();

-- Confirmed external-chat deletion is durable integration metadata. Replaying
-- a deletion is idempotent, and a deleted chat cannot be claimed again later.
CREATE TABLE IF NOT EXISTS task_external_chat_deletions (
    scope text NOT NULL,
    provider text NOT NULL,
    lookup_hash text NOT NULL,
    event_id text NOT NULL,
    deleted_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (scope, provider, lookup_hash)
);

-- A conversation link is execution ownership. Even internal/direct DB callers
-- must release an existing link before another conversation can claim it.
CREATE OR REPLACE FUNCTION guard_task_conversation_replacement()
RETURNS trigger AS $$
DECLARE previous_owner text; next_owner text;
BEGIN
    IF NEW.external_chat_provider IS NOT NULL THEN
        -- Fence a new claim against a concurrently committed deletion receipt.
        PERFORM pg_advisory_xact_lock(hashtextextended(
            (CASE WHEN NEW.hashed_team_id IS NOT NULL THEN 'team:' || NEW.hashed_team_id ELSE 'personal:' || NEW.hashed_user_id END)
            || ':' || NEW.external_chat_provider || ':' || NEW.external_chat_lookup_hash, 0));
    END IF;
    IF NEW.external_chat_provider IS NOT NULL AND EXISTS (
        SELECT 1 FROM task_external_chat_deletions d
        WHERE d.scope = CASE WHEN NEW.hashed_team_id IS NOT NULL THEN 'team:' || NEW.hashed_team_id ELSE 'personal:' || NEW.hashed_user_id END
          AND d.provider = NEW.external_chat_provider AND d.lookup_hash = NEW.external_chat_lookup_hash
    ) THEN
        RAISE EXCEPTION 'TASK_CHAT_DELETED' USING ERRCODE = '23514';
    END IF;
    IF NEW.primary_chat_id IS NOT NULL AND NEW.external_chat_provider IS NOT NULL THEN
        RAISE EXCEPTION 'TASK_MULTIPLE_CONVERSATIONS' USING ERRCODE = '23514';
    END IF;
    IF NEW.status = 'blocked' AND NEW.assignee_identity = 'codex'
        AND NEW.blocked_reason_code = 'external_dependency'
        AND NEW.encrypted_blocked_reason IS NULL AND NEW.plan_id IS NULL
        AND EXISTS (SELECT 1 FROM user_work_dependencies d WHERE d.source_kind = 'task' AND d.source_id = NEW.task_id) THEN
        IF NOT EXISTS (
            SELECT 1 FROM user_work_dependencies d
            LEFT JOIN user_tasks target ON d.target_kind = 'task' AND target.task_id = d.target_id
            WHERE d.source_kind = 'task' AND d.source_id = NEW.task_id
              AND (d.target_kind <> 'task' OR target.task_id IS NULL OR target.status <> 'done'
                OR target.hashed_team_id IS DISTINCT FROM NEW.hashed_team_id
                OR (NEW.hashed_team_id IS NULL AND target.hashed_user_id IS DISTINCT FROM NEW.hashed_user_id))
        ) THEN
            NEW.status := 'todo'; NEW.queue_state := 'none';
            NEW.blocked_reason_code := NULL; NEW.ai_execution_state := NULL;
        END IF;
    END IF;
    IF TG_OP = 'INSERT' THEN RETURN NEW; END IF;
    previous_owner := COALESCE('openmates:' || OLD.primary_chat_id::text,
        OLD.external_chat_provider || ':' || OLD.external_chat_lookup_hash);
    next_owner := COALESCE('openmates:' || NEW.primary_chat_id::text,
        NEW.external_chat_provider || ':' || NEW.external_chat_lookup_hash);
    IF previous_owner IS NOT NULL AND next_owner IS NOT NULL AND previous_owner <> next_owner THEN
        RAISE EXCEPTION 'TASK_ALREADY_LINKED' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS user_tasks_conversation_owner_guard ON user_tasks;
CREATE TRIGGER user_tasks_conversation_owner_guard BEFORE INSERT OR UPDATE ON user_tasks
FOR EACH ROW EXECUTE FUNCTION guard_task_conversation_replacement();

-- Cleanup is part of confirmed deletion, never an archive/offline heuristic.
-- Keep master/team/project key wrappers so work remains readable after unlink.
CREATE OR REPLACE FUNCTION unlink_work_on_chat_deletion()
RETURNS trigger AS $$
BEGIN
    UPDATE user_tasks SET primary_chat_id = NULL, hashed_primary_chat_id = NULL,
        status = CASE WHEN status = 'in_progress' THEN 'todo' ELSE status END,
        queue_state = 'none', ai_execution_state = NULL,
        version = version + 1, updated_at = extract(epoch FROM now())::bigint
    WHERE primary_chat_id = OLD.id;
    UPDATE user_plans SET primary_chat_id = NULL, hashed_primary_chat_id = NULL,
        status = CASE WHEN status IN ('active', 'executing', 'running_checks', 'blocked')
            THEN 'awaiting_confirmation' ELSE status END,
        continuation_state = 'paused', version = version + 1,
        updated_at = extract(epoch FROM now())::bigint
    WHERE primary_chat_id = OLD.id;
    DELETE FROM user_task_execution_contexts WHERE hashed_chat_id = encode(digest(OLD.id::text, 'sha256'), 'hex');
    DELETE FROM user_plan_execution_contexts WHERE hashed_primary_chat_id = encode(digest(OLD.id::text, 'sha256'), 'hex');
    DELETE FROM user_task_key_wrappers WHERE key_type = 'chat' AND hashed_chat_id = encode(digest(OLD.id::text, 'sha256'), 'hex');
    DELETE FROM user_plan_key_wrappers WHERE key_type = 'chat' AND hashed_chat_id = encode(digest(OLD.id::text, 'sha256'), 'hex');
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS chats_unlink_work_trigger ON chats;
CREATE TRIGGER chats_unlink_work_trigger BEFORE DELETE ON chats
FOR EACH ROW EXECUTE FUNCTION unlink_work_on_chat_deletion();

-- Wrapper changes can commit independently of the Task row. Journal those
-- commits as well, so a device can recover from temporarily missing key access.
CREATE OR REPLACE FUNCTION project_task_sync_wrapper_changed()
RETURNS trigger AS $$
DECLARE task_record jsonb; old_hash text; new_hash text;
BEGIN
    IF TG_OP <> 'INSERT' THEN old_hash := OLD.hashed_task_id; END IF;
    IF TG_OP <> 'DELETE' THEN new_hash := NEW.hashed_task_id; END IF;
    FOR task_record IN SELECT to_jsonb(t) FROM user_tasks t
        WHERE encode(digest(t.task_id, 'sha256'), 'hex') IN (old_hash, new_hash)
        ORDER BY t.task_id
    LOOP
        PERFORM record_project_task_sync_change(task_record);
    END LOOP;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS project_task_sync_wrapper_trigger ON user_task_key_wrappers;
CREATE TRIGGER project_task_sync_wrapper_trigger AFTER INSERT OR UPDATE OR DELETE ON user_task_key_wrappers
FOR EACH ROW EXECUTE FUNCTION project_task_sync_wrapper_changed();
