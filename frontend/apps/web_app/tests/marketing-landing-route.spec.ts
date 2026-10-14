import { expect, test } from './helpers/cookie-audit';

// eslint-disable-next-line @typescript-eslint/no-require-imports
const { getE2EDebugUrl } = require('./signup-flow-helpers');
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

test.beforeEach(async ({ page }) => {
  await page.route('**/v1/settings/server-status', async route => {
    // Keep the app's full status response when navigation starts its services.
    if (new URL(route.request().frame().url()).pathname !== '/landing') {
      await route.continue();
      return;
    }
    await route.fulfill({ json: { anonymous_free_usage: { active: true, can_send_text: true } } });
  });
});

const openWebAppProof = defineVideoProof({
  id: 'landing-open-web-app', title: 'Open the app after drafting from the landing page', surface: 'web',
  devices: ['web-phone', 'web-laptop'], domain: 'landing.dev.openmates.org',
  transcript: [{ id: 'app', text: 'The landing page preserves a guest draft and Open Web App opens the chat workspace.', checkpoint: 'app', devices: ['web-phone', 'web-laptop'] }],
  assertions: [{ id: 'landing.open-web-app-workspace', checkpoint: 'app', visual: 'The app chat workspace is visible with no automatic signup screen.', devices: ['web-phone', 'web-laptop'] }],
  tutorial: { readingWordsPerSecond: 3, minimumHoldMs: 900, maximumHoldMs: 2500 },
});


for (const { name, width, height } of [
  { name: 'phone', width: 390, height: 844 },
  { name: 'laptop', width: 1440, height: 900 },
]) {
  // contract-test: direct surface=gui.web assertions=marketing-landing.composer-focus,marketing-landing.destinations,marketing-landing.independent-scroll
  test(`landing composer preserves a guest draft and Open Web App opens chats (${name})`, async ({ page }, testInfo) => {
    test.setTimeout(90_000);
    const proof = createVideoProofRuntime(openWebAppProof, { device: name === 'phone' ? 'web-phone' : 'web-laptop', attach: testInfo.attach.bind(testInfo), captureFrame: () => page.screenshot() });
    await page.setViewportSize({ width, height });
    await page.goto(getE2EDebugUrl('/landing'), { waitUntil: 'domcontentloaded' });
    const scroller = page.getByTestId('landing-scroll-container');
    const composer = page.getByTestId('landing-compose');
    await expect(composer).toBeVisible();
    const composerBeforeScroll = await composer.boundingBox();
    if (!composerBeforeScroll) throw new Error('Landing composer geometry is missing');
    await scroller.hover();
    await page.mouse.wheel(0, height);
    await expect.poll(() => scroller.evaluate(element => element.scrollTop)).toBeGreaterThan(0);
    await expect.poll(() => composer.evaluate(element => element.getBoundingClientRect().top)).toBeCloseTo(composerBeforeScroll.y, 0);
    expect(await page.evaluate(() => document.documentElement.scrollHeight <= window.innerHeight + 1)).toBe(true);
    await page.getByTestId('landing-compose').click();
    const editor = page.getByTestId('message-editor').locator('[contenteditable="true"]').first();
    await expect(editor).toBeFocused({ timeout: 30_000 });
    await expect(editor).toHaveText('');

    const draft = `Fictional garden sketch for ${name}: blue lanterns near the pond.`;
    await editor.pressSequentially(draft);
    await expect(editor).toContainText(draft);
    await page.getByTestId('input-dismiss-button').click();
    await expect.poll(() => page.evaluate(text => Object.keys(sessionStorage).some(key =>
      key.startsWith('draft_') && (sessionStorage.getItem(key) ?? '').includes(text)), draft)).toBe(true);

    await page.goto(getE2EDebugUrl('/landing'), { waitUntil: 'domcontentloaded' });
    await page.getByTestId('landing-compose').click();
    await expect(editor).toBeFocused({ timeout: 30_000 });
    await expect(editor).toContainText(draft);
    await expect(page.getByTestId('message-editor')).toContainText(draft);

    await page.goto(getE2EDebugUrl('/landing'), { waitUntil: 'domcontentloaded' });
    const openWebApp = page.getByTestId('landing-open-web-app');
    await expect(openWebApp).toHaveAttribute('href', `${new URL(page.url()).origin}/`);
    await openWebApp.click();
    await expect(page).toHaveURL(`${new URL(page.url()).origin}/`);
    await proof.assert('landing.open-web-app-workspace', async () => {
      await expect(page.getByTestId('active-chat-container')).toBeVisible({ timeout: 30_000 });
      await expect(page.getByTestId('message-editor')).toBeVisible();
      await expect(page.getByTestId('signup-modal')).toHaveCount(0);
      await expect(page.getByTestId('login-wrapper')).toHaveCount(0);
    });
    await proof.checkpoint('app');
    await proof.attach();
  });
}

// contract-test: direct surface=gui.web assertions=marketing-landing.language-theme
test('saved dark theme stays dark from prepaint through landing hydration', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'light', reducedMotion: 'reduce' });
  await page.addInitScript(() => {
    localStorage.setItem('theme_mode', 'dark');
    const modes: string[] = [];
    (window as Window & { __landingThemeModes?: string[] }).__landingThemeModes = modes;
    new MutationObserver(records => {
      for (const record of records) {
        if (record.oldValue) modes.push(record.oldValue);
        const mode = document.documentElement.getAttribute('data-theme');
        if (mode) modes.push(mode);
      }
    }).observe(document, { subtree: true, attributes: true, attributeFilter: ['data-theme'], attributeOldValue: true });
  });
  await page.goto(getE2EDebugUrl('/landing'), { waitUntil: 'networkidle' });
  await expect(page.getByTestId('landing-page')).toBeVisible();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  const modes = await page.evaluate(() => (window as Window & { __landingThemeModes?: string[] }).__landingThemeModes ?? []);
  expect(modes).toContain('dark');
  expect(modes).not.toContain('light');
});
