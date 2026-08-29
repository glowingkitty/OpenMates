-- Durable graph integrity for encrypted Plan/Task dependency metadata.
CREATE UNIQUE INDEX IF NOT EXISTS user_work_dependencies_source_target_uq
    ON public.user_work_dependencies (source_ref, target_ref);
