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

for (const width of [700, 1280]) {
  // contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering,chats.rendering.inline-entity-interaction
  test(`document HTML and page screenshot stay horizontally centered at ${width}px`, async ({ page }, testInfo) => {
    test.setTimeout(90_000);
    await page.setViewportSize({ width, height: 900 });
    for (const variant of ['htmlContent', 'generatedDocxArtifact']) {
      await page.goto(`/dev/preview/embeds/docs/DocsEmbedPreview?variant=${variant}&chrome=0&width=${width}&context=chat`);
      await waitForComponentPreview(page);
      const viewport = page.locator('.doc-page-viewport');
      await expect.poll(() => viewport.evaluate(element => element.clientWidth)).toBeGreaterThan(400);
      const content = page.locator(variant === 'htmlContent' ? '.doc-page' : '.doc-page-image');
      await expect(content).toBeVisible();
      if (variant === 'htmlContent') await expect(content.locator('h1')).toHaveText('Project Architecture Overview');
      else await expect.poll(() => content.evaluate(image => (image as HTMLImageElement).naturalWidth)).toBe(794);
      await expect.poll(() => viewport.evaluate(element => {
        const viewport = element.getBoundingClientRect();
        const page = element.querySelector('.doc-page, .doc-page-image')!.getBoundingClientRect();
        return Math.abs((page.left + page.right) / 2 - (viewport.left + viewport.right) / 2);
      })).toBeLessThanOrEqual(1);
      const geometry = await viewport.evaluate(element => {
        const viewport = element.getBoundingClientRect();
        const page = element.querySelector('.doc-page, .doc-page-image')!.getBoundingClientRect();
        return { left: page.left - viewport.left, right: viewport.right - page.right, width: page.width, viewportWidth: viewport.width };
      });
      expect(geometry.width).toBeGreaterThan(0);
      expect(geometry.width).toBeLessThanOrEqual(geometry.viewportWidth + 1);
      expect(geometry.left).toBeGreaterThanOrEqual(-1);
      expect(geometry.right).toBeGreaterThanOrEqual(-1);
      await expect(page.getByTestId('preview-download')).toBeVisible();
      await testInfo.attach(`document-centered-${variant}-${width}`, { body: await page.getByTestId('component-preview-canvas').screenshot(), contentType: 'image/png' });
    }
  });
}
