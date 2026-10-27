/** Real isolated reminder -> Vault/cache recovery -> broker/worker -> SMTP/Mailpit.
 * Browser displays the captured email and bytes fetched from its actual image API;
 * target navigation itself is covered separately by notification-email-links.
 */
import { execFileSync } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { expect, test } from '@playwright/test';

const root = path.resolve(__dirname, '../../../..');
const composeFile = path.join(root, 'test-results/ci-private/compose.json');

interface CapturedEmail {
  kind: 'chat' | 'event';
  html: string;
  subject: string;
  title: string;
  destination: string;
  imageUrl: string;
  image: string;
}

test.describe('Reminder emails delivered on the isolated Mailpit stack', () => {
  test.setTimeout(240_000);

  // contract-test: supporting surface=gui.web assertions=notifications.reminder-email.identifiable-default,notifications.reminder-email.durable-limited-context,notifications.reminder-email.readable-without-images,notifications.reminder-email.exact-web-target,notifications.delivery.idempotent
  test('delivers chat and event reminders with durable private cards, descriptions and exact targets', async ({ page }, testInfo) => {
    test.skip(process.env.GITHUB_ACTIONS !== 'true' || process.env.RUNNER_ENVIRONMENT !== 'github-hosted'
      || process.env.CI_TEST_MODE !== 'e2e' || process.env.OPENMATES_CI_MAILPIT_URL !== 'http://127.0.0.1:8025',
    'Requires the runner-local isolated product and Mailpit stack');
    const email = process.env.OPENMATES_TEST_ACCOUNT_EMAIL;
    expect(email).toMatch(/^ci-[a-z0-9+._-]+@example\.com$/);
    expect(existsSync(composeFile)).toBe(true);
    const privateDir = mkdtempSync(path.join(os.tmpdir(), 'reminder-mail-proof-'));
    let captures: CapturedEmail[];
    const probeStartedAt = new Date().toISOString();
    try {
      const output = execFileSync('docker', [
        'compose', '-f', composeFile, 'exec', '-T', '-e', `PROBE_EMAIL=${email}`,
        'api', 'python', '/app/backend/scripts/probe_reminder_email.py',
      ], { cwd: root, encoding: 'utf8', timeout: 210_000, maxBuffer: 4 * 1024 * 1024 });
      expect(output).toContain('real reminder Mailpit roundtrip passed');
      const fixtureFile = path.join(privateDir, 'captured.json');
      execFileSync('docker', ['compose', '-f', composeFile, 'cp',
        'api:/tmp/reminder-email-probe.json', fixtureFile], { cwd: root, stdio: 'pipe' });
      const fixture = JSON.parse(readFileSync(fixtureFile, 'utf8'));
      expect(fixture.checks).toEqual(expect.arrayContaining([
        'real-skill', 'vault-persistence', 'cold-cache-recovery', 'real-scheduler',
        'broker-worker-smtp', 'image-api', 'capability-revocation', 'content-opt-out', 'replay-idempotence',
      ]));
      captures = fixture.captures;
    } finally {
      rmSync(privateDir, { recursive: true, force: true });
      execFileSync('docker', ['compose', '-f', composeFile, 'exec', '-T', 'api',
        'rm', '-f', '/tmp/reminder-email-probe.json'], { cwd: root, stdio: 'pipe' });
    }
    expect(captures.map((capture) => capture.kind)).toEqual(['chat', 'event']);
    const serviceLogs = execFileSync('docker', ['compose', '-f', composeFile, 'logs',
      '--no-color', '--since', probeStartedAt, 'api', 'core-worker'],
    { cwd: root, encoding: 'utf8', maxBuffer: 8 * 1024 * 1024 });
    // Inspect actual API/SMTP-worker logs without attaching private HTML or URLs.
    for (const capture of captures) {
      const token = new URL(capture.imageUrl).pathname.split('/').at(-1)!.replace(/\.png$/, '');
      expect(serviceLogs.includes(token), 'Private image capability must be redacted in service logs').toBe(false);
      expect(serviceLogs.includes(capture.title), 'Private reminder title must be absent from service logs').toBe(false);
    }
    expect(serviceLogs.includes('Doors open at 18:30. Bring the booking confirmation.'),
      'Private reminder description must be absent from service logs').toBe(false);
    for (const capture of captures) {
      await test.step(`Read delivered ${capture.kind} reminder email`, async () => {
        // The probe obtained these exact bytes from the real capability endpoint
        // before revocation and fixture cleanup; no browser renderer substitutes.
        await page.route('**/*', async (route) => {
          if (route.request().url() === capture.imageUrl) {
            await route.fulfill({ status: 200, contentType: 'image/png', body: Buffer.from(capture.image, 'base64') });
          } else if (new URL(route.request().url()).pathname === '/images/email/reminder-notification.png') {
            await route.continue();
          } else {
            await route.abort();
          }
        });
        await page.setContent(capture.html, { waitUntil: 'domcontentloaded' });
        const bell = page.locator('img[src$="/images/email/reminder-notification.png"]');
        await expect(bell).toBeVisible();
        await expect.poll(() => bell.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0)).toBe(true);
        const card = page.locator('img[src*="/v1/email/reminder-preview/"]');
        await expect(card).toBeVisible();
        await expect(card).toHaveAttribute('alt', new RegExp(capture.title));
        await expect.poll(() => card.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0)).toBe(true);
        await expect(page.getByText(capture.title, { exact: true }).first()).toBeVisible();
        const targetLinks = page.locator(`a[href$="${capture.destination}"]`);
        await expect(targetLinks).toHaveCount(2);
        // MJML keeps the translated label, <br/> and full note sentence in one
        // div; match the complete sentence within that visible native text block.
        await expect(page.getByText('Reminder notes: check the saved details.', { exact: false })).toBeVisible();
        if (capture.kind === 'event') {
          await expect(page.getByText('Doors open at 18:30. Bring the booking confirmation.', { exact: true })).toBeVisible();
          await expect(page.getByText('Philharmonie Berlin', { exact: false })).toBeVisible();
        } else {
          await expect(page.getByText('Review the museum itinerary and train reservations.', { exact: true })).toBeVisible();
        }
        await page.screenshot({ path: testInfo.outputPath(`${capture.kind}-delivered-email.png`), fullPage: true });
        // Preserve both actual delivered states in the reviewer recording.
        await page.waitForTimeout(1200);
        await page.setViewportSize({ width: 390, height: 844 });
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
        await expect(card).toBeVisible();
        await targetLinks.last().scrollIntoViewIfNeeded();
        await expect(targetLinks.last()).toBeInViewport();
        await page.screenshot({ path: testInfo.outputPath(`${capture.kind}-delivered-email-phone.png`), fullPage: true });
        await page.waitForTimeout(1200);
        await card.evaluate((img: HTMLImageElement) => { img.style.display = 'none'; });
        await expect(page.getByText(capture.title, { exact: true }).first()).toBeVisible();
        await expect(targetLinks.last()).toBeVisible();
        await page.setViewportSize({ width: 1280, height: 900 });
        await page.unroute('**/*');
      });
    }
  });
});
