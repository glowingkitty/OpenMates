// playwright-account: not_required reason=isolated_component_preview
import { test, expect } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

function path(component: 'Fullscreen' | 'Preview', width: number, variant = '') {
  const query = new URLSearchParams({ width: String(width), chrome: '0', theme: 'light', background: '#dbeafe', variant });
  return `/dev/preview/embeds/design/DesignDocumentEmbed${component}?${query}`;
}

// contract-test: supporting surface=gui.web assertions=design-editor.view.validated-scene
test('previews the first Design artboard within the result card', async ({ page }, info) => {
  await page.setViewportSize({ width: 1280, height: 860 });
  await page.goto(path('Preview', 1280));
  await waitForComponentPreview(page);
  const preview = page.getByTestId('embed-preview');
  await expect(preview).toContainText('Trail Club');
  const canvas = page.getByTestId('design-embed-thumbnail').locator('canvas');
  await expect(canvas).toBeVisible();
  await expect.poll(async () => (await canvas.boundingBox())?.height ?? 0).toBeGreaterThan(100);
  await info.attach('design-preview-desktop', { body: await preview.screenshot(), contentType: 'image/png' });
});

for (const profile of [{ width: 1280, height: 860 }, { width: 390, height: 844 }]) {
  // contract-test: supporting surface=gui.web assertions=design-editor.view.validated-scene
  test(`reads and navigates a validated scene at ${profile.width}px`, async ({ page }, info) => {
    await page.setViewportSize(profile);
    await page.goto(path('Fullscreen', profile.width));
    await waitForComponentPreview(page);
    const canvas = page.getByTestId('design-canvas');
    await expect(canvas).toHaveAttribute('data-painted-page', 'explore');
    await expect(page.getByTestId('design-mode')).toHaveCount(0);
    const chooser = page.getByTestId('design-page-chooser');
    await chooser.click();
    const menu = page.getByLabel('Design pages');
    await expect(menu.getByRole('button')).toHaveText(['Explore', 'Saved', 'Profile']);
    await expect(menu.getByRole('button', { name: 'Explore' })).toHaveAttribute('aria-current', 'page');
    await info.attach(`design-pages-${profile.width}`, { body: await page.screenshot(), contentType: 'image/png' });
    await menu.getByRole('button', { name: 'Saved' }).click();
    await expect(canvas).toHaveAttribute('data-painted-page', 'saved');
    const initialScale = Number(await canvas.getAttribute('data-scale'));
    await page.getByTestId('design-zoom-in').click();
    await expect.poll(async () => Number(await canvas.getAttribute('data-scale'))).toBeGreaterThan(initialScale);
    await page.getByTestId('design-fit').click();
    await expect.poll(async () => Number(await canvas.getAttribute('data-scale'))).toBeCloseTo(initialScale, 3);
    await info.attach(`design-saved-${profile.width}`, { body: await page.screenshot(), contentType: 'image/png' });
  });
}

// contract-test: supporting surface=gui.web assertions=design-editor.view.validated-scene
test('shows a load error before rendering an unsupported version', async ({ page }, info) => {
  await page.goto(path('Fullscreen', 1280, 'unsupported'));
  await waitForComponentPreview(page);
  const error = page.getByTestId('embed-fullscreen-load-error');
  await expect(error).toBeVisible();
  await expect(page.getByTestId('design-canvas')).toHaveCount(0);
  await info.attach('design-unsupported-version', { body: await error.screenshot(), contentType: 'image/png' });
});

for (const profile of [{ width: 1280, height: 860 }, { width: 390, height: 844 }]) {
  // contract-test: supporting surface=gui.web assertions=design-editor.edit.typed-layers
  test(`edits typed layers and pages at ${profile.width}px`, async ({ page }, info) => {
    await page.setViewportSize(profile);
    await page.goto(`/dev/preview/embeds/design/editor/DesignEditorFullscreen?variant=saved-edit&chrome=0&width=${profile.width}`);
    await waitForComponentPreview(page);
    const editing = page.getByTestId('design-mode');
    const workspace = page.getByTestId('design-workspace');
    await editing.click();
    await expect(workspace).toHaveAttribute('data-mode', 'edit');
    if (profile.width === 390) await page.getByTestId('design-show-layers').click();
    await page.getByTestId('design-layer-headline').click();
    if (profile.width === 390) await page.getByTestId('design-show-properties').click();
    const copy = page.getByTestId('design-property-text');
    await copy.fill('Nightfall');
    await copy.press('Tab');
    await expect(copy).toHaveValue('Nightfall');
    const x = page.getByTestId('design-property-x');
    await x.fill('75');
    await x.press('Tab');
    await expect(x).toHaveValue('75');
    if (profile.width === 390) await page.getByTestId('design-close-properties').click();
    await info.attach(`design-edit-${profile.width}`, { body: await page.screenshot(), contentType: 'image/png' });
    await page.getByTestId('design-undo').click();
    await page.getByTestId('design-clipboard-toggle').click();
    await page.getByTestId('design-add-rectangle').click();
    const count = await workspace.getAttribute('data-layers');
    await page.getByTestId('design-clipboard-toggle').click();
    await page.getByTestId('design-delete-layer').click();
    await expect(workspace).toHaveAttribute('data-layers', String(Number(count) - 1));
    await page.getByTestId('design-page-chooser').click();
    await page.getByTestId('design-add-page').click();
    await expect(workspace).toHaveAttribute('data-layers', '0');
    await page.getByTestId('design-undo').click();
    await expect(workspace).toHaveAttribute('data-layers', String(Number(count) - 1));
    await editing.click();
    await expect(workspace).toHaveAttribute('data-mode', 'view');
  });
}

// contract-test: supporting surface=gui.web assertions=design-editor.assistant.apply
test('shows a proposal on a phone while protecting edit and apply controls', async ({ page }, info) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(path('Fullscreen', 390, 'proposal'));
  await waitForComponentPreview(page);
  await expect(page.getByTestId('design-canvas')).toHaveAttribute('data-painted-page', 'explore');
  const proposal = page.getByTestId('design-proposal-controls');
  await expect(proposal).toContainText('Proposed revision');
  await expect(proposal).toBeInViewport({ ratio: 1 });
  await expect(page.getByTestId('design-proposal-apply')).toHaveCount(0);
  await expect(page.getByTestId('design-mode')).toHaveCount(0);
  await info.attach('design-proposal-read-only-phone', { body: await page.screenshot(), contentType: 'image/png' });
});
