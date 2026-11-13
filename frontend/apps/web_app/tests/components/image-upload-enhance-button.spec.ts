import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview

const PREVIEW = '/dev/preview/embeds/images/ImageEmbedFullscreen?chrome=0&theme=light&background=%23dbeafe';
const WIDE = 900;
test.use({ viewport: { width: 1000, height: 800 }, trace: 'retain-on-failure' });

async function open(page: import('@playwright/test').Page, variant: string, width: number) {
  await page.goto(`${PREVIEW}${variant ? `&variant=${variant}` : ''}&width=${width}`);
  await waitForComponentPreview(page);
}

// contract-test: supporting surface=gui.web assertions=embed-user-edits.enhance.button
test('shows Enhance as a round button for an uploaded photo', async ({ page }, testInfo) => {
  await open(page, 'enhanceIdle', WIDE);
  const topBar = page.locator('.embed-top-bar');
  const enhance = topBar.getByTestId('embed-enhance-button');
  await expect(enhance).toBeVisible();
  await expect(enhance).toBeEnabled();
  await expect(enhance).toHaveAccessibleName('Enhance');
  await expect(enhance.locator('.icon_enhance')).toBeVisible();
  const pillBox = (await enhance.locator('xpath=..').boundingBox())!;
  expect(Math.abs(pillBox.width - pillBox.height)).toBeLessThanOrEqual(1);
  await testInfo.attach('upload-enhance-idle-900', { body: await page.screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=embed-user-edits.enhance.button
test('shows progress and cannot be pressed twice while an uploaded photo is enhanced', async ({ page }, testInfo) => {
  await open(page, 'enhanceRunning', WIDE);
  const enhance = page.locator('.embed-top-bar').getByTestId('embed-enhance-button');
  await expect(enhance).toBeDisabled();
  await expect(enhance).toHaveAttribute('aria-busy', 'true');
  await expect(enhance.getByTestId('embed-enhance-progress')).toBeVisible();
  await testInfo.attach('upload-enhance-running-900', { body: await page.screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=embed-user-edits.enhance.button
test('is disabled with a reason for an uploaded photo the viewer may not edit', async ({ page }, testInfo) => {
  await open(page, 'enhanceNotAllowed', WIDE);
  const enhance = page.locator('.embed-top-bar').getByTestId('embed-enhance-button');
  await expect(enhance).toBeDisabled();
  await expect(enhance).toHaveAccessibleName("You can't enhance this image");
  await testInfo.attach('upload-enhance-not-allowed-900', { body: await page.screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=embed-user-edits.enhance.button
test('shows no Enhance button for an uploaded photo without an Enhance action', async ({ page }) => {
  await open(page, '', WIDE);
  await expect(page.locator('.embed-top-bar').getByTestId('embed-enhance-button')).toHaveCount(0);
});
