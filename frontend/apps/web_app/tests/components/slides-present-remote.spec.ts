// playwright-account: not_required reason=isolated_component_preview
// proof-video: not_required reason=visual_smoke_not_needed
import { test, expect, type Page, type TestInfo } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

const preview = (variant = '') =>
  `/dev/preview/embeds/slides/SlidesPresentRemote?${new URLSearchParams({ variant, chrome: '0' })}`;

async function open(page: Page, variant = '') {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(preview(variant));
  await waitForComponentPreview(page);
}

const calls = (page: Page) =>
  page.evaluate(() => (window as unknown as { __slidesRemoteCalls?: string[] }).__slidesRemoteCalls ?? []);

async function shot(page: Page, testInfo: TestInfo, name: string) {
  await testInfo.attach(name, { body: await page.screenshot(), contentType: 'image/png' });
}

test.describe('Slides presentation remote (component)', () => {
  // contract-test: direct surface=gui.web assertions=slides.present.remote-control
  test('shows the position as n / total', async ({ page }, testInfo) => {
    await open(page);
    await expect(page.getByTestId('slides-remote-position')).toHaveText('1 / 4');
    await shot(page, testInfo, 'remote-first-slide');
    await open(page, 'second');
    await expect(page.getByTestId('slides-remote-position')).toHaveText('2 / 4');
  });

  // contract-test: direct surface=gui.web assertions=slides.present.remote-control
  test('Next and Previous call back with large touch targets', async ({ page }) => {
    await open(page);
    await page.getByTestId('slides-remote-next').click();
    await page.getByTestId('slides-remote-prev').click();
    expect(await calls(page)).toEqual(['next', 'previous']);
    const box = await page.getByTestId('slides-remote-next').boundingBox();
    expect(box!.height).toBeGreaterThanOrEqual(56);
  });

  // contract-test: direct surface=gui.web assertions=slides.present.remote-control
  test('tapping a slide in the list jumps to it', async ({ page }) => {
    await open(page);
    await page.getByTestId('slides-remote-slide-3').click();
    expect(await calls(page)).toEqual(['goto:2']);
  });

  // contract-test: direct surface=gui.web assertions=slides.present.remote-control
  test('notes are hidden by default and show the current slide notes on demand', async ({ page }, testInfo) => {
    await open(page, 'second');
    await expect(page.getByTestId('slides-remote-notes')).toHaveCount(0);
    await page.getByTestId('slides-remote-notes-toggle').click();
    await expect(page.getByTestId('slides-remote-notes')).toHaveText('Stress the eighteen percent.');
    await shot(page, testInfo, 'remote-notes-shown');
    await page.getByTestId('slides-remote-notes-toggle').click();
    await expect(page.getByTestId('slides-remote-notes')).toHaveCount(0);
  });

  // contract-test: direct surface=gui.web assertions=slides.present.remote-control
  test('shows the not-presenting state and disables moves', async ({ page }, testInfo) => {
    await open(page, 'notPresenting');
    await expect(page.getByTestId('slides-remote-not-presenting')).toBeVisible();
    await expect(page.getByTestId('slides-remote-next')).toBeDisabled();
    await shot(page, testInfo, 'remote-not-presenting');
  });
});
