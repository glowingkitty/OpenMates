import { spawn, execFileSync, type ChildProcess } from 'node:child_process';
import { createHash, randomBytes } from 'node:crypto';
import path from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { expect, test } from './helpers/cookie-audit';
import { createSignupEmailClient } from './signup-flow-helpers';

// playwright-account: not_required reason=isolated_runner_local_newsletter_mail_capture
// Use the same runner-local website build/preview lifecycle as website-public-routes.
// The API, worker, Mailpit and CMS remain the isolated CI profile's real services.
test.skip(process.env.OPENMATES_CI_ISOLATED !== '1' || process.env.OPENMATES_CI_MAILPIT_URL !== 'http://127.0.0.1:8025',
  'Requires the isolated API, email worker and captured inbox.');

const root = path.resolve(__dirname, '../../../..');
const website = 'http://127.0.0.1:5180';
const app = new URL(process.env.PLAYWRIGHT_TEST_BASE_URL ?? 'http://127.0.0.1:5173').origin;
const api = 'http://127.0.0.1:8000';
const environment = {
  ...process.env,
  PUBLIC_WEBSITE_URL: website,
  PUBLIC_WEBAPP_URL: app,
  PUBLIC_NEWSLETTER_API_BASE_URL: api
};
let preview: ChildProcess | null = null;

function terminateGroup(child: ChildProcess | null, signal: NodeJS.Signals = 'SIGTERM'): void {
  if (!child?.pid) return;
  try { process.kill(-child.pid, signal); } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ESRCH') throw error;
  }
}

async function command(args: string[], timeoutMs: number): Promise<string> {
  const child = spawn('corepack', ['pnpm', ...args], { cwd: root, env: environment, detached: true, stdio: ['ignore', 'pipe', 'pipe'] });
  let output = '';
  const append = (chunk: Buffer) => { output = (output + chunk.toString()).slice(-24_000); };
  child.stdout?.on('data', append);
  child.stderr?.on('data', append);
  const timer = setTimeout(() => terminateGroup(child, 'SIGKILL'), timeoutMs);
  try {
    const code = await new Promise<number>((resolve, reject) => {
      child.once('error', reject);
      child.once('exit', (status) => resolve(status ?? -1));
    });
    if (code !== 0) throw new Error(`pnpm ${args.join(' ')} exited ${code}:\n${output}`);
    return output;
  } finally {
    clearTimeout(timer);
  }
}

async function waitForWebsite(child: ChildProcess, output: () => string): Promise<void> {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null || child.signalCode !== null) throw new Error(`Website preview exited before becoming ready:\n${output()}`);
    try {
      const response = await fetch(website, { signal: AbortSignal.timeout(2_000) });
      if (response.ok) return;
    } catch { /* The preview socket is not ready yet. */ }
    await delay(250);
  }
  throw new Error(`Website preview did not become ready on port 5180 within 30 seconds:\n${output()}`);
}

test.beforeAll(async () => {
  test.setTimeout(180_000);
  await command(['--filter', 'website...', 'install', '--frozen-lockfile', '--ignore-scripts'], 50_000);
  const build = await command(['--filter', 'website...', 'run', 'build'], 75_000);
  expect(build).toContain('[plugin public-bundle-boundary] Website client JS:');
  preview = spawn('corepack', ['pnpm', '--dir', 'frontend/apps/website', 'exec', 'vite', 'preview', '--host', '127.0.0.1', '--port', '5180', '--strictPort'], {
    cwd: root, env: environment, detached: true, stdio: ['ignore', 'pipe', 'pipe']
  });
  let previewOutput = '';
  const append = (chunk: Buffer) => { previewOutput = (previewOutput + chunk.toString()).slice(-4_000); };
  preview.stdout?.on('data', append);
  preview.stderr?.on('data', append);
  preview.once('error', (error) => { previewOutput += `\n${error.message}`; });
  try { await waitForWebsite(preview, () => previewOutput); } catch (error) { terminateGroup(preview, 'SIGKILL'); throw error; }
});

test.afterAll(async () => {
  const child = preview;
  preview = null;
  if (!child) return;
  terminateGroup(child);
  if (child.exitCode === null && child.signalCode === null) {
    await Promise.race([new Promise<void>((resolve) => child.once('exit', () => resolve())), delay(5_000)]);
  }
  if (child.exitCode === null) terminateGroup(child, 'SIGKILL');
});

const site = (pathname: string) => `${website}${pathname}`;

