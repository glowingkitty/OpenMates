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
  await expect(card).toHaveAttribute('aria-label', /from connected source Example repository/);
  await expect(card.locator('.unified-embed-preview')).toBeVisible();
  await expect(card).not.toContainText('Remote preview · loaded on demand · not stored in OpenMates');
  await expect(page.getByTestId('project-remote-preview-meta')).toHaveCount(0);
  await expect(page.getByTestId('project-remote-preview-upload')).toHaveAttribute('aria-label', 'Import to OpenMates');
  await expect(page.getByTestId('project-remote-preview-truncated')).toHaveCount(0);
  const open = card.locator('.unified-embed-preview');
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
  await expect(page.getByTestId('project-remote-preview-truncated')).toHaveText('Preview limited');
  await expect(page.getByTestId('project-remote-preview-upload')).toHaveCount(0);
  const previewBounds = await card.locator('.unified-embed-preview').boundingBox();
  const shellBounds = await card.boundingBox();
  expect(previewBounds).not.toBeNull();
  expect(shellBounds).not.toBeNull();
  expect(previewBounds!.y + previewBounds!.height).toBeLessThanOrEqual(shellBounds!.y + shellBounds!.height + 1);
  await card.locator('.unified-embed-preview').click();
  await expect.poll(() => page.evaluate(() => document.documentElement.dataset.projectPreviewActions)).toBe('["open"]');
  await testInfo.attach('remote-preview-mobile-incomplete', { body: await card.screenshot(), contentType: 'image/png' });
  await page.goto(`${PREVIEW}&variant=loadingImport&width=350`);
  await waitForComponentPreview(page);
  await expect(page.getByTestId('project-remote-preview-upload')).toBeDisabled();
});

// contract-test: supporting surface=gui.web assertions=projects.surface.semantic-parity,projects.files.no-server-decryption-authority,projects.files.connected-embed-previews
test('a listed binary file uses the regular file embed with metadata and an open action', async ({ page }) => {
  await page.goto(`${PREVIEW}&variant=unsupported&width=420`);
  await waitForComponentPreview(page);
  await expect(page.getByTestId('project-remote-preview-card')).toContainText('diagram.png');
  await expect(page.getByTestId('project-remote-preview-open')).toHaveCount(0);
  await expect(page.getByTestId('project-remote-preview-upload')).toHaveCount(0);
  await expect(page.getByTestId('project-remote-preview-card')).toContainText('Open for file details and download');
  await expect(page.getByTestId('project-remote-preview-card')).toHaveAttribute('data-file-kind', 'image');
  await page.getByTestId('project-remote-preview-card').locator('.unified-embed-preview').click();
  await expect.poll(() => page.evaluate(() => document.documentElement.dataset.projectPreviewActions)).toBe('["open"]');
});

// contract-test: supporting surface=gui.web assertions=projects.surface.semantic-parity,projects.files.no-server-decryption-authority
test('unread files render typed embed cards with size and an open prompt', async ({ page }) => {
  await page.goto(`${PREVIEW}&variant=pending&width=420`);
  await waitForComponentPreview(page);
  const codeCard = page.getByTestId('project-remote-preview-card');
  await expect(codeCard).toHaveAttribute('data-file-kind', 'code');
  await expect(codeCard.locator('.unified-embed-preview')).toHaveAttribute('data-app-id', 'code');
  await expect(codeCard).toContainText('example.ts');
  await expect(codeCard.getByTestId('project-remote-preview-pending')).toContainText('2.0 KiB');
  await expect(codeCard.getByTestId('project-remote-preview-pending')).toContainText('Open to render preview');
  await expect(codeCard.getByTestId('project-remote-preview-pending')).not.toContainText('example.ts');
  await expect(page.getByTestId('project-remote-preview-upload')).toHaveCount(0);
  await page.goto(`${PREVIEW}&variant=sheet&width=420`);
  await waitForComponentPreview(page);
  const sheetCard = page.getByTestId('project-remote-preview-card');
  await expect(sheetCard).toHaveAttribute('data-file-kind', 'sheet');
  await expect(sheetCard.locator('.unified-embed-preview')).toHaveAttribute('data-app-id', 'files');
  await expect(sheetCard).toContainText('budget.xlsx');
  await expect(sheetCard).toContainText('4.0 KiB');
  await page.goto(`${PREVIEW}&variant=plist&width=420`);
  await waitForComponentPreview(page);
  const plistCard = page.getByTestId('project-remote-preview-card');
  await expect(plistCard).toHaveAttribute('data-file-kind', 'code');
  await expect(plistCard.locator('.unified-embed-preview')).toHaveAttribute('data-app-id', 'code');
  await expect(plistCard).toContainText('Info.plist');
  await expect(plistCard).toContainText('1.2 KiB');
});
