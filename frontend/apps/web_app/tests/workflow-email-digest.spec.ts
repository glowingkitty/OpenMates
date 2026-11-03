// proof-video: required reason=workflow_daily_email_desktop_phone_and_images_blocked
import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { expect, test } from '@playwright/test';

const root = path.resolve(__dirname, '../../../..');
const composeFile = path.join(root, 'test-results/ci-private/compose.json');

test.describe('Daily Workflow email on the disposable isolated stack', () => {
  test.setTimeout(240_000);

  // contract-test: supporting surface=gui.web assertions=notifications.delivery.email-enabled,notifications.delivery.idempotent,notifications.workflow-digest.daily-activity,notifications.workflow-digest.readable-identity
  test('aggregates scheduled runs and renders readable desktop and phone Mailpit digests', async ({ page, request }) => {
    test.skip(process.env.GITHUB_ACTIONS !== 'true' || process.env.RUNNER_ENVIRONMENT !== 'github-hosted'
      || process.env.CI_TEST_MODE !== 'e2e' || process.env.OPENMATES_CI_MAILPIT_URL !== 'http://127.0.0.1:8025',
      'Requires the runner-local isolated product and Mailpit stack');
    const email = process.env.OPENMATES_TEST_ACCOUNT_EMAIL;
    expect(email).toMatch(/^ci-[a-z0-9+._-]+@example\.com$/);
    expect(existsSync(composeFile)).toBe(true);
    const output = execFileSync('docker', [
      'compose', '-f', composeFile, 'exec', '-T',
      '-e', `PROBE_EMAIL=${email}`, 'api', 'python',
      '/app/backend/scripts/probe_workflow_digest_email.py',
    ], { cwd: root, encoding: 'utf8', timeout: 210_000 });
    expect(output).toContain('real workflow digest Mailpit roundtrip passed');

    const response = await request.get('http://127.0.0.1:8025/api/v1/messages?limit=100');
    expect(response.ok()).toBe(true);
    const listing = await response.json();
    const matches = listing.messages.filter((item: { Subject: string; To: { Address: string }[] }) =>
      item.Subject === 'Your daily Workflow runs' && item.To.some(address => address.Address.toLowerCase() === email?.toLowerCase()));
    expect(matches.length).toBeGreaterThanOrEqual(2);
    matches.sort((a: { Created: string }, b: { Created: string }) => a.Created.localeCompare(b.Created));
    // The first digest has the frequent-run and multiple-Workflow cards, with
    // identifying names allowed and private outputs excluded.
    const message = await (await request.get(`http://127.0.0.1:8025/api/v1/message/${matches[0].ID}`)).json();
    await page.route('**/images/email/**', route => route.abort());
    await page.setViewportSize({ width: 1200, height: 1000 });
    await page.setContent(message.HTML);
    await expect(page.getByText('Private Workflow title CI', { exact: true })).toBeVisible();
    await expect(page.getByText('Runs: 242', { exact: true })).toBeVisible();
    await expect(page.getByText('PRIVATE-SEND-MESSAGE-MUST-NOT-EMAIL')).toHaveCount(0);
    await expect(page.getByRole('link', { name: 'View Workflow', exact: true })).toHaveCount(2);
    await expect(page.getByRole('link', { name: 'View latest run', exact: true })).toHaveCount(2);
    await expect(page.getByRole('link', { name: 'View all Workflows', exact: true })).toBeVisible();
    await page.screenshot({ path: test.info().outputPath('workflow-digest-desktop-images-blocked.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.getByText('Private Workflow title CI', { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.getByRole('link', { name: 'View all Workflows', exact: true }).scrollIntoViewIfNeeded();
    await expect(page.getByRole('link', { name: 'View all Workflows', exact: true })).toBeVisible();
    await page.screenshot({ path: test.info().outputPath('workflow-digest-phone-images-blocked.png'), fullPage: true });
  });
});
