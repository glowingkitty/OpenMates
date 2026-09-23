import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
const PREVIEW = '/dev/preview/projects/ProjectRemotePreviewCard?chrome=0';

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    window.addEventListener('project-preview-action', (event) => {
      const root = document.documentElement;
      const actions = JSON.parse(root.dataset.projectPreviewActions || '[]');
      actions.push((event as CustomEvent<string>).detail);
      root.dataset.projectPreviewActions = JSON.stringify(actions);
    }, true);
  });
});

// contract-test: supporting surface=gui.web assertions=projects.surface.semantic-parity,projects.files.no-server-decryption-authority
test('a virtual file preview keeps viewing and deliberate import as distinct actions', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto(`${PREVIEW}&width=420`);
  await waitForComponentPreview(page);
  const card = page.getByTestId('project-remote-preview-card');
  await expect(card).toBeVisible();
  await expect(card).toContainText('example.ts');
  await expect(card).toContainText('Example repository');
  await expect(card).toContainText('Remote preview · loaded on demand · not stored in OpenMates');
  await expect(page.getByTestId('project-remote-preview-upload')).toHaveText('Import to OpenMates');
  await expect(page.getByTestId('project-remote-preview-truncated')).toHaveCount(0);
  const open = page.getByTestId('project-remote-preview-open');
  await open.hover();
  await open.focus();
  await expect(open).toBeFocused();
  await page.keyboard.press('Enter');
  await expect.poll(() => page.evaluate(() => document.documentElement.dataset.projectPreviewActions)).toBe('["open"]');
  await page.getByTestId('project-remote-preview-upload').click();
  await expect.poll(() => page.evaluate(() => document.documentElement.dataset.projectPreviewActions)).toBe('["open","import"]');
  await testInfo.attach('remote-preview-desktop', { body: await card.screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=projects.surface.semantic-parity,projects.uploads.project-wrapped
test('an incomplete remote preview explains its limit and cannot be imported', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${PREVIEW}&variant=truncated&width=350`);
  await waitForComponentPreview(page);
  const card = page.getByTestId('project-remote-preview-card');
  await expect(card).toBeVisible();
  await expect(page.getByTestId('project-remote-preview-truncated')).toBeVisible();
  await expect(page.getByTestId('project-remote-preview-truncated')).toHaveText('Preview is truncated at the safe read limit.');
  await expect(page.getByTestId('project-remote-preview-upload')).toBeDisabled();
  const previewBounds = await card.locator('.unified-embed-preview').boundingBox();
  const shellBounds = await card.locator('.remote-preview-shell').boundingBox();
  expect(previewBounds).not.toBeNull();
  expect(shellBounds).not.toBeNull();
  expect(previewBounds!.y + previewBounds!.height).toBeLessThanOrEqual(shellBounds!.y + shellBounds!.height + 1);
  await page.getByTestId('project-remote-preview-open').click();
  await expect.poll(() => page.evaluate(() => document.documentElement.dataset.projectPreviewActions)).toBe('["open"]');
  await testInfo.attach('remote-preview-mobile-incomplete', { body: await card.screenshot(), contentType: 'image/png' });
  await page.goto(`${PREVIEW}&variant=loadingImport&width=350`);
  await waitForComponentPreview(page);
  await expect(page.getByTestId('project-remote-preview-upload')).toBeDisabled();
});
