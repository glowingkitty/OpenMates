import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
const root = '/dev/preview/embeds/web/';
async function preview(page: import('@playwright/test').Page, name: string, width: number, variant = '') {
  await page.setViewportSize({ width, height: width < 600 ? 844 : 1000 });
  const query = new URLSearchParams({ chrome: '0', theme: 'light', background: '#dbeafe', width: String(width) });
  if (variant) query.set('variant', variant);
  await page.goto(`${root}${name}?${query}`);
  await waitForComponentPreview(page);
}

// contract-test: supporting surface=gui.web assertions=web-browse.embed-and-observation,web-browse.truthful-completion,web-browse.structured-data,web-browse.budgets-and-stop
test('Browse preview reports the task outcome and keeps saved structured results readable', async ({ page }, info) => {
  // This case mounts multiple independently compiled previews on a cold Vite runner.
  test.setTimeout(90_000);
  await preview(page, 'BrowseEmbedPreview', 1280);
  const card = page.getByTestId('embed-preview');
  await expect(card).toContainText('Needs your input');
  await expect(card).toContainText('Example Domain');
  const icon = card.locator('[data-skill-icon="website"]');
  await expect(icon).toBeVisible();
  const iconDimensions = await icon.evaluate(async element => {
    const mask = getComputedStyle(element).maskImage;
    const url = /^url\(["']?(.*?)["']?\)$/.exec(mask)?.[1];
    if (!url) return [0, 0];
    const image = new Image(); image.src = url;
    try { await image.decode(); return [image.naturalWidth, image.naturalHeight]; }
    catch { return [0, 0]; }
  });
  expect(iconDimensions[0]).toBeGreaterThan(0);
  expect(iconDimensions[1]).toBeGreaterThan(0);
  await card.focus();
  await expect(card).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.locator('html')).toHaveAttribute('data-browse-opened', 'true');
  await info.attach('browse-preview-laptop', { body: await card.screenshot({ path: info.outputPath('browse-preview-laptop.png') }), contentType: 'image/png' });

  await preview(page, 'BrowseEmbedPreview', 390, 'mobile');
  await expect(card).toContainText('Needs your input');
  const bounds = await card.boundingBox();
  expect(bounds!.width).toBeLessThanOrEqual(390);
  await info.attach('browse-preview-phone', { body: await card.screenshot({ path: info.outputPath('browse-preview-phone.png') }), contentType: 'image/png' });

  await preview(page, 'BrowseEmbedPreview', 1280, 'processing');
  const watch = page.getByTestId('browse-preview').getByRole('button', { name: 'Watch browser', exact: true });
  await expect(card).toHaveAttribute('role', 'group');
  await expect(watch).toBeEnabled();
  await watch.click();
  await expect(page.locator('html')).toHaveAttribute('data-browse-opened', 'true');
  for (const variant of ['error', 'cancelled', 'completed']) {
    await preview(page, 'BrowseEmbedPreview', 1280, variant);
    await expect(page.getByTestId('browse-preview')).toBeVisible();
    await expect(card).toContainText(variant === 'error' ? 'Failed' : variant === 'cancelled' ? 'Cancelled' : 'Completed');
  }
  await preview(page, 'BrowseEmbedPreview', 1280, 'processingReady');
  const mockControl = async (status: number) => page.route('**/v1/apps/web/browse/*/control', route => route.fulfill({
    status: route.request().method() === 'OPTIONS' ? 204 : status,
    headers: { 'access-control-allow-origin': new URL(page.url()).origin, 'access-control-allow-credentials': 'true',
      'access-control-allow-methods': 'POST, OPTIONS', 'access-control-allow-headers': 'content-type' },
    contentType: 'application/json', body: route.request().method() === 'OPTIONS' ? '' : JSON.stringify({
      session_id: '11111111-1111-4111-8111-111111111111', status: 'paused',
    }),
  }));
  await mockControl(503);
  await card.locator('.stop-button').click();
  await expect(card.getByRole('alert')).toBeVisible();
  await expect(card).toHaveAttribute('data-status', 'processing');
  await page.unroute('**/v1/apps/web/browse/*/control');
  await mockControl(200);
  await card.locator('.stop-button').click();
  await expect(card).toHaveAttribute('data-status', 'cancelled');
  await page.unroute('**/v1/apps/web/browse/*/control');
  await preview(page, 'BrowseEmbedFullscreen', 1280);
  await expect(page.getByTestId('browse-fullscreen')).toContainText('No saved screenshot is available.');
  await page.getByText('Structured data', { exact: true }).click();
  const output = page.getByTestId('browse-json');
  await expect(output).toContainText('"items": []');
  await expect(output).toContainText('"missing": null');
  await expect(page.getByRole('button', { name: 'Take control', exact: true })).toHaveCount(0);
});

for (const width of [1280, 390]) {
  // contract-test: supporting surface=gui.web assertions=web-browse.exclusive-takeover,web-browse.sign-in,web-browse.lifecycle,web-browse.embed-and-observation
  test(`Browse viewer watch, takeover, consent, continuation and close at ${width}px`, async ({ page }, info) => {
    await preview(page, 'BrowseSessionViewer', width);
    const viewer = page.getByTestId('browse-session-viewer');
    await expect(page.getByAltText('Live browser', { exact: true })).toBeVisible();
    const viewport = page.getByRole('button', { name: 'Live browser', exact: true });
    await expect(viewport).toBeDisabled();
    await expect(viewer).toContainText('8 / 100 credits');
    const imageBox = await page.getByTestId('browse-frame').boundingBox();
    const viewportBox = await viewport.boundingBox();
    expect(imageBox!.width / imageBox!.height).toBeCloseTo(1.6, 2);
    expect(viewportBox!.height).toBeCloseTo(imageBox!.height, 0);
    await expect(viewer).toContainText('You are watching');
    await expect(page.getByLabel('Text for the website', { exact: true })).toHaveCount(0);
    const take = page.getByRole('button', { name: 'Take control', exact: true });
    await take.hover(); await take.focus(); await expect(take).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(viewer).toContainText('You have control');
    await expect(viewport).toBeEnabled();
    await viewport.click();
    const coordinates = JSON.parse(await page.locator('html').getAttribute('data-browse-coordinates') || '[]');
    expect(coordinates[0]).toBeCloseTo(640, 0);
    expect(coordinates[1]).toBeCloseTo(400, 0);
    await viewport.focus();
    await page.keyboard.press('Enter');
    await expect(page.locator('html')).toHaveAttribute('data-browse-input-kind', 'key');
    const input = page.getByLabel('Text for the website', { exact: true });
    await expect(input).toHaveAttribute('type', 'password');
    await input.fill('Synthetic input');
    await page.getByRole('button', { name: 'Send text', exact: true }).click();
    await expect(input).toHaveValue('');
    await page.getByRole('button', { name: 'Tab', exact: true }).click();
    await page.getByRole('button', { name: 'Scroll down', exact: true }).click();
    await info.attach(`browse-manual-${width}`, { body: await viewer.screenshot({ path: info.outputPath(`browse-manual-${width}.png`) }), contentType: 'image/png' });
    await page.getByRole('button', { name: 'Let AI continue', exact: true }).click();
    await expect(page.locator('html')).toHaveAttribute('data-browse-continued', '11111111-1111-4111-8111-111111111111');
    await expect(viewer).toContainText('Browsing');
    await page.getByRole('button', { name: 'Pause', exact: true }).click();
    await expect(viewer).toContainText('The browser is paused and compute is free');
    await expect(page.getByRole('button', { name: 'Pause', exact: true })).toBeDisabled();
    await page.getByRole('button', { name: 'Close browser', exact: true }).click();
    await expect(viewer).toContainText('Browser closed');
    await expect(input).toHaveCount(0);

    await preview(page, 'BrowseSessionViewer', width, 'signIn');
    await expect(input).toBeVisible();
    await input.fill('Synthetic account');
    await page.getByRole('button', { name: 'Send text', exact: true }).click();
    const notice = page.getByRole('region', { name: 'Before you sign in', exact: true });
    await expect(notice).toContainText('Relevant page content may be sent to our AI providers');
    await expect(notice).toContainText('https://example.com');
    await expect(page.getByRole('button', { name: 'Let AI continue', exact: true })).toBeDisabled();
    await info.attach(`browse-consent-${width}`, { body: await viewer.screenshot({ path: info.outputPath(`browse-consent-${width}.png`) }), contentType: 'image/png' });
    await notice.getByRole('button', { name: 'Cancel', exact: true }).click();
    await expect(notice).toHaveCount(0);
    await input.fill('Synthetic account');
    await page.getByRole('button', { name: 'Send text', exact: true }).click();
    await notice.getByRole('button', { name: 'Continue to sign in', exact: true }).click();
    await expect(notice).toHaveCount(0);
    await expect(input).toHaveValue('');
    await preview(page, 'BrowseSessionViewer', width, 'expired');
    await expect(viewer).toContainText('Session expired');
    await expect(viewer).toContainText('No saved screenshot is available.');
    await expect(viewer).not.toContainText('Waiting for the browser');
    await expect(viewer).not.toContainText('You are watching');
    await expect(page.getByRole('button', { name: 'Take control', exact: true })).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  });
}
