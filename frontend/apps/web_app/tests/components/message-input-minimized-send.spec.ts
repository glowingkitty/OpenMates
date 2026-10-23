// playwright-account: not_required reason=isolated_component_preview
import { test, expect } from '../helpers/cookie-audit';
import { waitForComponentMotion, waitForComponentPreview } from '../helpers/component-preview';

test.describe('Minimized composer Send shape', () => {
  for (const { viewportWidth, fieldWidth } of [
    { viewportWidth: 390, fieldWidth: 330 },
    { viewportWidth: 1280, fieldWidth: 400 },
    { viewportWidth: 1280, fieldWidth: 680 }
  ]) {
    // contract-test: direct surface=gui.web assertions=message-input.actions.visibility,message-input.layout.responsive-parity
    test(`keeps composer controls contained at ${fieldWidth}px inside a ${viewportWidth}px viewport`, async ({ page }) => {
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
      const expand = page.getByTestId('message-expand-button');
      await expect(expand).toHaveCount(0);
      await field.click();
      await expect(expand).toHaveCount(0);
      const editor = page.getByTestId('message-editor').locator('.ProseMirror');
      await editor.fill('s');
      await expect(expand).toHaveCount(0);
      const label = page.getByTestId('composer-model-selector-label');
      if (fieldWidth < 576) await expect(label).toBeHidden();
      else await expect(label).toBeVisible();
      const send = page.getByTestId('composer-send-button');
      await expect(send).toBeVisible();
      await expect.poll(() => field.evaluate((element) => {
        const field = element.getBoundingClientRect();
        const selector = element.querySelector('[data-testid="composer-model-selector"]')!.getBoundingClientRect();
        const speech = element.querySelector('[data-testid="assistant-speech-toggle"]')!.getBoundingClientRect();
        const send = element.querySelector('[data-testid="composer-send-button"]')!.getBoundingClientRect();
        return selector.right <= speech.left && send.right <= field.right && send.left >= field.left;
      })).toBe(true);

      const longDraft = Array.from({ length: 30 }, (_, index) => `Line ${index + 1}: a draft that needs more room.`).join('\n');
      await editor.fill(longDraft);
      await expect(expand).toBeVisible();
      await expand.click();
      await expect(field).toHaveClass(/fullscreen-expanded/);
      await waitForComponentMotion(field);
      await editor.fill('');
      // Collapse remains reachable even after an expanded draft is cleared.
      await expect(expand).toBeVisible();
      await expand.click();
      await expect(field).not.toHaveClass(/fullscreen-expanded/);
      await waitForComponentMotion(field);
      await expect(expand).toHaveCount(0);
      await editor.fill('asd');
      await expect(expand).toHaveCount(0);
      await page.mouse.click(4, 4);
      await expect(field).toHaveAttribute('data-focused', 'false');
      await expect(field).toHaveCSS('height', '48px');
      await expect(page.getByTestId('message-draft-summary-text')).toHaveText('asd');
      await expect(page.getByTestId('action-buttons')).toHaveCount(0);

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
