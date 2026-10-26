// playwright-account: not_required reason=isolated_component_preview
import { test, expect } from '../helpers/cookie-audit';
import { waitForComponentMotion, waitForComponentPreview } from '../helpers/component-preview';

for (const device of [
  { name: 'phone', width: 390, touch: true, camera: true },
  { name: 'iPad desktop viewport', width: 1024, touch: true, camera: true },
  { name: 'desktop', width: 1280, touch: false, camera: false },
]) {
  test.describe(`Attachment shortcut on ${device.name}`, () => {
    test.use({ viewport: { width: device.width, height: 844 }, hasTouch: device.touch });

    // contract-test: direct surface=gui.web assertions=message-input.attachments.quick-access,message-input.embeds.gated-send
    test('opens the correct picker without opening text entry and preserves a cancelled draft', async ({ page }) => {
      if (device.name.startsWith('iPad')) {
        await page.addInitScript(() => {
          Object.defineProperty(navigator, 'platform', { get: () => 'MacIntel' });
          Object.defineProperty(navigator, 'maxTouchPoints', { get: () => 5 });
        });
      }
      const params = new URLSearchParams({ theme: device.camera ? 'dark' : 'light', background: '#dbeafe', width: String(Math.min(device.width - 40, 680)), chrome: '0' });
      await page.goto(`/dev/preview/enter_message/MessageInput?${params}`);
      await waitForComponentPreview(page);
      const field = page.getByTestId('message-field');
      const editor = page.getByTestId('message-editor').locator('.ProseMirror');
      const shortcut = page.getByTestId('composer-attachment-shortcut');
      await expect(shortcut).toBeVisible();
      await expect(shortcut).toHaveAccessibleName(device.camera ? /photo/i : /^files$/i);
      await expect(shortcut.locator(device.camera ? '.icon_camera' : '.icon_files')).toBeVisible();
      await expect(shortcut).toHaveCSS('width', '40px');
      await expect(shortcut).toHaveCSS('height', '40px');
      const bounds = await shortcut.boundingBox();
      const fieldBounds = await field.boundingBox();
      expect(bounds!.x).toBeGreaterThanOrEqual(fieldBounds!.x);
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(fieldBounds!.x + fieldBounds!.width);
      if (!device.touch) {
        await shortcut.hover();
        await shortcut.focus();
        await expect(shortcut).toBeFocused();
      }
      const chooserEvent = page.waitForEvent('filechooser');
      if (device.touch) await shortcut.tap(); else await shortcut.press('Enter');
      const chooser = await chooserEvent;
      expect(await chooser.element().getAttribute('data-testid')).toBe(device.camera ? 'message-camera-input' : 'message-file-input');
      expect(await chooser.element().getAttribute('capture')).toBe(device.camera ? 'environment' : null);
      expect(chooser.isMultiple()).toBe(!device.camera);
      await expect(editor).not.toBeFocused();
      await expect(field).toHaveAttribute('data-focused', 'false');
      await chooser.element().dispatchEvent('cancel');
      await expect(editor).toBeEmpty();
      await expect(shortcut).toBeVisible();

      await field.click();
      await editor.fill('Keep this draft when cancelling an attachment.');
      await page.getByTestId('composer-attachment-menu-button').click();
      await expect(page.getByTestId('composer-attachment-menu')).toBeVisible();
      const secondChooserEvent = page.waitForEvent('filechooser');
      await page.getByTestId(device.camera ? 'composer-attachment-camera' : 'composer-attachment-files').click();
      const secondChooser = await secondChooserEvent;
      expect(await secondChooser.element().getAttribute('data-testid')).toBe(device.camera ? 'message-camera-input' : 'message-file-input');
      // Flush the click task and TipTap's frame queue before asserting the
      // picker handoff did not schedule a keyboard-opening editor refocus.
      await page.evaluate(() => new Promise<void>((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
      }));
      await expect(editor).not.toBeFocused();
      await secondChooser.element().dispatchEvent('cancel');
      await expect(editor).toHaveText('Keep this draft when cancelling an attachment.');
      await expect(field).toBeVisible();
      await editor.click();
      await editor.press('End');
      await editor.press('!');
      await expect(editor).toContainText('attachment.!');
    });
  });
}

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
