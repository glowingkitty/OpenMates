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
