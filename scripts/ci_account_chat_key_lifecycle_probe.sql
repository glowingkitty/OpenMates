-- Run only in a fresh isolated CI schema consumer after cms-setup.
-- Use a synthetic account and an opaque placeholder backup.
-- The inner exception simulates a failed account DELETE after the trigger ran.
-- PostgreSQL must roll both the user and backup deletion back together.
-- The final DELETE then commits and must remove both rows.
DO $probe$
DECLARE
    test_user_id uuid := gen_random_uuid();
    test_user_hash text;
    delete_reached boolean := false;
BEGIN
    test_user_hash := encode(digest(test_user_id::text, 'sha256'), 'hex');
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger AS trigger_row
        JOIN pg_class AS table_row ON table_row.oid = trigger_row.tgrelid
        WHERE table_row.relname = 'directus_users'
          AND trigger_row.tgname = 'account_chat_keys_user_delete'
          AND trigger_row.tgenabled = 'O'
    ) THEN
        RAISE EXCEPTION 'Account chat-key delete trigger missing';
    END IF;

    INSERT INTO directus_users (id, email, status)
    VALUES (test_user_id, test_user_id::text || '@example.invalid', 'active');
    INSERT INTO account_chat_keys (
        id, hashed_user_id, key_id, public_key, encrypted_private_key, algorithm, version
    ) VALUES (
        gen_random_uuid(), test_user_hash, repeat('a', 64), repeat('B', 43),
        'synthetic-ci-ciphertext', 'x25519-xsalsa20poly1305', 1
    );

    BEGIN
        DELETE FROM directus_users WHERE id = test_user_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Synthetic user delete did not execute';
        END IF;
        IF EXISTS (SELECT 1 FROM account_chat_keys WHERE hashed_user_id = test_user_hash) THEN
            RAISE EXCEPTION 'Account key survived user DELETE';
        END IF;
        delete_reached := true;
        RAISE EXCEPTION 'simulated account delete failure';
    EXCEPTION WHEN raise_exception THEN
        IF NOT delete_reached THEN
            RAISE;
        END IF;
    END;

    IF NOT EXISTS (SELECT 1 FROM directus_users WHERE id = test_user_id)
       OR NOT EXISTS (SELECT 1 FROM account_chat_keys WHERE hashed_user_id = test_user_hash) THEN
        RAISE EXCEPTION 'Failed user DELETE did not restore user and key';
    END IF;

    DELETE FROM directus_users WHERE id = test_user_id;
    IF EXISTS (SELECT 1 FROM directus_users WHERE id = test_user_id)
       OR EXISTS (SELECT 1 FROM account_chat_keys WHERE hashed_user_id = test_user_hash) THEN
        RAISE EXCEPTION 'Committed user DELETE did not remove account key';
    END IF;
END;
$probe$;
