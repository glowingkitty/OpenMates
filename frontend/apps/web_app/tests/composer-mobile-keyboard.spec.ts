// playwright-account: not_required reason=public_guest_composer
import { test, expect } from './helpers/cookie-audit';
import { getE2EDebugUrl } from './signup-flow-helpers';

test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });

// contract-test: direct surface=gui.web assertions=message-input.layout.responsive-parity,message-input.actions.visibility
test('keeps attachment actions above a keyboard that only resizes the visual viewport', async ({ page }) => {
  await page.addInitScript(() => {
    const viewport = window.visualViewport!;
    let height = 844;
    let offsetTop = 0;
    Object.defineProperties(viewport, {
      height: { get: () => height },
      offsetTop: { get: () => offsetTop },
      scale: { get: () => 1 },
    });
    Object.assign(window, {
      fixtureKeyboardViewport: (nextHeight: number, nextTop: number) => {
        height = nextHeight;
        offsetTop = nextTop;
        viewport.dispatchEvent(new Event('resize'));
        viewport.dispatchEvent(new Event('scroll'));
      },
    });
  });
  await page.goto(getE2EDebugUrl('/#chat-id=example-svelte-runes-docs'), { waitUntil: 'domcontentloaded' });
  await expect(page.getByTestId('active-chat-container')).toBeVisible({ timeout: 15000 });
  await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-current-chat-id', 'example-svelte-runes-docs', { timeout: 15000 });
  await expect(page.getByTestId('mate-message-content').last()).toContainText('Svelte', { timeout: 15000 });
  const field = page.getByTestId('message-field');
  await field.click();
  const editor = page.getByTestId('message-editor').locator('.ProseMirror');
  await editor.fill('Keep this draft while choosing a photo.');
  await expect(editor).toBeFocused();

  // iOS keeps the layout viewport unchanged while its keyboard covers the bottom.
  await page.evaluate(() => (window as any).fixtureKeyboardViewport(480, 0));
  await expect.poll(async () => {
    const bounds = await field.boundingBox();
    return bounds!.y + bounds!.height;
  }, { message: 'The whole composer remains above the keyboard' }).toBeLessThanOrEqual(481);
  await expect(editor).toBeFocused();
  await page.getByTestId('composer-attachment-menu-button').click();
  await expect(page.getByTestId('composer-attachment-menu')).toBeVisible();
  const menu = await page.getByTestId('composer-attachment-menu').boundingBox();
  expect(menu!.y).toBeGreaterThanOrEqual(0);
  expect(menu!.y + menu!.height).toBeLessThanOrEqual(481);

  // Safari can pan the visual viewport independently during focus/picker handoff.
  await page.evaluate(() => (window as any).fixtureKeyboardViewport(420, 50));
  await expect.poll(async () => {
    const bounds = await field.boundingBox();
    return bounds!.y + bounds!.height;
  }).toBeLessThanOrEqual(471);
  await expect(editor).toHaveText('Keep this draft while choosing a photo.');
  await page.evaluate(() => (window as any).fixtureKeyboardViewport(844, 0));
  await expect.poll(async () => {
    const bounds = await page.locator('.main-content').boundingBox();
    return bounds!.height;
  }).toBe(844);
});
