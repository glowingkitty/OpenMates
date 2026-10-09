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
