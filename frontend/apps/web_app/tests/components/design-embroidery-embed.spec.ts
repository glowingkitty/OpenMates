import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
// proof-video: not_required reason=isolated_component_preview

/*
 * design.embroidery result embed: card (preview) and opened view (fullscreen).
 *
 * Runs against the isolated component profile: every fixture carries inline
 * media (previewImageUrl / preparedSvgText), so nothing needs S3 or a backend.
 * Downloads use the inline `previewDownloadText` of the fixture (the real app
 * fetches and decrypts the encrypted file from storage); the follow-up
 * interpretation request is intercepted and asserted, never answered by a real service.
 */

const PREVIEW = '/dev/preview/embeds/design/DesignEmbroideryEmbedPreview?chrome=0';
const FULLSCREEN = '/dev/preview/embeds/design/DesignEmbroideryEmbedFullscreen?chrome=0';
const FORMATS = ['dst', 'pes', 'exp', 'jef', 'vp3'] as const;
const WIDTHS = [360, 1000];

// contract-test: supporting surface=gui.web assertions=design-embroidery.result.view-and-download
for (const width of WIDTHS) {
  test(`card shows the stitch preview uncropped with size, stitch count and thread swatches at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 800 });
    await page.goto(`${PREVIEW}&variant=finished`);
    await waitForComponentPreview(page);
    const card = page.getByTestId('design-embroidery-preview');
    await expect(card).toBeVisible();
    const image = page.getByTestId('design-embroidery-preview-image');
    await expect(image).toBeVisible();
    await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.naturalWidth)).toBeGreaterThan(0);
    await expect(image).toHaveCSS('object-fit', 'contain');
    const bounds = await image.evaluate((element) => {
      const media = element.parentElement!.getBoundingClientRect();
      const box = element.getBoundingClientRect();
      return { insideWidth: box.width <= media.width + 1, insideHeight: box.height <= media.height + 1 };
    });
    expect(bounds).toEqual({ insideWidth: true, insideHeight: true });
    const numbers = page.getByTestId('design-embroidery-numbers');
    await expect(numbers).toHaveText('90 × 74 mm · 12,840 stitches');
    const truncated = await numbers.evaluate((element) => element.scrollWidth > element.clientWidth);
    expect(truncated).toBe(false);
    const cardBox = await page.getByTestId('result-card-content').boundingBox();
    const imageBox = await image.boundingBox();
    expect(cardBox && imageBox).toBeTruthy();
    expect(imageBox!.x).toBeGreaterThanOrEqual(cardBox!.x - 0.5);
    expect(imageBox!.y).toBeGreaterThanOrEqual(cardBox!.y - 0.5);
    expect(imageBox!.x + imageBox!.width).toBeLessThanOrEqual(cardBox!.x + cardBox!.width + 0.5);
    expect(imageBox!.y + imageBox!.height).toBeLessThanOrEqual(cardBox!.y + cardBox!.height + 0.5);
    const swatches = page.getByTestId('design-embroidery-swatch');
    await expect(swatches).toHaveCount(3);
    await expect(swatches.first()).toHaveCSS('background-color', 'rgb(232, 116, 44)');
    await expect(swatches.nth(1)).toHaveCSS('border-top-width', '1px');
    await expect(page.getByTestId('design-embroidery-download-pes')).toHaveCount(0);
    await testInfo.attach(`embroidery-card-${width}`, { body: await page.screenshot(), contentType: 'image/png' });
  });

  // contract-test: supporting surface=gui.web assertions=design-embroidery.result.view-and-download
  test(`card shows a converting state while the conversion runs at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 });
    await page.goto(`${PREVIEW}&variant=processing`);
    await waitForComponentPreview(page);
    await expect(page.getByTestId('design-embroidery-preview')).toHaveAttribute('data-status', 'processing');
    await expect(page.getByTestId('embed-preview')).toContainText('Converting to stitches');
    await expect(page.getByTestId('design-embroidery-preview-image')).toHaveCount(0);
  });

  // contract-test: supporting surface=gui.web assertions=design-embroidery.result.view-and-download
  test(`failed card states the reason in plain words and offers no downloads at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 });
    await page.goto(`${PREVIEW}&variant=error`);
    await waitForComponentPreview(page);
    await expect(page.getByTestId('design-embroidery-preview')).toHaveAttribute('data-status', 'error');
    await expect(page.getByTestId('embed-preview')).toContainText('The design has too many stitches');
    await expect(page.getByTestId('design-embroidery-preview-image')).toHaveCount(0);
    await expect(page.locator('[data-testid^="design-embroidery-download-"]')).toHaveCount(0);
  });

  // contract-test: supporting surface=gui.web assertions=design-embroidery.result.view-and-download
  test(`opened view shows preview switch, threads, numbers, notes and five downloads at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(`${FULLSCREEN}&variant=finished`);
    await waitForComponentPreview(page);
    const view = page.getByTestId('design-embroidery-fullscreen');
    await expect(view).toBeVisible();

    const image = page.getByTestId('design-embroidery-image');
    await expect(image).toHaveAttribute('data-view', 'stitches');
    await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.naturalWidth)).toBeGreaterThan(0);
    await expect(image).toHaveCSS('object-fit', 'contain');
    const stitchSrc = await image.getAttribute('src');
    await page.getByTestId('design-embroidery-view-graphic').click();
    await expect(image).toHaveAttribute('data-view', 'graphic');
    await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.naturalWidth)).toBeGreaterThan(0);
    expect(await image.getAttribute('src')).not.toBe(stitchSrc);
    await page.getByTestId('design-embroidery-view-stitches').click();
    await expect(image).toHaveAttribute('src', stitchSrc!);

    await expect(page.getByTestId('design-embroidery-size')).toContainText('90 × 74 mm');
    await expect(page.getByTestId('design-embroidery-stitch-count')).toContainText('12,840');
    await expect(page.getByTestId('design-embroidery-thread-changes')).toContainText('3');
    await expect(page.getByTestId('design-embroidery-time')).toContainText('47 min');
    const hoopFit = page.getByTestId('design-embroidery-hoop-fit');
    await expect(hoopFit).toContainText('Fits hoop 130 × 180 mm');
    const hoopText = await hoopFit.locator('.fact-text').boundingBox();
    const hoopIndicator = await hoopFit.locator('.state').boundingBox();
    expect(hoopText && hoopIndicator).toBeTruthy();
    const overlaps = hoopIndicator!.x < hoopText!.x + hoopText!.width && hoopText!.x < hoopIndicator!.x + hoopIndicator!.width
      && hoopIndicator!.y < hoopText!.y + hoopText!.height && hoopText!.y < hoopIndicator!.y + hoopIndicator!.height;
    expect(overlaps).toBe(false);
    await expect(page.getByTestId('design-embroidery-fabric-info')).toContainText('Normal');

    const threads = page.getByTestId('design-embroidery-thread');
    await expect(threads).toHaveCount(3);
    await expect(threads.first()).toContainText('1');
    await expect(threads.first()).toContainText('Madeira 1135');
    await expect(threads.first()).toContainText('8,120 stitches');
    await expect(threads.nth(1)).toContainText('Madeira 1001');
    await expect(threads.nth(2)).toContainText('Madeira 1005');

    await expect(page.getByTestId('design-embroidery-notes')).toContainText('Background left out');
    await expect(page.getByTestId('design-embroidery-reworked')).toHaveCount(0);
    for (const format of FORMATS) {
      const button = page.getByTestId(`design-embroidery-download-${format}`);
      await button.scrollIntoViewIfNeeded();
      await expect(button).toBeVisible();
      await expect(button).toHaveText(format.toUpperCase());
    }
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(0);
    await testInfo.attach(`embroidery-opened-${width}`, { body: await page.screenshot(), contentType: 'image/png' });
  });
}

