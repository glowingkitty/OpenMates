import { createCipheriv } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// Matches aes_key of the generatedPdfArtifact preview variant (32 bytes 0..31).
const AES_KEY = Buffer.from(Array.from({ length: 32 }, (_, index) => index));
const PDF_TEXT = '%PDF-1.7\n% generated document artifact\n%%EOF\n';

function encryptArtifact(plain: Buffer): Buffer {
  const nonce = Buffer.alloc(12, 7);
  const cipher = createCipheriv('aes-256-gcm', AES_KEY, nonce);
  return Buffer.concat([nonce, cipher.update(plain), cipher.final(), cipher.getAuthTag()]);
}

// contract-test: supporting surface=gui.web assertions=doc-editor.export.latest-version
test('generated document offers a PDF download of the stored artifact next to Word', async ({ page }) => {
  await page.route('**/v1/embeds/presigned-url**', (route) => route.fulfill({
    json: { url: 'https://artifacts.example.test/generated-artifact.pdf.bin' },
  }));
  await page.route('https://artifacts.example.test/**', (route) => route.fulfill({
    status: 200,
    contentType: 'application/octet-stream',
    body: encryptArtifact(Buffer.from(PDF_TEXT)),
  }));

  await page.goto('/dev/preview/embeds/docs/DocsEmbedFullscreen?variant=generatedPdfArtifact&chrome=0');
  await waitForComponentPreview(page);

  const overlay = page.getByTestId('embed-fullscreen-overlay');
  const moreActions = overlay.getByRole('button', { name: 'More', exact: true });
  if (await moreActions.isVisible()) await moreActions.click();
  await expect(overlay.getByTestId('embed-download-button')).toBeVisible();
  const pdfButton = overlay.getByTestId('embed-download-pdf-button');
  await expect(pdfButton).toBeVisible();
  await expect(overlay.getByTestId('embed-download-button')).toContainText('Download Word');
  await expect(pdfButton).toContainText('Download PDF');
  await page.screenshot({ path: test.info().outputPath('docs-pdf-download-option.png') });

  const [download] = await Promise.all([page.waitForEvent('download'), pdfButton.click()]);
  expect(download.suggestedFilename()).toBe('generated-artifact.pdf');
  const bytes = await readFile(await download.path());
  expect(bytes.subarray(0, 4).toString()).toBe('%PDF');
});

// contract-test: supporting surface=gui.web assertions=doc-editor.export.latest-version
test('documents without a PDF artifact show Word only', async ({ page }) => {
  await page.goto('/dev/preview/embeds/docs/DocsEmbedFullscreen?variant=generatedDocxArtifact&chrome=0');
  await waitForComponentPreview(page);
  const overlay = page.getByTestId('embed-fullscreen-overlay');
  await expect(overlay.getByTestId('embed-download-pdf-button')).toHaveCount(0);
  const moreActions = overlay.getByRole('button', { name: 'More', exact: true });
  if (await moreActions.isVisible()) await moreActions.click();
  await expect(overlay.getByTestId('embed-download-button')).toContainText('Download');
  await expect(overlay.getByTestId('embed-download-button')).not.toContainText('Word');
});
