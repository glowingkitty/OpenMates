-- Durable graph integrity for encrypted Plan/Task dependency metadata.
CREATE UNIQUE INDEX IF NOT EXISTS user_work_dependencies_source_target_uq
    ON public.user_work_dependencies (source_ref, target_ref);

-- Plans V1 is unreleased: remove superseded Plan pointers, duplicate key storage,
-- and the retired Plan-step collection without compatibility preservation.
DELETE FROM public.directus_relations
WHERE many_collection = 'user_plan_steps'
   OR one_collection = 'user_plan_steps'
   OR (many_collection = 'user_plans' AND many_field IN (
       'encrypted_summary',
       'encrypted_current_focus',
       'current_phase_id',
       'current_step_id',
       'current_task_id',
       'encrypted_plan_key'
   ))
   OR (many_collection = 'user_tasks' AND many_field = 'plan_step_id')
   OR (many_collection = 'user_plan_acceptance_criteria' AND many_field = 'linked_step_ids')
   OR (many_collection = 'user_plan_assumptions' AND many_field = 'linked_step_ids');

DELETE FROM public.directus_fields
WHERE collection = 'user_plan_steps'
   OR (collection = 'user_plans' AND field IN (
       'encrypted_summary',
       'encrypted_current_focus',
       'current_phase_id',
       'current_step_id',
       'current_task_id',
       'encrypted_plan_key'
   ))
   OR (collection = 'user_tasks' AND field = 'plan_step_id')
   OR (collection = 'user_plan_acceptance_criteria' AND field = 'linked_step_ids')
   OR (collection = 'user_plan_assumptions' AND field = 'linked_step_ids');

DELETE FROM public.directus_collections WHERE collection = 'user_plan_steps';

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