// contract-test: supporting surface=gui.web assertions=design-embroidery.result.view-and-download
test('opened view translates known notes, falls back to the server text and hints at a rework', async ({ page }) => {
  await page.goto(`${FULLSCREEN}&variant=reworked`);
  await waitForComponentPreview(page);
  const notes = page.getByTestId('design-embroidery-note');
  await expect(notes).toHaveCount(4);
  await expect(notes.first()).toHaveText('Background left out');
  await expect(notes.nth(1)).toHaveText('Details too small to sew were left out (3)');
  await expect(notes.nth(2)).toHaveText('Gradients and filters were replaced by flat colours');
  await expect(notes.nth(3)).toHaveText('The tail was drawn a little wider');
  await expect(page.getByTestId('design-embroidery-reworked')).toBeVisible();
  await expect(page.getByTestId('design-embroidery-fabric-info')).toContainText('Stretchy');
});

// contract-test: supporting surface=gui.web assertions=design-embroidery.result.view-and-download
test('opened view states when the design is too large for the hoop and omits the line when not checked', async ({ page }) => {
  await page.goto(`${FULLSCREEN}&variant=hoopTooSmall`);
  await waitForComponentPreview(page);
  const fit = page.getByTestId('design-embroidery-hoop-fit');
  await expect(fit).toContainText('Too large for hoop 100 × 100 mm');
  await expect(fit).toHaveAttribute('data-state', 'no');
  await page.goto(`${FULLSCREEN}&variant=hoopNotChecked`);
  await waitForComponentPreview(page);
  await expect(page.getByTestId('design-embroidery-size')).toBeVisible();
  await expect(page.getByTestId('design-embroidery-hoop-fit')).toHaveCount(0);
});

