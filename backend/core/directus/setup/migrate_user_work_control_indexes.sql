-- Durable graph integrity for encrypted Plan/Task dependency metadata.
CREATE UNIQUE INDEX IF NOT EXISTS user_work_dependencies_source_target_uq
    ON public.user_work_dependencies (source_ref, target_ref);

-- Plans V1 is unreleased: remove superseded Plan pointers, duplicate key storage,
-- and the retired Plan-step collection without compatibility preservation.
ALTER TABLE IF EXISTS public.user_plans
    DROP COLUMN IF EXISTS encrypted_summary,
    DROP COLUMN IF EXISTS encrypted_current_focus,
    DROP COLUMN IF EXISTS current_phase_id,
    DROP COLUMN IF EXISTS current_step_id,
    DROP COLUMN IF EXISTS current_task_id,
    DROP COLUMN IF EXISTS encrypted_plan_key;
ALTER TABLE IF EXISTS public.user_tasks DROP COLUMN IF EXISTS plan_step_id;
ALTER TABLE IF EXISTS public.user_plan_acceptance_criteria DROP COLUMN IF EXISTS linked_step_ids;
ALTER TABLE IF EXISTS public.user_plan_assumptions DROP COLUMN IF EXISTS linked_step_ids;
DROP TABLE IF EXISTS public.user_plan_steps;
