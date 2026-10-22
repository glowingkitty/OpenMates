import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentMotion, waitForComponentPreview } from '../helpers/component-preview';
// playwright-account: not_required reason=isolated_component_preview

const preview = (path: string, width: number, variant = '', theme = 'light') =>
  `/dev/preview/embeds/${path}?chrome=0&width=${width}&theme=${theme}${variant ? `&variant=${variant}` : ''}${variant === 'chat' ? '&context=chat' : ''}`;

for (const width of [390, 1280]) {
  // contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence,chats.rendering.inline-entity-interaction
  test(`website and news shared responsive cards at ${width}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.route('**/api/v1/metadata?**', route => route.fulfill({ json: {} }));
    for (const path of ['web/WebsiteEmbedPreview', 'news/NewsEmbedPreview']) {
      let expanded = 0;
      const listener = (message: { text(): string }) => { if (message.text() === '[Preview] result expanded') expanded++; };
      page.on('console', listener);
      await page.goto(preview(path, width, 'chat'));
      await waitForComponentPreview(page);
      const card = page.getByTestId('embed-preview');
      const title = page.getByTestId('result-card-title');
      await expect(card).toHaveAttribute('role', 'group');
      await expect(title).toBeVisible();
      await expect(title).toHaveCSS('user-select', 'text');
      await title.click();
      expect(expanded).toBe(0);
      await card.getByTestId('result-preview-expand').focus();
      await page.keyboard.press('Enter');
      await expect.poll(() => expanded).toBe(1);
      await expect(card.locator('.result-corner')).toBeVisible();
      if (path.startsWith('news/')) await expect(page.getByTestId('news-publication-date').locator('time')).toHaveAttribute('datetime', '2026-10-21T00:00:00.000Z');
      await testInfo.attach(`${path.split('/')[0]}-chat-${width}`, { body: await page.screenshot(), contentType: 'image/png' });
      await page.goto(preview(path, width, 'results'));
      await waitForComponentPreview(page);
      await expect(card).toHaveAttribute('role', 'button');
      await page.getByTestId('result-card-title').click();
      await expect.poll(() => expanded).toBe(2);
      await page.goto(preview(path, width, 'noImage', 'dark'));
      await waitForComponentPreview(page);
      await expect(page.getByTestId('result-card-title')).toBeVisible();
      await expect(page.getByTestId('result-card-media')).toHaveCount(0);
      await expect(page.getByTestId('result-card-content')).toContainText('A concise source description');
      const fallback = await page.getByTestId('result-card-content').evaluate(element => {
        const card = element.getBoundingClientRect();
        const source = element.querySelector('.card-source')!.getBoundingClientRect();
        const description = element.querySelector('p')!.getBoundingClientRect();
        return { sourceOffset: source.top - card.top, descriptionBottom: description.bottom, cardBottom: card.bottom };
      });
      expect(fallback.sourceOffset).toBeLessThanOrEqual(64);
      expect(fallback.descriptionBottom).toBeLessThanOrEqual(fallback.cardBottom + 1);
      const box = (await card.boundingBox())!;
      expect(box.x + box.width).toBeLessThanOrEqual(width + 1);
      page.off('console', listener);
    }
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence,chats.rendering.inline-entity-interaction
  test(`website and news fullscreens retain provider, quotes and followup at ${width}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    for (const path of ['web/WebsiteEmbedFullscreen', 'news/NewsEmbedFullscreen']) {
      await page.goto(preview(path, width, 'withSnippets'));
      await waitForComponentPreview(page);
      await expect(page.getByTestId('result-embed-content')).toBeVisible();
      await waitForComponentMotion(page.getByTestId('embed-fullscreen-overlay'));
      await expect(page.getByTestId('external-provider-cta')).toBeVisible();
      await expect(page.getByTestId('apps-request-textarea')).toBeVisible();
      await expect(page.locator('.header-image')).toHaveCSS('object-fit', 'contain');
      await expect.poll(() => page.locator('.header-image').evaluate(element => { const image = element as HTMLImageElement; return image.complete && image.naturalWidth > 0; })).toBe(true);
      await expect(page.locator('.ds-snippet-card')).toHaveCount(2);
      await expect(page.getByTestId('result-facts')).toHaveCount(0);
      const hostname = path.startsWith('news/') ? 'techcrunch.com' : 'github.com';
      await expect(page.getByText(hostname, { exact: true })).toHaveCount(0);
      await expect(page.getByText(`Open on ${hostname}`, { exact: true })).toHaveCount(1);
      if (path.startsWith('news/')) {
        await expect(page.getByTestId('embed-header-subtitle')).toContainText('2025/11/15');
        await expect(page.getByText('Data from 2025/11/15', { exact: true })).toHaveCount(1);
      }
      if (width > 600) {
        const image = (await page.locator('.header-image').boundingBox())!;
        const description = (await page.locator('.description').boundingBox())!;
        const composer = (await page.getByTestId('apps-request-textarea').boundingBox())!;
        expect(image.height).toBeLessThanOrEqual(320);
        expect(description.y).toBeGreaterThanOrEqual(image.y + image.height - 1);
        expect(description.y + description.height).toBeLessThanOrEqual(Math.min(900, composer.y));
      }
      await testInfo.attach(`${path.split('/')[0]}-fullscreen-${width}`, { body: await page.screenshot(), contentType: 'image/png' });
    }
    await page.goto(preview('web/WebsiteEmbedFullscreen', width, 'withHighlightedQuote'));
    await waitForComponentPreview(page);
    await expect(page.getByTestId('embed-source-text-highlight').first()).toBeVisible();
  });
}

// contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence,chats.rendering.inline-entity-interaction
test('broken result media falls back to bounded title and description', async ({ page }, testInfo) => {
  await page.route('**/missing-result-preview-image.webp', route => route.fulfill({ status: 404, body: '' }));
  await page.goto(preview('web/WebsiteEmbedPreview', 390, 'brokenImage'));
  await waitForComponentPreview(page);
  await expect(page.getByTestId('result-card-media')).toHaveCount(0);
  await expect(page.getByTestId('result-card-title')).toBeVisible();
  await expect(page.getByTestId('result-card-content').locator('p')).toBeVisible();
  await page.route('**/api/v1/metadata?**', route => route.fulfill({ json: {} }));
  await page.route('**/missing-result-header-favicon.png', route => route.fulfill({ status: 404, body: '' }));
  const props = encodeURIComponent(JSON.stringify({
    data: { decodedContent: { url: 'https://example.com/header-favicon-test', title: 'Readable source title', description: 'The source remains readable when its icon is unavailable.', favicon: '/missing-result-header-favicon.png' }, embedData: { status: 'finished' }, attrs: { app_id: 'web', skill_id: 'website' } },
  }));
  await page.goto(`${preview('web/WebsiteEmbedFullscreen', 390)}&props=${props}`);
  await waitForComponentPreview(page);
  await expect(page.getByTestId('embed-header-title')).toHaveText('Readable source title');
  await expect(page.locator('.header-favicon')).toBeHidden();
  await testInfo.attach('web-broken-favicon-fallback', { body: await page.screenshot(), contentType: 'image/png' });
});


// contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence,chats.rendering.inline-entity-interaction
test('uncropped shared card media and natural-sized source/title/facts do not overlap', async ({ page }) => {
  for (const width of [390, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    const props = encodeURIComponent(JSON.stringify({
      previewImageUrl: '/store-examples/events-1.webp',
      title: 'An exceptionally detailed research observatory for community science education',
    }));
    await page.goto(`${preview('models3d/Model3DResultEmbedPreview', width)}&context=chat&props=${props}`);
    await waitForComponentPreview(page);
    const card = page.getByTestId('result-card-content');
    const media = card.getByTestId('result-card-media');
    await expect(media.locator('img')).toHaveCSS('object-fit', 'contain');
    await expect(card.locator('.card-facts button')).toHaveCount(3);
    const bounds = await card.evaluate(element => {
      const rect = (selector: string) => {
        const box = element.querySelector(selector)!.getBoundingClientRect();
        return { x: box.x, y: box.y, right: box.right, bottom: box.bottom, height: box.height };
      };
      return { card: element.getBoundingClientRect().toJSON(), media: rect('.card-media'), copy: rect('.card-copy'), title: rect('h3'), source: rect('.card-source'), facts: rect('.card-facts') };
    });
    expect(bounds.media.height).toBeGreaterThan(0);
    for (const region of [bounds.source, bounds.title, bounds.facts]) {
      expect(region.y).toBeGreaterThanOrEqual(bounds.copy.y - 1);
      expect(region.bottom).toBeLessThanOrEqual(bounds.copy.bottom + 1);
      expect(region.bottom).toBeLessThanOrEqual(bounds.card.bottom + 1);
    }
    if (bounds.card.width < 400) expect(bounds.media.bottom).toBeLessThanOrEqual(bounds.copy.y + 1);
    else expect(bounds.copy.right).toBeLessThanOrEqual(bounds.media.x + 1);
  }
});