// contract-test: supporting surface=gui.web assertions=design-embroidery.result.view-and-download
for (const width of [390, 1280]) {
  test(`opened view offers an obvious download: top-bar button and a main button above the threads at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(`${FULLSCREEN}&variant=finished`);
    await waitForComponentPreview(page);

    const topBar = page.getByTestId('embed-download-button');
    // A narrow top bar lists its actions under More, like every other result.
    if (width < 600) await page.getByRole('button', { name: 'More', exact: true }).click();
    await expect(topBar).toBeVisible();
    const topDownload = page.waitForEvent('download');
    await topBar.click();
    expect((await topDownload).suggestedFilename()).toMatch(/\.zip$/);

    const main = page.getByTestId('design-embroidery-download-all');
    await main.scrollIntoViewIfNeeded();
    await expect(main).toBeVisible();
    await expect(main).toContainText('Download all formats (ZIP)');
    const mainBox = await main.boundingBox();
    const firstThread = await page.getByTestId('design-embroidery-thread').first().boundingBox();
    const preview = await page.getByTestId('design-embroidery-image').boundingBox();
    expect(mainBox && firstThread && preview).toBeTruthy();
    expect(mainBox!.y).toBeGreaterThan(preview!.y + preview!.height - 1);
    expect(mainBox!.y + mainBox!.height).toBeLessThanOrEqual(firstThread!.y);
    expect(mainBox!.height).toBeGreaterThanOrEqual(44);
    await testInfo.attach(`embroidery-download-cta-${width}`, { body: await page.screenshot(), contentType: 'image/png' });

    const mainDownload = page.waitForEvent('download');
    await main.click();
    expect((await mainDownload).suggestedFilename()).toMatch(/\.zip$/);
    await expect(main).toHaveAttribute('data-state', 'idle');
  });
}

// contract-test: supporting surface=gui.web assertions=design-embroidery.result.view-and-download
test('a failing download of all formats shows an error on the main button and saves nothing', async ({ page }) => {
  await page.goto(`${FULLSCREEN}&variant=downloadUnavailable`);
  await waitForComponentPreview(page);
  const main = page.getByTestId('design-embroidery-download-all');
  await main.click();
  await expect(main).toHaveAttribute('data-state', 'error');
  await expect(page.getByTestId('design-embroidery-download-all-error')).toBeVisible();
});

// contract-test: supporting surface=gui.web assertions=design-embroidery.result.view-and-download
test('a format download saves the decrypted file under a name with its extension', async ({ page }) => {
  await page.goto(`${FULLSCREEN}&variant=finished`);
  await waitForComponentPreview(page);
  const download = page.waitForEvent('download');
  await page.getByTestId('design-embroidery-download-pes').click();
  expect((await download).suggestedFilename()).toMatch(/\.pes$/);
  await expect(page.getByTestId('design-embroidery-download-pes')).toHaveAttribute('data-state', 'idle');
});

// contract-test: supporting surface=gui.web assertions=design-embroidery.result.view-and-download
test('a failing download shows an error on that button only and can be retried', async ({ page }) => {
  await page.goto(`${FULLSCREEN}&variant=downloadUnavailable`);
  await waitForComponentPreview(page);
  const button = page.getByTestId('design-embroidery-download-dst');
  await button.click();
  await expect(button).toHaveAttribute('data-state', 'error');
  await expect(page.getByTestId('design-embroidery-download-dst-error')).toBeVisible();
  await expect(page.getByTestId('design-embroidery-download-pes')).toHaveAttribute('data-state', 'idle');
  await expect(page.getByTestId('design-embroidery-download-pes-error')).toHaveCount(0);
  await expect(button).toBeEnabled();
  await button.click();
  await expect(button).toHaveAttribute('data-state', 'error');
});

// contract-test: supporting surface=gui.web assertions=design-embroidery.result.view-and-download
test('applying new settings sends an ordinary follow-up asking for a new conversion', async ({ page }, testInfo) => {
  await page.route('**/v1/apps/workspace/interpret', route => route.fulfill({ status: 503, json: { detail: 'isolated component request' } }));
  await page.goto(`${FULLSCREEN}&variant=finished`);
  await waitForComponentPreview(page);
  const width = page.getByTestId('design-embroidery-width');
  await width.scrollIntoViewIfNeeded();
  await expect(width).toHaveValue('90');
  await expect(page.getByTestId('design-embroidery-hoop')).toHaveValue('130x180');
  await expect(page.getByTestId('design-embroidery-fabric')).toHaveValue('normal');
  await width.fill('60');
  await page.getByTestId('design-embroidery-fabric').selectOption('stretchy');
  const pending = page.waitForRequest('**/v1/apps/workspace/interpret');
  await page.getByTestId('design-embroidery-apply').click();
  const request = (await pending).postDataJSON();
  expect(request.text).toBe('Convert this embroidery design again: width 60 mm, hoop 130 × 180 mm, fabric stretchy.');
  const serialized = JSON.stringify(request.context ?? {});
  for (const secret of ['aes_key', 'aes_nonce', 's3_base_url', 's3_key']) expect(serialized).not.toContain(secret);
  await testInfo.attach('embroidery-settings-applied', { body: await page.screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=design-embroidery.result.view-and-download
test('a width outside 20 to 400 mm cannot be applied', async ({ page }) => {
  await page.goto(`${FULLSCREEN}&variant=finished`);
  await waitForComponentPreview(page);
  const width = page.getByTestId('design-embroidery-width');
  await width.scrollIntoViewIfNeeded();
  await width.fill('500');
  await expect(page.getByTestId('design-embroidery-apply')).toBeDisabled();
  await width.fill('20');
  await expect(page.getByTestId('design-embroidery-apply')).toBeEnabled();
});

// contract-test: supporting surface=gui.web assertions=design-embroidery.result.view-and-download
for (const variant of ['error', 'nothingToSew']) {
  test(`opened failed result (${variant}) shows the reason with no downloads and no settings`, async ({ page }, testInfo) => {
    await page.goto(`${FULLSCREEN}&variant=${variant}`);
    await waitForComponentPreview(page);
    const reason = page.getByTestId('design-embroidery-error');
    await expect(reason).toBeVisible();
    await expect(reason).toContainText(variant === 'error'
      ? 'The design has too many stitches'
      : 'There is nothing to sew after leaving out the background');
    await expect(page.locator('[data-testid^="design-embroidery-download-"]')).toHaveCount(0);
    await expect(page.getByTestId('embed-download-button')).toHaveCount(0);
    await expect(page.getByTestId('design-embroidery-settings')).toHaveCount(0);
    await expect(page.getByTestId('design-embroidery-thread')).toHaveCount(0);
    await testInfo.attach(`embroidery-failed-${variant}`, { body: await page.screenshot(), contentType: 'image/png' });
  });
}

// contract-test: supporting surface=gui.web assertions=design-embroidery.result.view-and-download
for (const width of [390, 1280]) {
  test(`opened view shows the sew-on border among the numbers at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(`${FULLSCREEN}&variant=withBorder`);
    await waitForComponentPreview(page);
    await expect(page.getByTestId('design-embroidery-border-info')).toContainText('3 mm');
    await expect(page.getByTestId('design-embroidery-border-info')).toContainText('Border');
    await expect(page.getByTestId('design-embroidery-note').filter({ hasText: 'Border of 3 mm added for sewing on' })).toHaveCount(1);
    await expect(page.getByTestId('design-embroidery-thread').first()).toContainText('Madeira 1000');
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(0);
    await testInfo.attach(`embroidery-border-${width}`, { body: await page.screenshot(), contentType: 'image/png' });
  });
}

