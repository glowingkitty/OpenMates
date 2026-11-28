/* eslint-disable @typescript-eslint/no-require-imports -- Existing Playwright helpers expose CommonJS exports. */
import { join } from 'node:path';
import { expect, test } from './helpers/cookie-audit';

const { loginToTestAccount, startNewChat } = require('./helpers/chat-test-helpers');

test.use({ hasTouch: true, isMobile: true, viewport: { width: 390, height: 844 } });

// contract-test: direct surface=gui.web assertions=chats.rendering.image-gestures
test('pinching an attached image keeps the composer and browser scale in place', async ({ page, context, browserName }, testInfo) => {
  test.skip(browserName !== 'chromium', 'Uses Chromium mobile touch input through CDP');
  test.setTimeout(120_000);
  await loginToTestAccount(page);
  await startNewChat(page);

  await page.locator('input[type="file"][multiple]').setInputFiles(join(__dirname, 'fixtures', 'finance.jpeg'));
  const editor = page.getByTestId('message-editor');
  const image = editor.getByRole('img', { name: 'finance.jpeg', exact: true });
  await expect(image).toBeVisible({ timeout: 20_000 });
  await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.naturalWidth)).toBeGreaterThan(0);
  await page.keyboard.press('Escape');
  await image.scrollIntoViewIfNeeded();
  const { x, y } = await image.evaluate(element => {
    const bounds = element.getBoundingClientRect();
    return {
      x: bounds.left + bounds.width / 2,
      y: (Math.max(0, bounds.top) + Math.min(innerHeight, bounds.bottom)) / 2,
    };
  });
  const url = page.url();
  const before = await page.evaluate(() => [performance.timeOrigin, visualViewport?.scale]);
  const input = await context.newCDPSession(page);
  await input.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: x - 18, y, id: 1 }, { x: x + 18, y, id: 2 }] });
  await input.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: x - 38, y, id: 1 }, { x: x + 38, y, id: 2 }] });
  await input.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  await expect(image).toHaveAttribute('data-content-zoomed', '');
  await expect(page.getByTestId('embed-fullscreen-overlay')).toBeHidden();
  await expect(editor).toBeVisible();
  await expect(page).toHaveURL(url);
  expect(await page.evaluate(() => [performance.timeOrigin, visualViewport?.scale])).toEqual(before);
  await testInfo.attach('uploaded-image-pinched', { body: await page.screenshot(), contentType: 'image/png' });
});
