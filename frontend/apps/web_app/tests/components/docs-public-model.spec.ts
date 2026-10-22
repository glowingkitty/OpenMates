import { createRequire } from 'node:module';
import { resolve } from 'node:path';
import { readFile } from 'node:fs/promises';
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
// contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering
test('real public document model renders and downloads as a DOCX', async ({ page }) => {
  await page.goto('/dev/preview/embeds/docs/DocsEmbedFullscreen?variant=realModel&chrome=0');
  await waitForComponentPreview(page);

  const overlay = page.getByTestId('embed-fullscreen-overlay');
  await expect(overlay.locator('.doc-page-content h1')).toHaveText('Community Garden Volunteer Guide');
  await expect(overlay.locator('.doc-page-content li')).toHaveCount(6);
  await expect(overlay.locator('.doc-page-content strong')).toContainText(['[Coordinator Name]', '[Phone Number / Radio Channel]']);
  await expect(overlay).not.toContainText('No document content available');
  await page.screenshot({ path: test.info().outputPath('public-docx-model.png') });

  const moreActions = overlay.getByRole('button', { name: 'More', exact: true });
  if (await moreActions.isVisible()) await moreActions.click();
  const downloadButton = overlay.getByTestId('embed-download-button');
  await expect(downloadButton).toBeVisible();
  const [download] = await Promise.all([page.waitForEvent('download'), downloadButton.click()]);
  expect(download.suggestedFilename()).toBe('Volunteer_Onboarding_Guide.docx');
  const bytes = await readFile(await download.path());
  expect(bytes.length).toBeGreaterThan(1_000);
  expect(bytes.subarray(0, 2).toString()).toBe('PK');
});

// contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering,chats.rendering.inline-entity-interaction
test('document preview downloads a real DOCX directly with owner PII masked', async ({ page }, testInfo) => {
  const uiRequire = createRequire(resolve(__dirname, '../../../../packages/ui/package.json'));
  const JSZip = uiRequire('jszip');
  await page.goto('/dev/preview/embeds/docs/DocsDownloadFixture?chrome=0&width=700');
  await waitForComponentPreview(page);
  const fixture = page.getByTestId('docs-download-fixture');
  const content = fixture.locator('.doc-page-content');
  await expect(content).toContainText('[EMAIL_1]');
  await expect(content).not.toContainText('alex@example.test');
  await expect(fixture.getByTestId('preview-download')).toBeVisible();
  await testInfo.attach('DocsEmbedPreview-direct-download-masked', { body: await page.getByTestId('component-preview-canvas').screenshot(), contentType: 'image/png' });
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    fixture.getByTestId('preview-download').click(),
  ]);
  expect(download.suggestedFilename()).toBe('masked-notes.docx');
  await expect(fixture).toHaveAttribute('data-expanded', '0');
  const bytes = await readFile(await download.path());
  expect(bytes.length).toBeGreaterThan(1_000);
  expect(bytes.subarray(0, 2).toString()).toBe('PK');
  const archive = await JSZip.loadAsync(bytes);
  expect(archive.file('[Content_Types].xml')).toBeTruthy();
  expect(archive.file('word/document.xml')).toBeTruthy();
  const entries = Object.values(archive.files) as { dir: boolean; async(type: 'string'): Promise<string> }[];
  const exportedContent = (await Promise.all(entries.filter(entry => !entry.dir).map(entry => entry.async('string')))).join('\n');
  expect(exportedContent).toContain('[EMAIL_1]');
  expect(exportedContent).not.toContain('alex@example.test');
  expect(exportedContent).not.toContain('unsafe_document_marker');
});
