/**
 * E2B upload consent, user-started Code Run (assertion code-run.e2b.upload-consent).
 *
 * Real authenticated account, chat, embed encryption and consent endpoints on the
 * isolated CI stack. Only Code Run prepare (dependency suggestions) is synthetic;
 * /v1/code/run is NOT intercepted, so the real consent gate answers. Whether the
 * stack can finish a real E2B run is out of scope: after consent the proof is that
 * the server accepted the start request (not 403 e2b_consent_*).
 * Based on code-run-dependency-flow.spec.ts.
 */
// playwright-account: required reason=real_account_consent_state
import { test, expect } from './helpers/cookie-audit';
import type { Page, Response } from '@playwright/test';
import path from 'node:path';
/* eslint-disable @typescript-eslint/no-require-imports */
const { createSignupLogger, createStepScreenshotter, getTestAccount, getE2EDebugUrl, withMockMarker } = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat, deleteActiveChat } = require('./helpers/chat-test-helpers');
const { openFullscreen, closeFullscreen } = require('./helpers/embed-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const API_BASE_URL = process.env.PLAYWRIGHT_TEST_API_URL || 'https://api.dev.openmates.org';
const SOURCE_PATH = path.join(__dirname, 'fixtures', 'code_run_math.py');

type RunStart = { status: number; body: string };

async function consentDecision(page: Page): Promise<string | null> {
  const response = await page.request.get(`${API_BASE_URL}/v1/settings/e2b-upload-consent`);
  expect(response.ok()).toBe(true);
  return (await response.json()).decision ?? null;
}

async function openPrivacyConsentEntry(page: Page) {
  await page.getByTestId('profile-container').click();
  const menu = page.getByTestId('settings-menu');
  await expect(menu).toBeVisible({ timeout: 10_000 });
  await menu.getByRole('menuitem', { name: /privacy/i }).first().click();
  const entry = page.getByTestId('settings-e2b-consent');
  await expect(entry).toBeVisible({ timeout: 15_000 });
  return entry;
}

async function closeSettings(page: Page) {
  await page.getByTestId('icon-button-close').click();
  await expect(page.getByTestId('profile-container')).toHaveAttribute('data-action', 'open-settings');
}

// contract-test: direct surface=gui.web assertions=code-run.e2b.upload-consent
test('first user-started code run asks, Not now uploads nothing, Allow starts and later runs do not ask', async ({ page }, testInfo) => {
  test.setTimeout(240_000);
  const log = createSignupLogger('E2B_UPLOAD_CONSENT');
  const screenshot = createStepScreenshotter(log, { filenamePrefix: 'e2b-upload-consent' });
  const { email, password, otpKey } = getTestAccount();
  skipWithoutCredentials(test, email, password, otpKey);

  // Consent and Rust core warnings name the core's refusal code when a Worker call fails.
  page.on('console', (message) => {
    const line = message.text();
    if (/e2bConsent|e2b_consent|rustCore|UnitPort|sharedRustCore/i.test(line)) log(`browser ${message.type()}: ${line.slice(0, 400)}`);
  });

  const runStarts: RunStart[] = [];
  page.on('response', async (response: Response) => {
    const request = response.request();
    if (request.method() === 'POST' && /\/v1\/code\/run(?:\?|$)/.test(request.url())) {
      runStarts.push({ status: response.status(), body: await response.text().catch(() => '') });
    }
  });
  await page.route(/\/v1\/code\/run\/prepare(?:\?|$)/, route => route.fulfill({ json: { dependency_suggestions: [] } }));

  await page.goto(getE2EDebugUrl('/'));
  await loginToTestAccount(page, log, screenshot);
  await startNewChat(page, log);
  expect(await consentDecision(page), 'a fresh account has no decision').toBeNull();

  const editor = page.getByTestId('message-editor');
  await expect(editor.locator('[contenteditable="true"]').first()).toBeVisible({ timeout: 20_000 });
  await editor.locator('[contenteditable="true"]').first().fill(withMockMarker('Please acknowledge this attached Python file.', 'test_hello', 'instant'));
  await page.locator('input[type="file"][multiple]').setInputFiles(SOURCE_PATH);
  await expect(editor.locator('[data-testid="embed-full-width-wrapper"][data-embed-type="code-code"]')).toBeVisible({ timeout: 30_000 });
  const send = page.locator('[data-action="send-message"]');
  await expect(send).toBeEnabled({ timeout: 15_000 });
  await send.click();
  await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 30_000 });
  await expect(page.getByTestId('message-assistant').last()).toContainText('Hello', { timeout: 30_000 });
  const chatUrl = page.url();
  const embed = page.getByTestId('message-user').last().locator('[data-testid="embed-full-width-wrapper"][data-embed-type="code-code"]');
  await expect(embed).toBeVisible({ timeout: 30_000 });

  async function startRun() {
    const overlay = await openFullscreen(page, embed.getByTestId('result-preview-expand'));
    await overlay.getByTestId('embed-run-button').click();
    const selection = overlay.getByTestId('code-run-file-selection');
    if (await selection.isVisible({ timeout: 15_000 }).catch(() => false)) {
      await selection.getByTestId('code-run-continue').click();
    }
    return overlay;
  }

  // (1) First start asks; Not now starts nothing.
  let overlay = await startRun();
  const dialog = page.getByTestId('e2b-consent-dialog');
  await expect(dialog).toBeVisible({ timeout: 30_000 });
  await expect(dialog.getByTestId('e2b-consent-allow')).toBeVisible();
  await expect(dialog.getByTestId('e2b-consent-own-machine')).toBeVisible();
  await screenshot(page, 'consent-dialog');
  await dialog.getByTestId('e2b-consent-not-now').click();
  await expect(dialog).toHaveCount(0);
  await expect.poll(() => consentDecision(page), { timeout: 15_000 }).toBe('declined');
  // Nothing starts: the run panel shows only the not-allowed notice with the settings path.
  const terminal = overlay.getByTestId('code-run-terminal');
  await expect(terminal).toContainText('nothing was started');
  await expect(terminal).toContainText('Settings > Privacy');
  await screenshot(page, 'not-now-nothing-started');
  expect(runStarts, 'Not now must not send any run start request').toEqual([]);
  await closeFullscreen(page, overlay, { returnToChatUrl: chatUrl });

  const declinedEntry = await openPrivacyConsentEntry(page);
  await expect(declinedEntry).toHaveAttribute('data-decision', 'declined');
  await testInfo.attach('settings-not-allowed', { body: await declinedEntry.screenshot(), contentType: 'image/png' });

  // (2) Allow in settings; the next start asks nothing and the server accepts it.
  await declinedEntry.getByRole('menuitem').first().click();
  await expect(declinedEntry).toHaveAttribute('data-decision', 'allowed', { timeout: 15_000 });
  expect(await consentDecision(page)).toBe('allowed');
  await closeSettings(page);
  overlay = await startRun();
  await expect.poll(() => runStarts.length, { timeout: 30_000 }).toBeGreaterThan(0);
  expect(runStarts[0].status, `server must accept the start: ${runStarts[0].body}`).toBeLessThan(400);
  expect(runStarts[0].body).not.toContain('e2b_consent');
  await expect(dialog).toHaveCount(0);
  await screenshot(page, 'run-started-after-allow');
  await closeFullscreen(page, overlay, { returnToChatUrl: chatUrl });

  // (3) A second start does not ask.
  const before = runStarts.length;
  overlay = await startRun();
  await expect.poll(() => runStarts.length, { timeout: 30_000 }).toBeGreaterThan(before);
  await expect(dialog).toHaveCount(0);
  expect(runStarts[runStarts.length - 1].body).not.toContain('e2b_consent');
  await closeFullscreen(page, overlay, { returnToChatUrl: chatUrl });
  await deleteActiveChat(page, log, screenshot, 'e2b-consent-cleanup');
});
