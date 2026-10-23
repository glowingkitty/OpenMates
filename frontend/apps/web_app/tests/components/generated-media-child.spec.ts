import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview

// contract-test: supporting surface=gui.web assertions=app-skills.media.visible-assistant-results
test('a generated image child displays its actual media from a public preview URL', async ({ page }, testInfo) => {
  await page.goto('/dev/preview/embeds/images/ImageGenerateEmbedPreview?chrome=0&variant=publicChild');
  await waitForComponentPreview(page);
  const image = page.locator('.preview-image');
  await expect(image).toBeVisible();
  await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.naturalWidth)).toBeGreaterThan(0);
  await expect(page.locator('.card-source')).toBeVisible();
  await expect(page.locator('.card-source')).toContainText(/Gemini|gemini/);
  await expect(page.locator('.card-source')).toContainText('Google');
  await expect(page.getByTestId('result-card-title')).toContainText('A serene mountain landscape');
  await expect(page.getByTestId('result-card-title')).toBeVisible();
  await testInfo.attach('image-prompt-and-provider', { body: await page.screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=app-skills.media.parent-children-and-attribution
test('generated image fullscreen retains the complete prompt and actual model', async ({ page }, testInfo) => {
  await page.goto('/dev/preview/embeds/images/ImageGenerateEmbedFullscreen?chrome=0&variant=completePrompt');
  await waitForComponentPreview(page);
  await expect(page.getByTestId('component-preview-viewport')).toContainText(
    'An observatory on a windswept coast, blue-hour fog, copper telescope, and three bright stars above the horizon',
  );
  await expect(page.locator('.generated-by-text')).toContainText(/Gemini|gemini/);
  await expect(page.locator('.generated-by-text')).toContainText('Google');
  await expect(page.locator('.embed-header')).toContainText('observatory_coast.png');
  await page.locator('.prompt-text').scrollIntoViewIfNeeded();
  await expect(page.locator('.prompt-text')).toBeInViewport();
  await expect(page.locator('.generated-by-text')).toBeInViewport();
  await testInfo.attach('image-filename-and-full-prompt', { body: await page.screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=app-skills.media.visible-assistant-results,app-skills.media.parent-children-and-attribution
test('generated 3D child exposes its encrypted GLB through an owner-scoped download', async ({ page }) => {
  await page.route('**/v1/generated-assets/6bfe4822-f203-427e-92d2-e30fc1e6940d/files/master/download-url', async (route) => {
    await route.fulfill({ json: { download_url: `${new URL(route.request().url()).origin}/preview-generated-model.glb` } });
  });
  await page.route('**/preview-generated-model.glb', async (route) => {
    await route.fulfill({ body: 'glTF', headers: { 'Content-Type': 'model/gltf-binary', 'Content-Disposition': 'attachment; filename="model.glb"' } });
  });
  await page.goto('/dev/preview/embeds/models3d/Model3DGenerateEmbedFullscreen?chrome=0&variant=privateModel');
  await waitForComponentPreview(page);
  await expect(page.getByTestId('models3d-generate-fullscreen')).toContainText('A textured stone arch with moss and carved details');
  await expect(page.getByTestId('models3d-generate-fullscreen')).toContainText('hitem3dv2.1');
  const download = page.waitForEvent('download');
  await page.getByTestId('models3d-download-model').click();
  await expect(await download).toBeTruthy();
});

// contract-test: supporting surface=gui.web assertions=app-skills.media.parent-children-and-attribution,app-skills.media.visible-assistant-results
test('generated parent opens both actual image children and drills into the complete prompt and model', async ({ page }) => {
  await page.goto('/dev/preview/embeds/GeneratedMediaGroupEmbedFullscreen?chrome=0');
  await waitForComponentPreview(page);
  await expect(page.getByTestId('generated-media-group-fullscreen')).toBeVisible();
  await expect(page.getByTestId('generated-media-child-card')).toHaveCount(2);
  await expect(page.locator('.preview-image')).toHaveCount(2);
  await page.getByTestId('generated-media-child-card').first().click();
  await expect(page.getByTestId('component-preview-viewport')).toContainText('A stone lighthouse at dawn with sea mist and three gulls');
  await expect(page.getByTestId('component-preview-viewport')).toContainText(/Gemini|gemini/);
});

// contract-test: supporting surface=gui.web assertions=app-skills.media.visible-assistant-results
test('completed media parent remains a visible card with its output count', async ({ page }) => {
  await page.goto('/dev/preview/embeds/GeneratedMediaGroupEmbedPreview?chrome=0');
  await waitForComponentPreview(page);
  await expect(page.getByTestId('generated-media-parent-preview')).toBeVisible();
  await expect(page.getByTestId('generated-media-parent-preview')).toContainText('2');
});
