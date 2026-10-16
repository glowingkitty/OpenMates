-- Read-only aggregate preview. Returns counts only; no account identifiers or addresses.
-- Run before the migration to estimate the legacy default-on transition.
WITH legacy AS (
    SELECT u.id, u.hashed_email,
           COALESCE(to_jsonb(u)->'email_notification_preference_choices', '{}'::jsonb) AS choices
    FROM public.directus_users AS u
    WHERE u.email_notifications_enabled IS NOT TRUE
), classified AS (
    SELECT l.id,
           (l.choices #>> '{enabled,source}' = 'user'
            AND l.choices #>> '{enabled,value}' = 'false') AS explicit_opt_out,
           EXISTS (
               SELECT 1 FROM public.account_contact_emails AS contact
               WHERE contact.user_id = l.id::text
                 AND contact.hashed_email = l.hashed_email
                 AND contact.purpose = 'account_lifecycle'
                 AND contact.verified_at IS NOT NULL
                 AND contact.encrypted_email_address IS NOT NULL
           ) AS verified_contact,
           EXISTS (
               SELECT 1 FROM public.account_contact_emails AS contact
               JOIN public.ignored_emails AS blocked
                 ON blocked.hashed_email = contact.hashed_email
               WHERE contact.user_id = l.id::text
           ) AS blocked_exact_hash
    FROM legacy AS l
)
SELECT COUNT(*) AS legacy_master_off,
       COUNT(*) FILTER (WHERE explicit_opt_out) AS explicit_master_opt_out,
       COUNT(*) FILTER (WHERE blocked_exact_hash) AS global_block_exact_hash,
       COUNT(*) FILTER (
           WHERE NOT COALESCE(explicit_opt_out, false)
             AND NOT blocked_exact_hash
       ) AS default_on_candidates,
       COUNT(*) FILTER (
           WHERE NOT COALESCE(explicit_opt_out, false)
             AND NOT blocked_exact_hash
             AND verified_contact
       ) AS candidates_with_verified_contact,
       COUNT(*) FILTER (
           WHERE NOT COALESCE(explicit_opt_out, false)
             AND NOT blocked_exact_hash
             AND NOT verified_contact
       ) AS candidates_missing_verified_contact
FROM classified;
