// proof-video: not_required reason=real_inference_dev_only
/** Real dev flow: open a researched conference card fullscreen and ask for talk tips from its input.
 * Held out of isolated CI (real inference, personal dev account). */
import { test, expect, chromium, type Page } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { loginToTestAccount } = require('./helpers/chat-test-helpers');

// playwright-account: required reason=real_ai_personal_dev_only
const enabled = process.env.CONFERENCE_TALK_REAL_DEV === '1';
const APP = 'https://app.dev.openmates.org';
const chatId = process.env.CONFERENCE_TALK_CHAT_ID || '';
const profile = path.join(process.env.OPENMATES_STATE_DIR || '/tmp', 'conference-talk-profile');
const FOLLOW_UP = 'Awesome. I work on a large open source project and would love to submit a talk. '
  + 'Any tips I should consider before I plan out talk ideas for the conference?';
test.skip(!enabled, 'Requires explicit dev-only execution against a chat holding researched conference cards.');
test.describe.configure({ retries: 0, timeout: 300_000 });

async function login(page: Page) {
  await page.goto('/');
  await page.waitForTimeout(4000);
  if (await page.getByTestId('header-login-signup-btn').isVisible()) await loginToTestAccount(page, () => {}, async () => {}, { credentials: {
    email: process.env.OPENMATES_PERSONAL_TEST_ACOUNT_EMAIL,
    password: process.env.OPENMATES_PERSONAL_TEST_ACOUNT_PASSWORD,
    otpKey: process.env.OPENMATES_PERSONAL_TEST_ACOUNT_OTP_KEY } });
}

// contract-test: direct surface=gui.web assertions=authored-results.creation.relevant-and-independent,authored-results.media.safe-and-attributed
test('FOSDEM card fullscreen shows image, real map and domain link; its follow-up activates Plan a conference talk', async ({ baseURL: _baseURL }, info) => {
  expect(chatId).toMatch(/^[a-f0-9-]{36}$/);
  const ctx = await chromium.launchPersistentContext(profile, { headless: true, baseURL: APP,
    executablePath: process.env.PW_CHROMIUM, viewport: { width: 1400, height: 1000 },
    recordVideo: { dir: info.outputPath('recordings'), size: { width: 1400, height: 1000 } } });
  try {
    const page = ctx.pages()[0] || await ctx.newPage();
    await login(page);
    await page.goto(`/#chat-id=${chatId}`);
    const card = page.locator('[data-testid="embed-preview"]').filter({ hasText: /FOSDEM/i }).first();
    await expect(card).toBeVisible({ timeout: 60_000 });
    await expect(card.locator('img').first()).toBeVisible({ timeout: 30_000 });
    await card.scrollIntoViewIfNeeded();
    if (await card.getAttribute('role') === 'button') await card.click();
    else { await card.hover(); await card.getByTestId('result-preview-expand').click(); }
    const fullscreen = page.getByTestId('embed-fullscreen-overlay').last();
    await expect(fullscreen).toBeVisible();
    await expect(fullscreen.getByTestId('embed-header-title')).toContainText(/FOSDEM/i);
    await expect(fullscreen.locator('img.event-image')).toBeVisible({ timeout: 30_000 });
    // Server-side geocoding gives the Brussels venue a real map (never 0/0).
    await expect(fullscreen.getByTestId('embed-leaflet-map').first()).toBeVisible({ timeout: 30_000 });
    await expect(fullscreen.getByTestId('external-provider-cta')).toContainText('Open fosdem.org');
    await page.screenshot({ path: info.outputPath('fosdem-fullscreen.png') });

    const composer = fullscreen.getByTestId('apps-request-composer');
    await expect(composer).toBeVisible();
    await composer.getByTestId('apps-request-textarea').fill(FOLLOW_UP);
    await composer.getByTestId('apps-request-submit').click();
    // The fullscreen hands off to the source chat with the card attached.
    await expect(fullscreen).toBeHidden({ timeout: 20_000 });
    await expect(page.getByTestId('focus-pill')).toBeVisible({ timeout: 120_000 });
    await expect(page.getByTestId('focus-pill')).toContainText(/conference talk/i);
    const answer = page.getByTestId('message-assistant').last();
    await expect(answer).toContainText('?', { timeout: 150_000 });
    await expect.poll(async () => (await answer.innerText()).length, { timeout: 150_000, intervals: [5000] }).toBeGreaterThan(200);
    await page.waitForTimeout(8000);
    const text = await answer.innerText();
    fs.writeFileSync(info.outputPath('answer.txt'), text, { mode: 0o600 });
    // One question, CFP title/abstract limits stated (or explicitly not found).
    expect((text.match(/\?/g) || []).length).toBeLessThanOrEqual(2);
    expect(text).toMatch(/title|abstract|limit|character|word/i);
    await page.screenshot({ path: info.outputPath('conference-talk-focus.png') });
  } finally {
    await ctx.close();
  }
});
