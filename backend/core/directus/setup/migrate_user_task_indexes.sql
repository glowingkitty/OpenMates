-- User task hot-path indexes.
-- These keep task list/board/retention queries bounded as completed tasks and
-- key wrappers grow. All statements are idempotent for Directus setup reruns.

CREATE INDEX IF NOT EXISTS user_tasks_owner_status_position_idx
    ON user_tasks (hashed_user_id, status, position, created_at);

CREATE INDEX IF NOT EXISTS user_tasks_owner_priority_idx
    ON user_tasks (hashed_user_id, priority DESC, position, created_at);

CREATE INDEX IF NOT EXISTS user_tasks_owner_completed_idx
    ON user_tasks (hashed_user_id, completed_at)
    WHERE completed_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS user_tasks_due_ai_idx
    ON user_tasks (due_at, position, created_at)
    WHERE assignee_type = 'ai' AND due_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS user_tasks_owner_chat_idx
    ON user_tasks (hashed_user_id, hashed_primary_chat_id, position, created_at)
    WHERE hashed_primary_chat_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS user_tasks_project_hashes_gin_idx
    ON user_tasks USING GIN ((linked_project_hashes::jsonb) jsonb_path_ops);

CREATE INDEX IF NOT EXISTS user_tasks_label_hashes_gin_idx
    ON user_tasks USING GIN ((label_hashes::jsonb) jsonb_path_ops);

CREATE INDEX IF NOT EXISTS user_task_key_wrappers_task_owner_idx
    ON user_task_key_wrappers (hashed_task_id, hashed_user_id);

CREATE INDEX IF NOT EXISTS user_task_activity_task_created_idx
    ON user_task_activity (task_id, created_at);

CREATE INDEX IF NOT EXISTS user_task_archives_owner_archived_idx
    ON user_task_archives (hashed_user_id, archived_at DESC);
