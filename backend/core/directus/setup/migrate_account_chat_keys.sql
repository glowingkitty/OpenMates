-- Account chat-key backups are keyed by SHA256(user ID), so Directus cannot
-- cascade them through a foreign key. Delete in the same PostgreSQL transaction
-- as directus_users: a failed account DELETE leaves the immutable backup intact.
-- Setup applies this after importing the account_chat_keys Directus collection.
-- The unique owner index also fences concurrent first-device registration.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE UNIQUE INDEX IF NOT EXISTS account_chat_keys_owner_uq
    ON account_chat_keys (hashed_user_id);

CREATE OR REPLACE FUNCTION delete_account_chat_key_backup_with_user()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    DELETE FROM account_chat_keys
    WHERE hashed_user_id = encode(digest(OLD.id::text, 'sha256'), 'hex');
    RETURN OLD;
END;
$$;

DROP TRIGGER IF EXISTS account_chat_keys_user_delete ON directus_users;
CREATE TRIGGER account_chat_keys_user_delete
    BEFORE DELETE ON directus_users
    FOR EACH ROW EXECUTE FUNCTION delete_account_chat_key_backup_with_user();
