// proof-video: not_required reason=non_visual_email_delivery
import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { expect, test } from '@playwright/test';

const root = path.resolve(__dirname, '../../../..');
const composeFile = path.join(root, 'test-results/ci-private/compose.json');

test.describe('Chat response email on the disposable isolated stack', () => {
  test.setTimeout(240_000);

  // contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,notifications.delivery.idempotent
  test('sends consent-aware private mail through the real worker and Mailpit', () => {
    test.skip(process.env.GITHUB_ACTIONS !== 'true' || process.env.RUNNER_ENVIRONMENT !== 'github-hosted'
      || process.env.CI_TEST_MODE !== 'e2e' || process.env.OPENMATES_CI_MAILPIT_URL !== 'http://127.0.0.1:8025',
      'Requires the runner-local isolated product and Mailpit stack');
    const email = process.env.OPENMATES_TEST_ACCOUNT_EMAIL;
    expect(email).toMatch(/^ci-[a-z0-9+._-]+@example\.com$/);
    expect(existsSync(composeFile)).toBe(true);
    const output = execFileSync('docker', [
      'compose', '-f', composeFile, 'exec', '-T',
      '-e', `PROBE_EMAIL=${email}`, 'api', 'python',
      '/app/backend/scripts/probe_chat_response_email.py',
    ], { cwd: root, encoding: 'utf8', timeout: 220_000 });
    expect(output).toContain('real chat response Mailpit roundtrip passed');
  });
});
