// playwright-account: not_required reason=public_logged_out_focused_chat_scroll
import { test, expect } from './helpers/cookie-audit';
import { expectFocusedChatWheelScroll } from './helpers/chat-scroll';
// eslint-disable-next-line @typescript-eslint/no-require-imports -- Shared E2E helper uses CommonJS.
const { getE2EDebugUrl } = require('./signup-flow-helpers');

for (const width of [390, 1280]) {
  // contract-test: direct surface=gui.web assertions=message-input.actions.visibility,public-example-chats.surface.semantic-parity
  test(`can scroll the conversation while composing at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(getE2EDebugUrl('/#chat-id=example-gigantic-airplanes'), { waitUntil: 'domcontentloaded' });
    const field = page.getByTestId('message-field');
    const editor = page.getByTestId('message-editor').locator('.ProseMirror');
    const ready = async () => {
      await expect(page.getByTestId('chat-header-title')).toBeVisible();
      await expect(page.getByTestId('message-assistant').first()).toBeVisible();
      await expect(field).toHaveAttribute('data-focused', 'false');
      await expect(editor).not.toBeFocused();
    };
    await ready();
    await page.reload({ waitUntil: 'domcontentloaded' });
    await ready();
    await field.click();
    const draft = 'Unsent draft while reading older messages';
    await page.keyboard.type(draft);
    await expect(editor).toContainText(draft);
    await test.step('Scroll up and down without dismissing the composer', async () => {
      await expectFocusedChatWheelScroll(page);
    });
    await expect(editor).toContainText(draft);
  });
}
