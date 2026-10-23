import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
// playwright-account: not_required reason=isolated_component_preview

const components = ['ImageResultEmbedPreview', 'ImageEmbedPreview', 'ImageGenerateEmbedPreview'];

for (const theme of ['light', 'dark']) {
  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction,chats.layout.responsive-history
  test(`image-only previews preserve the complete media in ${theme}`, async ({ page }) => {
    test.setTimeout(180_000);
    await page.setViewportSize({ width: 1120, height: 900 });
    const response = await page.request.get('/images/examples/group1.jpg');
    expect(response.ok()).toBe(true);
    const bytes = await response.body();
    await page.route('**/api/v1/image?*', route => route.fulfill({ contentType: 'image/jpeg', body: bytes }));
    for (const component of components) for (const mode of ['compact', 'mobile', 'chat']) {
      await test.step(`${component}: ${mode}`, async () => {
        const params = new URLSearchParams({ chrome: '0', theme, background: '#dbeafe', width: mode === 'chat' ? '1000' : '390' });
        if (mode === 'chat') params.set('context', 'chat');
        if (mode === 'mobile') params.set('props', JSON.stringify({ isMobile: true }));
        await page.goto(`/dev/preview/embeds/images/${component}?${params}`);
        await waitForComponentPreview(page);
        const card = page.getByTestId('embed-preview');
        const media = card.getByTestId('result-card-media');
        const image = media.locator('img').first();
        await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.complete && element.naturalWidth > 0)).toBe(true);
        await expect(image).toBeVisible();
        await expect(image).toHaveCSS('object-fit', 'contain');
        await expect(image).toHaveAttribute('alt', /\S/);
        await expect(card.getByTestId('result-card-title')).toHaveCount(0);
        await expect(card.getByTestId('embed-basic-infos-bar')).toHaveCount(0);
        const shell = (await card.boundingBox())!;
        expect(shell.width).toBeCloseTo(mode === 'chat' ? 1000 : mode === 'mobile' ? 150 : 300, 0);
        expect(shell.height).toBeCloseTo(mode === 'chat' ? 400 : mode === 'mobile' ? 290 : 200, 0);
        for (const element of [media, image]) {
          const box = (await element.boundingBox())!;
          expect(box.x).toBeCloseTo(shell.x, 0);
          expect(box.y).toBeCloseTo(shell.y, 0);
          expect(box.width).toBeCloseTo(shell.width, 0);
          expect(box.height).toBeCloseTo(shell.height, 0);
        }
        expect(await media.evaluate(element => getComputedStyle(element, '::after').display)).toBe('none');
        // Real source ratios differ from the fixed shell; contain must leave
        // room on the shorter axis, rather than crop or stretch the image.
        const ratio = await image.evaluate((element: HTMLImageElement) => element.naturalWidth / element.naturalHeight);
        expect(Math.abs(ratio - shell.width / shell.height)).toBeGreaterThan(0.01);
        if (mode === 'chat') {
          await card.hover();
          await expect(card).toHaveCSS('transform', 'none');
          const expand = card.getByTestId('result-preview-expand');
          await expect(expand).toBeVisible();
          await expand.focus();
          await expect(expand).toBeFocused();
          await expect(card.getByTestId('result-preview-more')).toBeVisible();
        }
      });
    }
  });
}
