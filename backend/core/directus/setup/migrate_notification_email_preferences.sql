-- Idempotent default-on transition for optional notification email.
-- Explicit user opt-outs, existing category false values, and global blocks win.
-- The verified contact address remains Vault ciphertext in account_contact_emails.
ALTER TABLE public.directus_users
    ADD COLUMN IF NOT EXISTS email_notification_preference_choices jsonb NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE public.directus_users
    ALTER COLUMN email_notifications_enabled SET DEFAULT true;

ALTER TABLE public.directus_users
    ALTER COLUMN email_notification_preferences SET DEFAULT
        '{"aiResponses":true,"workflowRuns":true,"includeContent":false,"backupReminder":false,"webhookChats":false}'::jsonb;

-- A master=false value without an explicit user choice is the old schema
-- default. Activate the two requested categories and keep unrelated mail off.
-- Existing aiResponses/workflowRuns=false values and explicit user false choices
-- remain false. Unknown preference keys survive the JSON merge.
WITH candidates AS (
    SELECT u.id,
           COALESCE(u.email_notification_preferences::jsonb, '{}'::jsonb) AS prefs,
           COALESCE(u.email_notification_preference_choices::jsonb, '{}'::jsonb) AS choices
    FROM public.directus_users AS u
    WHERE u.email_notifications_enabled IS NOT TRUE
      AND NOT COALESCE((
          COALESCE(u.email_notification_preference_choices::jsonb, '{}'::jsonb) #>> '{enabled,source}' = 'user'
          AND COALESCE(u.email_notification_preference_choices::jsonb, '{}'::jsonb) #>> '{enabled,value}' = 'false'
      ), false)
      AND NOT EXISTS (
          SELECT 1 FROM public.account_contact_emails AS contact
          JOIN public.ignored_emails AS blocked
            ON blocked.hashed_email = contact.hashed_email
          WHERE contact.user_id = u.id::text
      )
)
UPDATE public.directus_users AS u
SET email_notifications_enabled = true,
    email_notification_preferences = c.prefs || jsonb_build_object(
        'aiResponses', CASE
            WHEN c.choices #>> '{aiResponses,source}' = 'user'
             AND c.choices #>> '{aiResponses,value}' = 'false' THEN false
            ELSE c.prefs->'aiResponses' IS DISTINCT FROM 'false'::jsonb
        END,
        'workflowRuns', CASE
            WHEN c.choices #>> '{workflowRuns,source}' = 'user'
             AND c.choices #>> '{workflowRuns,value}' = 'false' THEN false
            ELSE c.prefs->'workflowRuns' IS DISTINCT FROM 'false'::jsonb
        END,
        'includeContent', COALESCE((c.choices #>> '{includeContent,source}' = 'user' AND c.choices #>> '{includeContent,value}' = 'true'), false),
        'backupReminder', false,
        'webhookChats', false
    )
FROM candidates AS c
WHERE u.id = c.id;

-- Accounts that already opted into optional email gain only the new Workflow
-- category. Existing false and explicit user false choices remain disabled.
UPDATE public.directus_users AS u
SET email_notification_preferences = COALESCE(u.email_notification_preferences::jsonb, '{}'::jsonb)
    || jsonb_build_object('workflowRuns',
        NOT COALESCE((
            COALESCE(u.email_notification_preference_choices::jsonb, '{}'::jsonb) #>> '{workflowRuns,source}' = 'user'
            AND COALESCE(u.email_notification_preference_choices::jsonb, '{}'::jsonb) #>> '{workflowRuns,value}' = 'false'
        ), false)
    )
WHERE u.email_notifications_enabled IS TRUE
  AND NOT COALESCE(u.email_notification_preferences::jsonb, '{}'::jsonb) ? 'workflowRuns';

UPDATE public.directus_users AS u
SET email_notification_preferences = COALESCE(u.email_notification_preferences::jsonb, '{}'::jsonb)
    || '{"aiResponses":false}'::jsonb
WHERE u.email_notification_preference_choices::jsonb #>> '{aiResponses,source}' = 'user'
  AND u.email_notification_preference_choices::jsonb #>> '{aiResponses,value}' = 'false'
  AND COALESCE(u.email_notification_preferences::jsonb, '{}'::jsonb)->'aiResponses'
      IS DISTINCT FROM 'false'::jsonb;

UPDATE public.directus_users AS u
SET email_notification_preferences = COALESCE(u.email_notification_preferences::jsonb, '{}'::jsonb)
    || '{"workflowRuns":false}'::jsonb
WHERE u.email_notification_preference_choices::jsonb #>> '{workflowRuns,source}' = 'user'
  AND u.email_notification_preference_choices::jsonb #>> '{workflowRuns,value}' = 'false'
  AND COALESCE(u.email_notification_preferences::jsonb, '{}'::jsonb)->'workflowRuns'
      IS DISTINCT FROM 'false'::jsonb;

-- Resolve any inconsistent old row in favor of recorded explicit user opt-out.
UPDATE public.directus_users AS u
SET email_notifications_enabled = false
WHERE u.email_notifications_enabled IS TRUE
  AND COALESCE(u.email_notification_preference_choices::jsonb, '{}'::jsonb) #>> '{enabled,source}' = 'user'
  AND COALESCE(u.email_notification_preference_choices::jsonb, '{}'::jsonb) #>> '{enabled,value}' = 'false';

-- The exact hashed-address match is enforceable in SQL. The send-time helper
-- additionally hashes the decrypted normalized address, covering old casing.
UPDATE public.directus_users AS u
SET email_notifications_enabled = false
WHERE u.email_notifications_enabled IS TRUE
  AND EXISTS (
      SELECT 1 FROM public.account_contact_emails AS contact
      JOIN public.ignored_emails AS blocked
        ON blocked.hashed_email = contact.hashed_email
      WHERE contact.user_id = u.id::text
  );
