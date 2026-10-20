// playwright-account: not_required reason=isolated_component_preview
import { test, expect } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

test.describe('Minimized composer Send shape', () => {
  for (const { viewportWidth, fieldWidth } of [
    { viewportWidth: 390, fieldWidth: 330 },
    { viewportWidth: 1280, fieldWidth: 680 }
  ]) {
    // contract-test: direct surface=gui.web assertions=message-input.actions.visibility,message-input.layout.responsive-parity
    test(`keeps Send circular in normal, hovered and pressed states at ${viewportWidth}px`, async ({ page }) => {
      await page.setViewportSize({ width: viewportWidth, height: 844 });
      const availability = { active: true, can_send_text: true, reason: null };
      await page.route('**/v1/settings/server-status', (route) => route.fulfill({ json: {
        is_self_hosted: false, payment_enabled: true, server_edition: 'development',
        ai_models_configured: true, anonymous_free_usage: availability
      } }));
      await page.route('**/v1/anonymous/free-usage/status**', (route) => route.fulfill({ json: availability }));
      const params = new URLSearchParams({
        theme: 'dark', background: '#dbeafe', width: String(fieldWidth), chrome: '0', variant: 'inlineCompact'
      });
      await page.goto(`/dev/preview/enter_message/MessageInput?${params}`);
      await waitForComponentPreview(page);
      const field = page.getByTestId('message-field');
      await field.click();
      await page.getByTestId('message-editor').locator('.ProseMirror').fill('asd');
      await page.mouse.click(4, 4);
      await expect(field).toHaveAttribute('data-focused', 'false');
      await expect(field).toHaveCSS('height', '48px');
      await expect(page.getByTestId('message-draft-summary-text')).toHaveText('asd');
      await expect(page.getByTestId('action-buttons')).toHaveCount(0);

      const send = page.getByTestId('composer-send-button');
      await expect(send).toBeVisible();
      await expect(send).toBeEnabled();
      await expect(send).toHaveAttribute('aria-label', 'Send');
      await expect(send.locator('svg')).toBeVisible();
      await expect(send).toHaveCSS('width', '40px');
      await expect(send).toHaveCSS('height', '40px');
      await expect(send).toHaveCSS('border-radius', '50%');
      const expectRoundSend = async () => {
        await expect.poll(() => send.evaluate((element) => {
          const { width, height } = element.getBoundingClientRect();
          return Math.abs(width - height);
        })).toBeLessThan(1);
      };
      await expectRoundSend();
      await send.hover();
      await expectRoundSend();
      await page.mouse.down();
      await expectRoundSend();
      // Release away from Send so this geometry check never submits a message.
      await page.mouse.move(4, 4);
      await page.mouse.up();
      await expect(field).toHaveAttribute('data-focused', 'false');
      await expectRoundSend();
    });
  }
});
