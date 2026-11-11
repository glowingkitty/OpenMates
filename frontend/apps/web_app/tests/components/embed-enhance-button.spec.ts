import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview

const PREVIEW = '/dev/preview/embeds/images/ImageGenerateEmbedFullscreen?chrome=0&theme=light&background=%23dbeafe';
const WIDE = 900;
const NARROW = 420;
test.use({ viewport: { width: 1000, height: 800 }, trace: 'retain-on-failure' });

async function open(page: import('@playwright/test').Page, variant: string, width: number) {
  await page.goto(`${PREVIEW}${variant ? `&variant=${variant}` : ''}&width=${width}`);
  await waitForComponentPreview(page);
}

// contract-test: supporting surface=gui.web assertions=embed-user-edits.enhance.button
test('shows Enhance as a round button that matches the other round buttons when there is room', async ({ page }, testInfo) => {
  await open(page, 'enhanceIdle', WIDE);
  const topBar = page.locator('.embed-top-bar');
  const enhance = topBar.getByTestId('embed-enhance-button');
  await expect(enhance).toBeVisible();
  await expect(enhance).toHaveAccessibleName('Enhance');
  await expect(enhance.locator('.icon_enhance')).toBeVisible();
  await expect(topBar.locator('.more-trigger')).toHaveCount(0);
  const pill = enhance.locator('xpath=..');
  const share = topBar.getByTestId('embed-share-button').locator('xpath=..');
  const pillBox = (await pill.boundingBox())!;
  const shareBox = (await share.boundingBox())!;
  expect(Math.abs(pillBox.width - pillBox.height)).toBeLessThanOrEqual(1);
  expect(Math.abs(pillBox.width - shareBox.width)).toBeLessThanOrEqual(1);
  expect(Math.abs(pillBox.height - shareBox.height)).toBeLessThanOrEqual(1);
  for (const property of ['backgroundColor', 'borderRadius', 'boxShadow'] as const) {
    const [a, b] = await Promise.all([pill, share].map((p) => p.evaluate((el, prop) => getComputedStyle(el)[prop as 'color'], property)));
    expect(a, property).toBe(b);
  }
  await enhance.hover();
  await expect.poll(() => pill.evaluate((el) => getComputedStyle(el).transform)).not.toBe('none');
  await enhance.focus();
  await expect(enhance).toBeFocused();
  await testInfo.attach('enhance-idle-round-900', { body: await page.screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=embed-user-edits.enhance.button
test('lists Enhance with icon and label under More when the bar is too narrow', async ({ page }, testInfo) => {
  await open(page, 'enhanceIdle', NARROW);
  const topBar = page.locator('.embed-top-bar');
  await expect(topBar.getByTestId('embed-enhance-button')).toHaveCount(0);
  await topBar.locator('.more-trigger').click();
  const enhance = topBar.locator('.more-actions').getByTestId('embed-enhance-button');
  await expect(enhance).toBeVisible();
  await expect(enhance.locator('.icon_enhance')).toBeVisible();
  await expect(enhance).toContainText('Enhance');
  await testInfo.attach('enhance-under-more-420', { body: await page.screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=embed-user-edits.enhance.button
test('runs once: shows progress and cannot be pressed a second time', async ({ page }, testInfo) => {
  await open(page, 'enhanceRunning', WIDE);
  const enhance = page.locator('.embed-top-bar').getByTestId('embed-enhance-button');
  await expect(enhance).toBeDisabled();
  await expect(enhance).toHaveAttribute('aria-busy', 'true');
  await expect(enhance).toHaveAccessibleName('Enhancing…');
  await expect(enhance.getByTestId('embed-enhance-progress')).toBeVisible();
  // The progress ring must be drawn in a colour that shows on the dark header pill.
  await expect(enhance.getByTestId('embed-enhance-progress')).toHaveCSS('border-top-color', 'rgb(255, 255, 255)');
  await testInfo.attach('enhance-running-900', { body: await page.screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=embed-user-edits.enhance.button
test('after a failure the button names the error and can be pressed again', async ({ page }, testInfo) => {
  await open(page, 'enhanceFailed', WIDE);
  const enhance = page.locator('.embed-top-bar').getByTestId('embed-enhance-button');
  await expect(enhance).toBeEnabled();
  await expect(enhance).toHaveAttribute('data-enhance-state', 'failed');
  await expect(enhance).toHaveAccessibleName('Enhance failed. Please try again.');
  await testInfo.attach('enhance-failed-900', { body: await page.screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=embed-user-edits.enhance.button
test('is disabled with a reason for a viewer who may not edit', async ({ page }, testInfo) => {
  await open(page, 'enhanceNotAllowed', WIDE);
  const enhance = page.locator('.embed-top-bar').getByTestId('embed-enhance-button');
  await expect(enhance).toBeDisabled();
  await expect(enhance).toHaveAccessibleName("You can't enhance this image");
  await testInfo.attach('enhance-not-allowed-900', { body: await page.screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=embed-user-edits.enhance.button
test('shows no Enhance button when the image view is not given an Enhance action', async ({ page }) => {
  await open(page, '', WIDE);
  await expect(page.locator('.embed-top-bar').getByTestId('embed-enhance-button')).toHaveCount(0);
});
