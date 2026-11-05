-- Additive indexes; row-locked head publication assigns revision numbers.
CREATE UNIQUE INDEX IF NOT EXISTS user_specification_revision_number_uq
    ON public.user_specification_revisions (specification_id, revision_number);
CREATE INDEX IF NOT EXISTS user_specification_personal_project_idx
    ON public.user_specifications (hashed_user_id, home_project_hash, specification_id)
    WHERE hashed_team_id IS NULL;
CREATE INDEX IF NOT EXISTS user_specification_team_project_idx
    ON public.user_specifications (hashed_team_id, home_project_hash, specification_id)
    WHERE hashed_team_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS user_specification_revision_owner_idx
    ON public.user_specification_revisions (hashed_user_id, hashed_team_id, home_project_hash);

-- Preserve documents and access through the existing Project move transaction,
-- including its rollback. The Project key remains the content-key context;
-- its authenticated move already supplies the new Team Project key wrapper.
CREATE OR REPLACE FUNCTION sync_project_specification_scope() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE project_hash text := encode(sha256(convert_to(NEW.project_id, 'UTF8')), 'hex');
BEGIN
    UPDATE public.user_specifications AS s
    SET hashed_user_id = NEW.hashed_user_id, hashed_team_id = NEW.hashed_team_id,
        key_wrappers = CASE WHEN NEW.hashed_team_id IS NOT NULL THEN
            (SELECT COALESCE(jsonb_agg(wrapper), '[]'::jsonb)
             FROM jsonb_array_elements(s.key_wrappers::jsonb) AS wrapper
             WHERE wrapper->>'key_type' = 'project'
               AND wrapper->>'hashed_project_id' = project_hash)
            ELSE s.key_wrappers::jsonb END
    WHERE s.home_project_hash = project_hash;
    UPDATE public.user_specification_revisions
    SET hashed_user_id = NEW.hashed_user_id, hashed_team_id = NEW.hashed_team_id
    WHERE home_project_hash = project_hash;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS projects_specification_scope ON public.projects;
CREATE TRIGGER projects_specification_scope
AFTER UPDATE OF hashed_user_id, hashed_team_id ON public.projects
FOR EACH ROW WHEN (OLD.hashed_user_id IS DISTINCT FROM NEW.hashed_user_id
                   OR OLD.hashed_team_id IS DISTINCT FROM NEW.hashed_team_id)
EXECUTE FUNCTION sync_project_specification_scope();
