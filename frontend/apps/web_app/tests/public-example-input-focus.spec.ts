// playwright-account: not_required reason=public_logged_out_example_focus_regression
import { test, expect } from './helpers/cookie-audit';
// eslint-disable-next-line @typescript-eslint/no-require-imports -- Shared E2E helper uses CommonJS.
const { getE2EDebugUrl } = require('./signup-flow-helpers');

for (const width of [390, 1280]) {
  // contract-test: direct surface=gui.web assertions=public-example-chats.surface.semantic-parity,message-input.actions.visibility
  test(`opening, reloading and switching public chats leaves input idle at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(getE2EDebugUrl('/#chat-id=example-building-maintenance-email'), { waitUntil: 'domcontentloaded' });
    const field = page.getByTestId('message-field');
    const editor = page.getByTestId('message-editor').locator('.ProseMirror');
    const idle = async () => {
      await expect(page.getByTestId('chat-header-title')).toBeVisible();
      await expect(page.getByTestId('message-assistant').first()).toBeVisible();
      await expect(field).toHaveAttribute('data-focused', 'false');
      await expect(field).not.toHaveClass(/focused/);
      await expect(editor).not.toBeFocused();
      await expect(page.getByTestId('input-dismiss-button')).toHaveCount(0);
    };
    await idle();
    await page.reload({ waitUntil: 'domcontentloaded' });
    await idle();
    await field.click();
    await expect(field).toHaveAttribute('data-focused', 'true');
    await expect(editor).toBeFocused();
    // Navigate without a pointer blur: the route transition must clear both DOM
    // focus and the expanded composer state itself.
    await page.evaluate(() => { window.location.hash = 'chat-id=example-gigantic-airplanes'; });
    await expect(page).toHaveURL(/chat-id=example-gigantic-airplanes/);
    await idle();
    await field.click();
    await expect(editor).toBeFocused();
    await page.keyboard.type('A deliberate follow-up draft');
    await expect(editor).toContainText('A deliberate follow-up draft');
    await expect(field).toHaveAttribute('data-focused', 'true');
  });
}