// contract-test: supporting surface=gui.web assertions=design-embroidery.result.view-and-download
test('choosing a border in the settings and applying names the border width in the follow-up', async ({ page }) => {
  await page.route('**/v1/apps/workspace/interpret', route => route.fulfill({ status: 503, json: { detail: 'isolated component request' } }));
  await page.goto(`${FULLSCREEN}&variant=finished`);
  await waitForComponentPreview(page);
  const border = page.getByTestId('design-embroidery-border');
  await border.scrollIntoViewIfNeeded();
  await expect(border).toHaveValue('0');
  await border.selectOption('4');
  const pending = page.waitForRequest('**/v1/apps/workspace/interpret');
  await page.getByTestId('design-embroidery-apply').click();
  const request = (await pending).postDataJSON();
  expect(request.text).toBe('Convert this embroidery design again: width 90 mm, hoop 130 × 180 mm, fabric normal. Add a 4 mm border for sewing on.');
});

// contract-test: supporting surface=gui.web assertions=design-embroidery.result.view-and-download
test('a result without a border shows no border number', async ({ page }) => {
  await page.goto(`${FULLSCREEN}&variant=finished`);
  await waitForComponentPreview(page);
  await expect(page.getByTestId('design-embroidery-size')).toBeVisible();
  await expect(page.getByTestId('design-embroidery-border-info')).toHaveCount(0);
});
