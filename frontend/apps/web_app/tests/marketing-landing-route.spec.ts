import { expect, test } from './helpers/cookie-audit';

// eslint-disable-next-line @typescript-eslint/no-require-imports
const { getE2EDebugUrl } = require('./signup-flow-helpers');

// contract-test: direct surface=gui.web assertions=marketing-landing.independent-scroll,marketing-landing.feature-layout,marketing-landing.destinations,marketing-landing.real-screenshots,marketing-landing.public-content
test('public landing server-renders and opens real app workspaces', async ({ page }) => {
  test.setTimeout(90_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  const htmlResponse = await page.request.get(getE2EDebugUrl('/landing'));
  expect(htmlResponse.ok()).toBe(true);
  expect(htmlResponse.headers()['content-type']).toContain('text/html');
  const html = await htmlResponse.text();
  expect(html).toContain('Your privacy first');
  for (const id of ['actionable', 'privacy', 'workflows', 'devices', 'open-source']) {
    expect(html).toContain(`id="${id}"`);
  }
  expect(html).toMatch(/<meta[^>]+name="description"[^>]+content="[^"]*actionable chats/i);

  const privateBootstrap: string[] = [];
  const sockets: string[] = [];
  page.on('request', request => {
    if (['fetch', 'xhr'].includes(request.resourceType()) && /\/api\//.test(new URL(request.url()).pathname)) {
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

  const heroImage = page.locator('.hero-desktop');
  await expect.poll(() => heroImage.evaluate((image: HTMLImageElement) => image.complete && image.naturalWidth > 0)).toBe(true);
  const origin = new URL(page.url()).origin;
  for (const [testId, fragment, workspace] of [
    ['landing-explore-apps', '#apps', 'apps-daily-inspiration-area'],
    ['landing-explore-workflows', '#workflows', 'workflows-page'],
  ] as const) {
    const link = page.getByTestId(testId);
    await expect(link).toHaveAttribute('href', `${origin}/${fragment}`);
    await expect(link).toHaveAttribute('target', '_blank');
    await expect(link).toHaveAttribute('rel', /noopener/);
    const [popup] = await Promise.all([page.waitForEvent('popup'), link.click()]);
    await expect(popup).toHaveURL(new RegExp(`/#${fragment.slice(1)}$`));
    await expect(popup.getByTestId(workspace)).toBeVisible({ timeout: 30_000 });
    await popup.close();
  }
  await expect(page.getByRole('link', { name: 'Browse events' })).toHaveAttribute('href', `${origin}/events`);
  await page.getByRole('link', { name: 'Browse events' }).click();
  await expect(page).toHaveURL(`${origin}/events`);
  await expect(page.getByRole('heading', { name: 'OpenMates Events', level: 1 })).toBeVisible();
});

for (const { name, width, height } of [
  { name: 'phone', width: 390, height: 844 },
  { name: 'laptop', width: 1440, height: 900 },
]) {
  // contract-test: direct surface=gui.web assertions=marketing-landing.composer-focus,marketing-landing.destinations
  test(`landing composer preserves a guest draft and signup opens basics (${name})`, async ({ page }) => {
    test.setTimeout(90_000);
    await page.setViewportSize({ width, height });
    await page.goto(getE2EDebugUrl('/landing'), { waitUntil: 'domcontentloaded' });
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
