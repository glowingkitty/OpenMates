-- Add encrypted object slug metadata and owner/team scoped duplicate guards.
-- Plaintext private slugs are never stored; clients submit only encrypted_slug
-- and a keyed slug_lookup_hash for privacy-preserving duplicate rejection.

BEGIN;

ALTER TABLE public.workflows
    ADD COLUMN IF NOT EXISTS encrypted_slug text,
    ADD COLUMN IF NOT EXISTS slug_lookup_hash varchar(255);
ALTER TABLE public.projects
    ADD COLUMN IF NOT EXISTS encrypted_slug text,
    ADD COLUMN IF NOT EXISTS slug_lookup_hash varchar(255);
ALTER TABLE public.user_tasks
    ADD COLUMN IF NOT EXISTS encrypted_slug text,
    ADD COLUMN IF NOT EXISTS slug_lookup_hash varchar(255);
ALTER TABLE public.user_plans
    ADD COLUMN IF NOT EXISTS encrypted_slug text,
    ADD COLUMN IF NOT EXISTS slug_lookup_hash varchar(255);
ALTER TABLE public.chats
    ADD COLUMN IF NOT EXISTS encrypted_slug text,
    ADD COLUMN IF NOT EXISTS slug_lookup_hash varchar(255);

CREATE UNIQUE INDEX IF NOT EXISTS workflows_personal_slug_hash_uq
    ON public.workflows (hashed_user_id, slug_lookup_hash)
    WHERE hashed_team_id IS NULL AND slug_lookup_hash IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS workflows_team_slug_hash_uq
    ON public.workflows (hashed_team_id, slug_lookup_hash)
    WHERE hashed_team_id IS NOT NULL AND slug_lookup_hash IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS projects_personal_slug_hash_uq
    ON public.projects (hashed_user_id, slug_lookup_hash)
    WHERE hashed_team_id IS NULL AND slug_lookup_hash IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS projects_team_slug_hash_uq
    ON public.projects (hashed_team_id, slug_lookup_hash)
    WHERE hashed_team_id IS NOT NULL AND slug_lookup_hash IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS user_tasks_personal_slug_hash_uq
    ON public.user_tasks (hashed_user_id, slug_lookup_hash)
    WHERE hashed_team_id IS NULL AND slug_lookup_hash IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS user_tasks_team_slug_hash_uq
    ON public.user_tasks (hashed_team_id, slug_lookup_hash)
    WHERE hashed_team_id IS NOT NULL AND slug_lookup_hash IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS user_plans_personal_slug_hash_uq
    ON public.user_plans (hashed_user_id, slug_lookup_hash)
    WHERE hashed_team_id IS NULL AND slug_lookup_hash IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS user_plans_team_slug_hash_uq
    ON public.user_plans (hashed_team_id, slug_lookup_hash)
    WHERE hashed_team_id IS NOT NULL AND slug_lookup_hash IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS chats_personal_slug_hash_uq
    ON public.chats (hashed_user_id, slug_lookup_hash)
    WHERE hashed_team_id IS NULL AND slug_lookup_hash IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS chats_team_slug_hash_uq
    ON public.chats (hashed_team_id, slug_lookup_hash)
    WHERE hashed_team_id IS NOT NULL AND slug_lookup_hash IS NOT NULL;

COMMIT;
