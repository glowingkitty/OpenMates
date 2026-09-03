-- User task hot-path indexes.
-- These keep task list/board/retention queries bounded as completed tasks and
-- key wrappers grow. All statements are idempotent for Directus setup reruns.

CREATE INDEX IF NOT EXISTS user_tasks_owner_status_position_idx
    ON user_tasks (hashed_user_id, status, position, created_at);

CREATE INDEX IF NOT EXISTS user_tasks_owner_priority_idx
    ON user_tasks (hashed_user_id, priority DESC, position, created_at);

CREATE INDEX IF NOT EXISTS user_tasks_team_admission_idx
    ON user_tasks (hashed_team_id, status, assignee_type, priority DESC, position, created_at)
    WHERE hashed_team_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS user_tasks_ai_admission_idx
    ON user_tasks (status, assignee_type, due_at, priority DESC, position, created_at)
    WHERE assignee_type = 'ai' AND status IN ('todo', 'in_progress', 'blocked');

CREATE INDEX IF NOT EXISTS user_tasks_owner_completed_idx
    ON user_tasks (hashed_user_id, completed_at)
    WHERE completed_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS user_tasks_due_ai_idx
    ON user_tasks (due_at, position, created_at)
    WHERE assignee_type = 'ai' AND due_at IS NOT NULL;

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

CREATE INDEX IF NOT EXISTS user_task_archives_owner_archived_idx
    ON user_task_archives (hashed_user_id, archived_at DESC);