/** Inspect only the run-scoped subscriber in the disposable CI database. */
function readCapturedNewsletterCategories(email: string): Record<string, boolean> | null {
  if (process.env.OPENMATES_CI_ISOLATED !== '1' || process.env.OPENMATES_CI_MAILPIT_URL !== 'http://127.0.0.1:8025') {
    throw new Error('Newsletter database inspection requires isolated CI.');
  }
  const compose = process.env.OPENMATES_CI_COMPOSE_FILE || path.join(root, 'test-results/ci-private/compose.json');
  const hash = createHash('sha256').update(email.toLowerCase().trim()).digest('base64');
  const output = execFileSync('docker', [
    'compose', '-f', compose, 'exec', '-T', 'cms-database', 'sh', '-ec',
    'export PGPASSWORD="$POSTGRES_PASSWORD"; exec psql -X -q -A -t -v ON_ERROR_STOP=1 -v hashed_email="$1" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f -',
    'sh', hash,
  ], {
    cwd: process.env.OPENMATES_CI_SOURCE_ROOT || root, encoding: 'utf8', timeout: 30_000,
    input: "SELECT categories::text FROM public.newsletter_subscribers WHERE hashed_email = :'hashed_email' AND confirmed_at IS NOT NULL LIMIT 1;",
  });
  return output.trim() ? JSON.parse(output.trim()) : null;
}

// contract-test: direct surface=gui.web assertions=newsletter.lifecycle.double-opt-in,newsletter.categories.default-and-migration,newsletter.surface.standalone-confirmation
test('standalone Apple beta signup delivers confirmation mail and persists choices only after explicit confirmation', async ({ page }) => {
  test.setTimeout(180_000);
  test.skip(process.env.OPENMATES_CI_ISOLATED !== '1' || process.env.OPENMATES_CI_MAILPIT_URL !== 'http://127.0.0.1:8025',
    'Requires the isolated API, email worker and captured inbox.');
  const inbox = createSignupEmailClient();
  expect(inbox?.provider).toBe('mailpit');
  if (!inbox) throw new Error('Isolated inbox is missing.');
  const email = `ci-inbox+website${randomBytes(6).toString('hex')}@example.com`;
  const choices = { openmates_events: true, software_updates: false, apple_beta_updates: true };
  const requestedAfter = new Date(Date.now() - 5000).toISOString();
  await page.goto(site('/#testflight-signup'), { waitUntil: 'domcontentloaded' });
  const form = page.getByTestId('landing-newsletter');
  await expect(form).toBeVisible();
  await expect(form.getByRole('checkbox', { name: /Apple app beta updates/ })).not.toBeChecked();
  await form.getByRole('checkbox', { name: 'Software updates', exact: true }).uncheck();
  await form.getByRole('checkbox', { name: /Apple app beta updates/ }).check();
  await form.getByLabel('Email address').fill(email);
  const subscribed = page.waitForResponse(response => new URL(response.url()).pathname === '/v1/newsletter/subscribe' && response.request().method() === 'POST');
  await form.getByRole('button', { name: 'Subscribe', exact: true }).click();
  const response = await subscribed;
  expect(response.status()).toBe(200);
  expect(response.request().postDataJSON().categories).toEqual(choices);
  expect((await response.json()).success).toBe(true);
  await expect(form.getByTestId('newsletter-requested')).toBeVisible();
  expect(readCapturedNewsletterCategories(email)).toBeNull();
  const message = await inbox.waitForMessage({ sentTo: email, subjectContains: 'confirm', receivedAfter: requestedAfter, timeoutMs: 120_000 });
  const href = message.html?.body?.match(/href=["']([^"']*\/newsletter\/confirm\/[^"']+)["']/i)?.[1];
  if (!href) throw new Error('Captured confirmation email lacks the standalone website link.');
  const destination = new URL(href.replace(/&amp;/g, '&'));
  expect(destination.origin).toBe(website);
  let confirmationRequests = 0;
  page.on('request', request => {
    if (new URL(request.url()).pathname.startsWith('/v1/newsletter/confirm/')) confirmationRequests += 1;
  });
  await page.goto(destination.href, { waitUntil: 'domcontentloaded' });
  await expect(page.getByTestId('newsletter-confirm-button')).toBeVisible();
  await expect(page.getByTestId('newsletter-signal-link')).toHaveCount(0);
  expect(confirmationRequests).toBe(0);
  expect(readCapturedNewsletterCategories(email)).toBeNull();
  const confirmed = page.waitForResponse(item => new URL(item.url()).pathname.startsWith('/v1/newsletter/confirm/'));
  await page.getByTestId('newsletter-confirm-button').click();
  const confirmedResponse = await confirmed;
  expect(confirmedResponse.status()).toBe(200);
  expect((await confirmedResponse.json()).success).toBe(true);
  await expect(page.getByTestId('newsletter-signal-link')).toBeVisible();
  expect(confirmationRequests).toBe(1);
  expect(readCapturedNewsletterCategories(email)).toEqual(choices);
});
