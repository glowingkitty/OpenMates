// playwright-account: not_required reason=isolated_component_preview
// proof-video: not_required reason=visual_smoke_not_needed
import { test, expect, type Page, type TestInfo } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

async function open(page: Page, variant = '') {
  await page.goto(`/dev/preview/embeds/slides/SlideImageElement?${new URLSearchParams({ variant, chrome: '0' })}`);
  await waitForComponentPreview(page);
}

async function shot(page: Page, testInfo: TestInfo, name: string) {
  await testInfo.attach(name, { body: await page.screenshot(), contentType: 'image/png' });
}

test.describe('Slides animated SVG image (component)', () => {
  // contract-test: direct surface=gui.web assertions=slides.media.svg-declarative-animation
  test('motion mode renders the animated SVG through an img', async ({ page }, testInfo) => {
    await open(page);
    const img = page.getByTestId('slide-image-animated');
    await expect(img).toHaveCount(1);
    expect(await img.evaluate((el) => el.tagName)).toBe('IMG');
    expect(await img.getAttribute('src')).toMatch(/^data:image\/svg\+xml/);
    await expect.poll(() => img.evaluate((el) => (el as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
    await shot(page, testInfo, 'animated-svg');
  });

  // contract-test: direct surface=gui.web assertions=slides.media.svg-declarative-animation
  test('reduced motion shows the still picture', async ({ page }, testInfo) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await open(page);
    const img = page.getByTestId('slide-image-animated');
    await expect.poll(() => img.evaluate((el) => (el as HTMLImageElement).currentSrc)).toMatch(/^data:image\/png/);
    await shot(page, testInfo, 'reduced-motion-still');
  });

  // contract-test: direct surface=gui.web assertions=slides.media.svg-declarative-animation
  test('still-only mode and raster images show no animated img', async ({ page }) => {
    await open(page, 'stillOnly');
    await expect(page.getByTestId('slide-image-animated')).toHaveCount(0);
    await expect(page.locator('img.slide-image')).toHaveAttribute('src', /^data:image\/png/);
    await open(page, 'rasterOnly');
    await expect(page.getByTestId('slide-image-animated')).toHaveCount(0);
  });
});
