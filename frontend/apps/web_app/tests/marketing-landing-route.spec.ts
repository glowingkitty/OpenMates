import { expect, test } from './helpers/cookie-audit';
import { getUpcomingOpenMatesEventCards } from '../../../packages/public-site/src/data/events';

// eslint-disable-next-line @typescript-eslint/no-require-imports
const { getE2EDebugUrl } = require('./signup-flow-helpers');

// contract-test: direct surface=gui.web assertions=marketing-landing.independent-scroll,marketing-landing.feature-layout,marketing-landing.six-feature-viewport,marketing-landing.destinations,marketing-landing.real-screenshots,marketing-landing.public-content,workflows-ui.workspace.guest-template-preview
test('public landing server-renders and opens real app workspaces', async ({ page }) => {
  test.setTimeout(90_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  const htmlResponse = await page.request.get(getE2EDebugUrl('/landing'));
  expect(htmlResponse.ok()).toBe(true);
  expect(htmlResponse.headers()['content-type']).toContain('text/html');
  const html = await htmlResponse.text();
  expect(html).toContain('Your privacy first');
  for (const id of ['actionable', 'privacy', 'model-choice', 'workflows', 'devices', 'open-source']) {
    expect(html).toContain(`id="${id}"`);
  }
  expect(html).toMatch(/<meta[^>]+name="description"[^>]+content="[^"]*actionable chats/i);

  const privateBootstrap: string[] = [];
  const sockets: string[] = [];
  page.on('request', request => {
    if (['fetch', 'xhr'].includes(request.resourceType()) && /\/v1\/(?:auth|chats|sync|settings|websocket)(?:\/|$)/.test(new URL(request.url()).pathname)) {
      privateBootstrap.push(request.url());
    }
  });
  page.on('websocket', socket => sockets.push(socket.url()));
  await page.goto(getE2EDebugUrl('/landing'), { waitUntil: 'networkidle' });
  await expect(page.getByTestId('landing-page')).toBeVisible();
  await expect(page.getByTestId('landing-hero')).toBeVisible();
  expect(privateBootstrap).toEqual([]);
  expect(sockets).toEqual([]);

  const icons = await page.getByTestId('landing-hero').locator('.rail-icon').evaluateAll(nodes => nodes.map(node => {
    const style = getComputedStyle(node, '::before');
    return { mask: style.maskImage || style.webkitMaskImage, width: node.getBoundingClientRect().width };
  }));
  expect(icons.length).toBeGreaterThanOrEqual(8);
  expect(icons.every(icon => icon.mask !== 'none' && icon.mask.includes('url(') && icon.width > 0)).toBe(true);

  const heroImage = page.getByTestId('landing-hero-media').locator('.laptop img.device-screen');
  await expect.poll(() => heroImage.evaluate((image: HTMLImageElement) => image.complete && image.naturalWidth > 0)).toBe(true);
  const origin = new URL(page.url()).origin;
  for (const [testId, fragment, workspace] of [
    ['landing-explore-apps', '#apps', 'apps-daily-inspiration-area'],
    ['landing-explore-workflows', '#workflows', 'workflows-start-screen'],
  ] as const) {
    const link = page.getByTestId(testId);
    await expect(link).toHaveAttribute('href', `${origin}/${fragment}`);
    await expect(link).toHaveAttribute('target', '_blank');
    await expect(link).toHaveAttribute('rel', /noopener/);
    const ownerRequests: string[] = [];
    const recordOwnerRequest = (request: import('@playwright/test').Request) => {
      if (/\/v1\/workflows(?:\/|$)/.test(new URL(request.url()).pathname)) ownerRequests.push(request.url());
    };
    page.context().on('request', recordOwnerRequest);
    const [popup] = await Promise.all([page.waitForEvent('popup'), link.click()]);
    await expect(popup).toHaveURL(new RegExp(`/#${fragment.slice(1)}$`));
    await expect(popup.getByTestId(workspace)).toBeVisible({ timeout: 30_000 });
    if (fragment === '#workflows') {
      await expect(popup.getByTestId('all-workflows-grid')).toBeVisible();
      await expect(popup.getByTestId('workflow-landing-card')).toHaveCount(3);
      await expect(popup.getByTestId('workflow-input-composer')).toHaveCount(0);
      await popup.getByTestId('workflow-landing-card').filter({ hasText: 'Daily planning reminder' }).click();
      await expect(popup.getByTestId('workflow-management')).toBeVisible();
      await expect(popup.getByTestId('workflow-template-panel')).toBeVisible();
      await expect(popup.getByTestId('workflow-graph-renderer')).toHaveAttribute('data-read-only', 'true');
      for (const id of ['workflow-input-composer', 'run-workflow', 'delete-workflow', 'workflow-share', 'workflow-export']) {
        await expect(popup.getByTestId(id)).toHaveCount(0);
      }
      expect(ownerRequests).toEqual([]);
    }
    await popup.close();
    page.context().off('request', recordOwnerRequest);
  }
  const upcoming = getUpcomingOpenMatesEventCards(new Date(), origin);
  const cards = page.getByTestId('landing-event-card');
  await expect(cards).toHaveCount(upcoming.length);
  for (let i = 0; i < upcoming.length; i++) {
    await expect(cards.nth(i)).toHaveAttribute('href', upcoming[i].href);
    await expect(cards.nth(i)).toHaveAttribute('target', '_blank');
  }
  await expect(page.getByTestId('landing-events').getByRole('link', { name: /browse/i })).toHaveCount(0);
});

for (const { name, width, height } of [
  { name: 'phone', width: 390, height: 844 },
  { name: 'laptop', width: 1440, height: 900 },
]) {
  // contract-test: direct surface=gui.web assertions=marketing-landing.composer-focus,marketing-landing.destinations,marketing-landing.independent-scroll
  test(`landing composer preserves a guest draft and signup opens basics (${name})`, async ({ page }) => {
    test.setTimeout(90_000);
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
    const signup = page.getByTestId('landing-signup');
    await expect(signup).toHaveAttribute('href', `${new URL(page.url()).origin}/#signup/basics`);
    await signup.click();
    // The app consumes the signup fragment and opens its real account screen.
    await expect(page.locator('input[type="email"][autocomplete="email"]')).toBeVisible({ timeout: 30_000 });
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
