import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
const PREVIEW = '/dev/preview/embeds/music/MusicGenerateEmbedFullscreen?chrome=0&theme=light';

for (const width of [390, 1440]) {
  // contract-test: supporting surface=gui.web assertions=chats.layout.responsive-history
  test(`music fullscreen fills its pane without containment collapse at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(PREVIEW);
    await waitForComponentPreview(page);
    const content = page.getByTestId('music-generate-fullscreen');
    await expect(content).toBeVisible();
    await expect(content).toContainText('A 30 second ambient synth background loop');
    await expect(content.locator('.cover')).toHaveText('♪');

    const pane = await content.locator('..').boundingBox();
    const body = await content.boundingBox();
    expect(pane).not.toBeNull();
    expect(body).not.toBeNull();
    expect(body!.width).toBeGreaterThanOrEqual(Math.min(pane!.width, 980) - 1);
    expect(Math.abs(body!.x + body!.width / 2 - (pane!.x + pane!.width / 2))).toBeLessThan(1);

    for (const selector of ['.player-card', '.details-card']) {
      const card = await content.locator(selector).boundingBox();
      expect(card).not.toBeNull();
      expect(card!.x).toBeGreaterThanOrEqual(body!.x);
      expect(card!.x + card!.width).toBeLessThanOrEqual(body!.x + body!.width + 1);
    }

    const columns = await content.locator('.player-card').evaluate(
      (element) => getComputedStyle(element).gridTemplateColumns.split(' ').length
    );
    expect(columns).toBe(width < 640 ? 1 : 2);
    await page.screenshot({ path: test.info().outputPath(`music-fullscreen-${width}.png`) });
  });
}
