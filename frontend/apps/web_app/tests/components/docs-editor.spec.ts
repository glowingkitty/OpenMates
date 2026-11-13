// playwright-account: not_required reason=isolated_component_preview
// proof-video: not_required reason=visual_smoke_not_needed
//
// Manual document editor component spec. Save is stubbed by the preview fixture;
// the real save path is proven by the real-stack docs editor E2E.
import { test, expect } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

const EDITOR = '/dev/preview/embeds/docs/DocsEditor?chrome=0';

// contract-test: supporting surface=gui.web assertions=doc-editor.edit.rich-text
test('document editor formats text with a heading, bold and a bulleted list', async ({ page }, testInfo) => {
  await page.goto(`${EDITOR}&variant=blank`);
  await waitForComponentPreview(page);
  const editor = page.getByTestId('docs-editor');
  const content = page.getByTestId('docs-editor-content');
  await expect(content).toBeFocused();
  await testInfo.attach('docs-editor-blank', { body: await editor.screenshot(), contentType: 'image/png' });

  await page.getByTestId('docs-editor-h2').click();
  await page.keyboard.type('Shopping plan');
  await page.keyboard.press('Enter');
  await page.getByTestId('docs-editor-paragraph').click();
  await page.getByTestId('docs-editor-bold').click();
  await page.keyboard.type('Important');
  await page.getByTestId('docs-editor-bold').click();
  await page.keyboard.type(' items below');
  await page.keyboard.press('Enter');
  await page.getByTestId('docs-editor-bullets').click();
  await page.keyboard.type('Apples');
  await page.keyboard.press('Enter');
  await page.keyboard.type('Pears');

  await expect(content.locator('h2')).toHaveText('Shopping plan');
  // Chromium's bold command writes <b>; the saved HTML below must carry <strong>.
  await expect(content.locator('b, strong')).toHaveText('Important');
  await expect(content.locator('ul > li')).toHaveText(['Apples', 'Pears']);
  await testInfo.attach('docs-editor-formatted', { body: await editor.screenshot(), contentType: 'image/png' });

  await page.getByTestId('docs-editor-save').click();
  await expect.poll(() => page.evaluate(() => (window as unknown as { __docsEditorSaved?: string }).__docsEditorSaved ?? ''))
    .toContain('<h2>Shopping plan</h2>');
  const saved = await page.evaluate(() => (window as unknown as { __docsEditorSaved?: string }).__docsEditorSaved ?? '');
  expect(saved).toContain('<strong>Important</strong>');
  expect(saved).toContain('<ul><li>Apples</li><li>Pears</li></ul>');
  expect(saved).not.toContain('<script');
});

// contract-test: supporting surface=gui.web assertions=doc-editor.edit.rich-text
test('document editor loads existing text and shows save errors, with reload on conflict', async ({ page }, testInfo) => {
  await page.goto(`${EDITOR}&variant=conflict`);
  await waitForComponentPreview(page);
  const content = page.getByTestId('docs-editor-content');
  await expect(content.locator('h1')).toHaveText('Garden volunteer notes');
  await expect(content.locator('ul > li')).toHaveCount(2);
  await testInfo.attach('docs-editor-existing', { body: await page.getByTestId('docs-editor').screenshot(), contentType: 'image/png' });

  await content.locator('h1').click();
  await page.keyboard.press('End');
  await page.keyboard.type(' 2');
  await page.getByTestId('docs-editor-save').click();
  await expect(page.getByTestId('docs-editor-error')).toContainText('changed elsewhere');
  await expect(page.getByTestId('docs-editor-reload')).toBeVisible();
  await expect(content).toContainText('Garden volunteer notes 2');
  await testInfo.attach('docs-editor-conflict', { body: await page.getByTestId('docs-editor').screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=doc-editor.edit.rich-text
test('document viewer keeps its page look (before editing)', async ({ page }, testInfo) => {
  await page.goto('/dev/preview/embeds/docs/DocsEmbedFullscreen?chrome=0');
  await waitForComponentPreview(page);
  await expect(page.getByTestId('embed-fullscreen-overlay')).toBeVisible();
  await testInfo.attach('docs-viewer', { body: await page.screenshot(), contentType: 'image/png' });
});
