-- Add exact Personal/Team ownership to Projects and every durable child row.
-- The migration is idempotent, copies existing Personal ownership into actor
-- fields, and derives Team child ownership from the parent Project.

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

ALTER TABLE public.projects
    ADD COLUMN IF NOT EXISTS created_by_user_hash varchar(255);
ALTER TABLE public.project_folders
    ADD COLUMN IF NOT EXISTS hashed_team_id varchar(255),
    ADD COLUMN IF NOT EXISTS created_by_user_hash varchar(255);
ALTER TABLE public.project_items
    ADD COLUMN IF NOT EXISTS hashed_team_id varchar(255),
    ADD COLUMN IF NOT EXISTS attached_by_user_hash varchar(255);
ALTER TABLE public.project_sources
    ADD COLUMN IF NOT EXISTS hashed_team_id varchar(255),
    ADD COLUMN IF NOT EXISTS attached_by_user_hash varchar(255);
ALTER TABLE public.project_settings
    ADD COLUMN IF NOT EXISTS hashed_team_id varchar(255),
    ADD COLUMN IF NOT EXISTS updated_by_user_hash varchar(255);

ALTER TABLE public.projects ALTER COLUMN hashed_user_id DROP NOT NULL;
ALTER TABLE public.project_folders ALTER COLUMN hashed_user_id DROP NOT NULL;
ALTER TABLE public.project_items ALTER COLUMN hashed_user_id DROP NOT NULL;
ALTER TABLE public.project_sources ALTER COLUMN hashed_user_id DROP NOT NULL;
ALTER TABLE public.project_settings ALTER COLUMN hashed_user_id DROP NOT NULL;
ALTER TABLE public.project_key_wrappers ALTER COLUMN hashed_user_id DROP NOT NULL;

UPDATE public.projects
SET created_by_user_hash = COALESCE(created_by_user_hash, hashed_user_id)
WHERE created_by_user_hash IS NULL;

UPDATE public.project_folders AS child
SET hashed_user_id = parent.hashed_user_id,
    hashed_team_id = parent.hashed_team_id,
    created_by_user_hash = COALESCE(child.created_by_user_hash, child.hashed_user_id, parent.created_by_user_hash)
FROM public.projects AS parent
WHERE child.hashed_project_id = encode(digest(parent.project_id, 'sha256'), 'hex');

UPDATE public.project_items AS child
SET hashed_user_id = parent.hashed_user_id,
    hashed_team_id = parent.hashed_team_id,
    attached_by_user_hash = COALESCE(child.attached_by_user_hash, child.hashed_user_id, parent.created_by_user_hash)
FROM public.projects AS parent
WHERE child.hashed_project_id = encode(digest(parent.project_id, 'sha256'), 'hex');

UPDATE public.project_sources AS child
SET hashed_user_id = parent.hashed_user_id,
    hashed_team_id = parent.hashed_team_id,
    attached_by_user_hash = COALESCE(child.attached_by_user_hash, child.hashed_user_id, parent.created_by_user_hash)
FROM public.projects AS parent
WHERE child.hashed_project_id = encode(digest(parent.project_id, 'sha256'), 'hex');

UPDATE public.project_settings AS child
SET hashed_user_id = parent.hashed_user_id,
    hashed_team_id = parent.hashed_team_id,
    updated_by_user_hash = COALESCE(child.updated_by_user_hash, child.hashed_user_id, parent.created_by_user_hash)
FROM public.projects AS parent
WHERE child.hashed_project_id = encode(digest(parent.project_id, 'sha256'), 'hex');

UPDATE public.projects SET hashed_user_id = NULL WHERE hashed_team_id IS NOT NULL;
UPDATE public.project_folders SET hashed_user_id = NULL WHERE hashed_team_id IS NOT NULL;
UPDATE public.project_items SET hashed_user_id = NULL WHERE hashed_team_id IS NOT NULL;
UPDATE public.project_sources SET hashed_user_id = NULL WHERE hashed_team_id IS NOT NULL;
UPDATE public.project_settings SET hashed_user_id = NULL WHERE hashed_team_id IS NOT NULL;
UPDATE public.project_key_wrappers SET hashed_user_id = NULL WHERE hashed_team_id IS NOT NULL;

ALTER TABLE public.projects ALTER COLUMN created_by_user_hash SET NOT NULL;
ALTER TABLE public.project_folders ALTER COLUMN created_by_user_hash SET NOT NULL;
ALTER TABLE public.project_items ALTER COLUMN attached_by_user_hash SET NOT NULL;
ALTER TABLE public.project_sources ALTER COLUMN attached_by_user_hash SET NOT NULL;
ALTER TABLE public.project_settings ALTER COLUMN updated_by_user_hash SET NOT NULL;

DO $$
DECLARE
    current_table text;
    constraint_name text;
BEGIN
    FOREACH current_table IN ARRAY ARRAY[
        'projects', 'project_folders', 'project_items', 'project_sources',
        'project_settings', 'project_key_wrappers'
    ]
    LOOP
        constraint_name := CASE
            WHEN current_table = 'projects' THEN 'project_owner_context_check'
            ELSE current_table || '_owner_context_check'
        END;
        IF NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_constraint AS constraint_record
            JOIN pg_catalog.pg_class AS relation ON relation.oid = constraint_record.conrelid
            JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'public'
              AND relation.relname = current_table
              AND constraint_record.conname = constraint_name
        ) THEN
            EXECUTE format(
                'ALTER TABLE public.%I ADD CONSTRAINT %I CHECK (num_nonnulls(hashed_user_id, hashed_team_id) = 1) NOT VALID',
                current_table,
                constraint_name
            );
        END IF;
    END LOOP;
END $$;

ALTER TABLE public.projects VALIDATE CONSTRAINT project_owner_context_check;
ALTER TABLE public.project_folders VALIDATE CONSTRAINT project_folders_owner_context_check;
ALTER TABLE public.project_items VALIDATE CONSTRAINT project_items_owner_context_check;
ALTER TABLE public.project_sources VALIDATE CONSTRAINT project_sources_owner_context_check;
ALTER TABLE public.project_settings VALIDATE CONSTRAINT project_settings_owner_context_check;
ALTER TABLE public.project_key_wrappers VALIDATE CONSTRAINT project_key_wrappers_owner_context_check;

CREATE UNIQUE INDEX IF NOT EXISTS project_sources_personal_source_uq
    ON public.project_sources (hashed_user_id, source_id)
    WHERE hashed_team_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS project_sources_team_source_uq
    ON public.project_sources (hashed_team_id, source_id)
    WHERE hashed_team_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS project_folders_team_project_idx
    ON public.project_folders (hashed_team_id, hashed_project_id);
CREATE INDEX IF NOT EXISTS project_items_team_project_idx
    ON public.project_items (hashed_team_id, hashed_project_id);
CREATE INDEX IF NOT EXISTS project_settings_team_project_idx
    ON public.project_settings (hashed_team_id, hashed_project_id);

COMMIT;
