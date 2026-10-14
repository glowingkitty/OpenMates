-- Internal owner aggregate. Every writer, including Directus admin/import and SQL,
-- increments in the same transaction; encrypted Team memories never enter it.
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE TABLE IF NOT EXISTS personal_privacy_generations (
  owner_hash varchar(64) PRIMARY KEY,
  epoch uuid NOT NULL DEFAULT gen_random_uuid(),
  generation bigint NOT NULL DEFAULT 0 CHECK (generation >= 0)
);
-- Counter rollback starts a new epoch, so restoring/resetting a clock cannot
-- acknowledge an older prepared bundle with the same opaque token.
CREATE OR REPLACE FUNCTION personal_privacy_generation_reset()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.generation <= OLD.generation THEN NEW.epoch := gen_random_uuid(); END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS personal_privacy_clock_reset ON personal_privacy_generations;
CREATE TRIGGER personal_privacy_clock_reset BEFORE UPDATE ON personal_privacy_generations
FOR EACH ROW EXECUTE FUNCTION personal_privacy_generation_reset();
CREATE OR REPLACE FUNCTION bump_personal_privacy_generation(owner text)
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
  IF owner IS NULL OR owner = '' THEN RETURN; END IF;
  INSERT INTO personal_privacy_generations(owner_hash, generation) VALUES(owner, 1)
  ON CONFLICT(owner_hash) DO UPDATE SET generation = personal_privacy_generations.generation + 1;
END $$;
CREATE OR REPLACE FUNCTION personal_privacy_memory_changed()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE old_owner text; new_owner text;
BEGIN
  IF TG_OP <> 'INSERT' AND OLD.hashed_team_id IS NULL THEN old_owner := OLD.hashed_user_id; END IF;
  IF TG_OP <> 'DELETE' AND NEW.hashed_team_id IS NULL THEN new_owner := NEW.hashed_user_id; END IF;
  -- Deterministic order prevents owner-transfer lock inversion.
  IF old_owner IS NOT NULL AND new_owner IS NOT NULL AND old_owner <> new_owner THEN
    PERFORM bump_personal_privacy_generation(LEAST(old_owner, new_owner));
    PERFORM bump_personal_privacy_generation(GREATEST(old_owner, new_owner));
  ELSE
    PERFORM bump_personal_privacy_generation(COALESCE(new_owner, old_owner));
  END IF;
  RETURN NULL;
END $$;
CREATE OR REPLACE FUNCTION personal_privacy_settings_changed()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'INSERT' OR NEW.encrypted_settings IS DISTINCT FROM OLD.encrypted_settings THEN
    PERFORM bump_personal_privacy_generation(encode(digest(NEW.id::text, 'sha256'), 'hex'));
  END IF;
  RETURN NULL;
END $$;
CREATE OR REPLACE FUNCTION personal_privacy_memories_truncated()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  UPDATE personal_privacy_generations SET epoch = gen_random_uuid(), generation = 0;
  RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS personal_privacy_memory_generation ON user_app_settings_and_memories;
CREATE TRIGGER personal_privacy_memory_generation AFTER INSERT OR UPDATE OR DELETE
ON user_app_settings_and_memories FOR EACH ROW EXECUTE FUNCTION personal_privacy_memory_changed();
DROP TRIGGER IF EXISTS personal_privacy_settings_generation ON directus_users;
CREATE TRIGGER personal_privacy_settings_generation AFTER INSERT OR UPDATE OF encrypted_settings
ON directus_users FOR EACH ROW EXECUTE FUNCTION personal_privacy_settings_changed();
DROP TRIGGER IF EXISTS personal_privacy_memory_truncate ON user_app_settings_and_memories;
CREATE TRIGGER personal_privacy_memory_truncate AFTER TRUNCATE
ON user_app_settings_and_memories FOR EACH STATEMENT EXECUTE FUNCTION personal_privacy_memories_truncated();

-- Schema initialization/restore is an explicit epoch reset. A restored dump must
-- run this initializer before first-party reuse is enabled; old tokens cannot
-- survive that boundary even when a backup restored the previous counter.
UPDATE personal_privacy_generations SET epoch = gen_random_uuid(), generation = 0;
