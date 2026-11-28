// playwright-account: not_required reason=isolated_component_preview
import { readFile } from 'node:fs/promises';
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

const cases = [
  ['code/CodeEmbedFullscreen', 'editableInProject'],
  ['sheets/SheetEmbedFullscreen', 'editableFormulas'],
  ['docs/DocsEmbedFullscreen', 'editableInChat'],
  ['images/ImageEmbedFullscreen', ''],
  ['events/EventEmbedFullscreen', ''],
  ['diagrams/MermaidDiagramEmbedFullscreen', ''],
  ['web/WebsiteEmbedFullscreen', ''],
  ['news/NewsEmbedFullscreen', ''],
  ['design/editor/DesignEditorFullscreen', 'saved-edit'],
] as const;

for (const width of [1280, 390]) {
  for (const [fixture, variant] of cases) {
    // contract-test: supporting surface=gui.web assertions=shared-embed-fullscreen.content,shared-embed-fullscreen.followup
    test(`${fixture} uses the shared content shell at ${width}px`, async ({ page }, info) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 860 });
      const query = new URLSearchParams({ chrome: '0', theme: 'light', width: String(width), variant });
      await page.goto(`/dev/preview/embeds/${fixture}?${query}`);
      await waitForComponentPreview(page);
      const shell = page.locator('[data-embed-shell="shared"]');
      await expect(shell).toHaveCount(1);
      await expect(shell).toHaveAttribute('data-header-kind', 'content');
      const bar = shell.getByTestId('embed-top-bar');
      await expect(bar.getByTestId('embed-compact-identity')).toBeInViewport({ ratio: 1 });
      await expect(bar.getByTestId('embed-header-title')).not.toBeEmpty();
      const more = bar.getByRole('button', { name: 'More', exact: true });
      await expect(more).toBeInViewport({ ratio: 1 });
      const close = bar.getByTestId('embed-minimize');
      await expect(close).toBeInViewport({ ratio: 1 });
      const dock = shell.getByTestId('embed-fixed-bottom');
      await expect(dock.getByTestId('embed-followup-composer')).toBeInViewport({ ratio: 1 });
      await more.click();
      await expect(bar.getByTestId('embed-report-issue-button')).toBeVisible();
      await page.keyboard.press('Escape');
      await expect(more).toHaveAttribute('aria-expanded', 'false');
      await expect(bar.getByTestId('embed-report-issue-button')).toHaveCount(0);
      await expect(bar.getByTestId('embed-compact-identity').locator('span[style]')).not.toHaveCSS('mask-image', 'none');
      await info.attach(`${fixture.split('/').at(-1)}-view-${width}`, {
        body: await page.screenshot({ animations: 'disabled' }), contentType: 'image/png',
      });

      const edit = bar.locator('[data-edit-state="edit"]');
      if (await edit.isVisible() && await edit.isEnabled()) {
        await edit.click();
        await expect(bar.getByTestId('embed-compact-identity')).toBeInViewport({ ratio: 1 });
        await expect(close).toBeInViewport({ ratio: 1 });
        await expect(dock.getByTestId('embed-followup-composer')).toBeInViewport({ ratio: 1 });
        await info.attach(`${fixture.split('/').at(-1)}-edit-${width}`, {
          body: await page.screenshot({ animations: 'disabled' }), contentType: 'image/png',
        });
      }
    });
  }
}

// contract-test: supporting surface=gui.web assertions=shared-embed-fullscreen.content
test('the news execution retains its large header and uses the shared composer', async ({ page }) => {
  await page.goto('/dev/preview/embeds/news/NewsSearchEmbedFullscreen?chrome=0&theme=light&width=390');
  await waitForComponentPreview(page);
  const shell = page.locator('[data-embed-shell="shared"]').first();
  await expect(shell).toHaveAttribute('data-header-kind', 'execution');
  await expect(shell.getByTestId('embed-compact-identity')).toHaveCount(0);
  await expect(shell.getByTestId('embed-followup-composer')).toBeVisible();
});

// contract-test: supporting surface=gui.web assertions=shared-embed-fullscreen.content
test('a website opened from search uses the compact shell and keeps its image', async ({ page }, info) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const title = 'The city market';
  const query = new URLSearchParams({ chrome: '0', theme: 'light', width: '390', props: JSON.stringify({
    results: [{ title, url: 'https://example.com/market', description: 'An indoor market.', image: '/store-examples/events-1.webp' }],
  }) });
  await page.goto(`/dev/preview/embeds/web/WebSearchEmbedFullscreen?${query}`);
  await waitForComponentPreview(page);
  const parent = page.locator('[data-embed-shell="shared"][data-header-kind="execution"]');
  await expect(parent).toBeVisible();
  await parent.getByText(title, { exact: true }).click();
  const child = page.locator('[data-embed-shell="shared"][data-header-kind="content"]');
  await expect(child.getByTestId('embed-compact-identity').getByTestId('embed-header-title')).toHaveText(title);
  const image = child.getByRole('img').first();
  await expect(image).toBeVisible();
  await expect(image).toHaveAttribute('src', /events-1\.webp/);
  await expect(child.getByTestId('embed-followup-composer')).toBeInViewport({ ratio: 1 });
  await info.attach('website-child-phone', { body: await page.screenshot({ animations: 'disabled' }), contentType: 'image/png' });
  await child.getByTestId('embed-minimize').click();
  await expect(child).toHaveCount(0);
  await expect(parent).toBeVisible();
});

for (const profile of [{ width: 1280, height: 860 }, { width: 390, height: 844 }]) {
  // contract-test: supporting surface=gui.web assertions=design-editor.export.artboard,design-editor.export.pdf
  test(`shows local export controls at ${profile.width}px`, async ({ page }, info) => {
    await page.setViewportSize(profile);
    await page.goto(path('Fullscreen', profile.width));
    await waitForComponentPreview(page);
    await expect(page.getByTestId('design-canvas')).toHaveAttribute('data-painted-page', 'explore');
    const toggle = page.getByTestId('design-export-toggle');
    await toggle.click();
    const menu = page.getByTestId('design-export-menu');
    await expect(menu).toBeInViewport({ ratio: 1 });
    await expect(menu.getByRole('button')).toHaveText(['SVG Current page', 'PNG Current page', 'PDF All pages']);
    await info.attach(`design-export-${profile.width}`, {
      body: await page.screenshot({ animations: 'disabled' }), contentType: 'image/png',
    });
    await page.keyboard.press('Escape');
    await expect(menu).toHaveCount(0);
    await toggle.click();
    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.getByTestId('design-export-svg').click(),
    ]);
    const xml = await readFile((await download.path())!, 'utf8');
    expect(xml).toContain('viewBox="0 0 390 700"');
    expect(xml).toContain('<path ');
    expect(xml).toContain('Find a trail');
    await expect(menu).toHaveCount(0);
  });
}


// contract-test: supporting surface=gui.web assertions=design-editor.export.local
test('explains when a required local image prevents export', async ({ page }) => {
  await page.goto(path('Fullscreen', 390, 'missing-image-export'));
  await waitForComponentPreview(page);
  await expect(page.getByTestId('design-canvas')).toHaveAttribute('data-missing-assets', 'true');
  await page.getByTestId('design-export-toggle').click();
  await page.getByTestId('design-export-png').click();
  await expect(page.getByTestId('design-export-error')).toContainText('An image is unavailable on this device.');
});
