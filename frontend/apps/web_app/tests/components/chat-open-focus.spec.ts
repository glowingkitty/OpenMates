// playwright-account: not_required reason=isolated_component_preview
import { test, expect } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
import { expectFocusedChatWheelScroll } from '../helpers/chat-scroll';

const first = 'example-gigantic-airplanes';
const second = 'example-building-maintenance-email';

for (const width of [390, 1280]) {
  // contract-test: direct surface=gui.web assertions=message-input.actions.visibility,public-example-chats.surface.semantic-parity
  test(`chat navigation waits for deliberate composer focus at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(`/dev/preview/ActiveChatFocusFixture?theme=light&background=%23dbeafe&width=${width}&chrome=0`);
    await waitForComponentPreview(page);
    const field = page.getByTestId('message-field');
    const editor = page.getByTestId('message-editor').locator('.ProseMirror');
    let loadCount = 0;
    const open = async (id: string) => {
      await page.evaluate((chatId) => window.dispatchEvent(new CustomEvent('fixtureOpenExample', { detail: chatId })), id);
      await expect(page.getByTestId('example-focus-fixture')).toHaveAttribute('data-loaded', id);
      await expect(page.getByTestId('example-focus-fixture')).toHaveAttribute('data-load-count', String(++loadCount));
    };
    await expect(field).toHaveAttribute('data-focused', 'false');
    await expect(editor).not.toBeFocused();
    await open(first);
    await expect(field).toHaveAttribute('data-focused', 'false');
    await expect(field).not.toHaveClass(/focused/);
    await expect(editor).not.toBeFocused();
    await field.click();
    await expect(editor).toBeFocused();
    await page.keyboard.type('Keep my typing session');
    // A duplicate load of the same chat must preserve deliberate typing focus.
    await open(first);
    await expect(editor).toBeFocused();
    await expect(editor).toContainText('Keep my typing session');
    await open(second);
    await expect(field).toHaveAttribute('data-focused', 'false');
    await expect(field).not.toHaveClass(/focused/);
    await expect(editor).not.toBeFocused();
    await field.click();
    await expect(editor).toBeFocused();
    await expect(field).toHaveAttribute('data-focused', 'true');
    await page.keyboard.type('Manual entry remains available');
    await expect(editor).toContainText('Manual entry remains available');
    await test.step('Scroll the conversation in both directions while typing stays active', async () => {
      await expectFocusedChatWheelScroll(page);
    });
  });
}
