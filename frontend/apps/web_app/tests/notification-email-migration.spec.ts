// proof-video: not_required reason=database_migration_contract
import { execFileSync } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { expect, test } from '@playwright/test';

const root = path.resolve(__dirname, '../../../..');
const composeFile = path.join(root, 'test-results/ci-private/compose.json');
const migrationFile = path.join(root, 'backend/core/directus/setup/migrate_notification_email_preferences.sql');

test.describe('Notification email migration on disposable PostgreSQL', () => {
  test.setTimeout(90_000);

  // contract-test: supporting surface=rest_api assertions=notifications.settings.ack-persisted,notifications.delivery.email-enabled
  test('preserves explicit opt-outs and unrelated categories across repeated migration', () => {
    test.skip(process.env.GITHUB_ACTIONS !== 'true' || process.env.RUNNER_ENVIRONMENT !== 'github-hosted'
      || process.env.CI_TEST_MODE !== 'e2e' || process.env.OPENMATES_CI_MAILPIT_URL !== 'http://127.0.0.1:8025',
      'Requires the runner-local isolated product and Mailpit stack');
    expect(existsSync(composeFile)).toBe(true);

    const schema = `ci_email_migration_${randomBytes(8).toString('hex')}`;
    const migration = readFileSync(migrationFile, 'utf8');
    expect(migration).toContain('ALTER TABLE public.directus_users');
    const scopedMigration = migration.replace(/\bpublic\./g, `${schema}.`);
    const snapshot = (label: string) => `
      SELECT '${label}:' || (jsonb_object_agg(label, jsonb_build_object(
        'enabled', email_notifications_enabled,
        'prefs', email_notification_preferences,
        'choices', email_notification_preference_choices
      )))::text FROM ${schema}.directus_users;
    `;
    const sql = `
      BEGIN;
      CREATE SCHEMA ${schema};
      CREATE TABLE ${schema}.directus_users (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        label text NOT NULL UNIQUE,
        email_notifications_enabled boolean NOT NULL DEFAULT false,
        email_notification_preferences jsonb DEFAULT '{"aiResponses":true,"backupReminder":true}'::jsonb,
        email_notification_preference_choices jsonb NOT NULL DEFAULT '{}'::jsonb
      );
      CREATE TABLE ${schema}.account_contact_emails (user_id text, hashed_email text);
      CREATE TABLE ${schema}.ignored_emails (hashed_email text);
      INSERT INTO ${schema}.directus_users
        (label, email_notifications_enabled, email_notification_preferences, email_notification_preference_choices)
      VALUES
        ('ambiguous_off', false, '{"aiResponses":true,"backupReminder":true,"webhookChats":true,"legacyUnknown":false}', '{}'),
        ('ai_off', false, '{"aiResponses":false,"backupReminder":false}', '{}'),
        ('workflow_off', false, '{"aiResponses":true,"workflowRuns":false}', '{}'),
        ('master_explicit_off', false, '{"aiResponses":true}', '{"enabled":{"value":false,"source":"user","updated_at":"2026-09-01T00:00:00Z"}}'),
        ('categories_explicit_off', false, '{"aiResponses":true,"workflowRuns":true}', '{"aiResponses":{"value":false,"source":"user","updated_at":"2026-09-01T00:00:00Z"},"workflowRuns":{"value":false,"source":"user","updated_at":"2026-09-01T00:00:00Z"}}'),
        ('blocked', false, '{"aiResponses":true}', '{}'),
        ('preview_explicit_on', false, '{"aiResponses":true,"includeContent":false}', '{"includeContent":{"value":true,"source":"user","updated_at":"2026-09-01T00:00:00Z"}}'),
        ('unrelated_off', false, '{"aiResponses":true,"backupReminder":false,"webhookChats":false}', '{}'),
        ('already_on', true, '{"aiResponses":false,"backupReminder":true,"webhookChats":false}', '{}'),
        ('already_on_workflow_choice_off', true, '{"aiResponses":true}', '{"workflowRuns":{"value":false,"source":"user","updated_at":"2026-09-01T00:00:00Z"}}');
      INSERT INTO ${schema}.account_contact_emails SELECT id::text, 'blocked-hash' FROM ${schema}.directus_users WHERE label = 'blocked';
      INSERT INTO ${schema}.ignored_emails VALUES ('blocked-hash');
      ${scopedMigration}
      ${snapshot('FIRST')}
      ${scopedMigration}
      ${snapshot('SECOND')}
      ROLLBACK;
      SELECT 'ROLLED_BACK:' || CASE WHEN to_regnamespace('${schema}') IS NULL THEN 'true' ELSE 'false' END;
    `;

    // Credentials stay inside the disposable database container environment.
    // A failed psql command closes the connection and rolls back this transaction.
    const output = execFileSync('docker', [
      'compose', '-f', composeFile, 'exec', '-T', 'cms-database', 'sh', '-ec',
      'export PGPASSWORD="$POSTGRES_PASSWORD"; exec psql -X -q -A -t -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f -',
    ], { cwd: root, encoding: 'utf8', input: sql, timeout: 75_000 });
    const lines = output.trim().split('\n');
    const first = lines.find(line => line.startsWith('FIRST:'));
    const second = lines.find(line => line.startsWith('SECOND:'));
    expect(first).toBeTruthy();
    expect(second).toBeTruthy();
    expect(lines).toContain('ROLLED_BACK:true');
    const before = JSON.parse(first!.slice('FIRST:'.length));
    const after = JSON.parse(second!.slice('SECOND:'.length));
    expect(after).toEqual(before);

    expect(before.ambiguous_off.enabled).toBe(true);
    expect(before.ambiguous_off.prefs).toMatchObject({
      aiResponses: true, workflowRuns: true, includeContent: false,
      backupReminder: false, webhookChats: false, legacyUnknown: false,
    });
    expect(before.ai_off.prefs.aiResponses).toBe(false);
    expect(before.workflow_off.prefs.workflowRuns).toBe(false);
    expect(before.master_explicit_off.enabled).toBe(false);
    expect(before.categories_explicit_off.prefs).toMatchObject({ aiResponses: false, workflowRuns: false });
    expect(before.blocked.enabled).toBe(false);
    expect(before.preview_explicit_on.prefs.includeContent).toBe(true);
    expect(before.unrelated_off.prefs).toMatchObject({ backupReminder: false, webhookChats: false });
    expect(before.already_on.prefs).toMatchObject({
      aiResponses: false, workflowRuns: true, backupReminder: true, webhookChats: false,
    });
    expect(before.already_on_workflow_choice_off.prefs.workflowRuns).toBe(false);
  });
});
