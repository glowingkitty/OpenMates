// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

for (const width of [390, 1280]) {
  // contract-test: direct surface=gui.web assertions=message-input.actions.visibility,message-input.send.ownership
  test(`fully minimizes after an accepted image submission at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    const availability = { active: true, can_send_text: true, reason: null };
    await page.route('**/v1/settings/server-status', route => route.fulfill({ json: {
      is_self_hosted: false, payment_enabled: true, server_edition: 'development',
      ai_models_configured: true, anonymous_free_usage: availability,
    } }));
    await page.route('**/v1/anonymous/free-usage/status**', route => route.fulfill({ json: availability }));
    await page.route('**/v1/anonymous/chat/stream', route => route.fulfill({ json: {
      status: 'completed', messageId: 'synthetic-response', assistant: 'Synthetic response',
    } }));
    const params = new URLSearchParams({ chrome: '0', theme: 'dark', background: '#dbeafe',
      width: String(Math.min(width, 680)), variant: 'imageDraft' });
    await page.goto(`/dev/preview/enter_message/MessageInputFocusFixture?${params}`);
    await waitForComponentPreview(page);
    await expect(page.getByTestId('composer-focus-fixture')).toHaveAttribute('data-ready', 'true');
    const field = page.getByTestId('message-field');
    const editor = page.getByTestId('message-editor').locator('.ProseMirror');
    await expect(editor.getByTestId('embed-preview')).toHaveCount(1);
    await field.click({ position: { x: 8, y: 8 } });
    await expect(field).toHaveAttribute('data-focused', 'true');
    await expect(field.getByTestId('action-buttons')).toBeVisible();
    await page.getByTestId('composer-send-button').click();
    await expect(editor).toBeEmpty();
    await expect(editor.getByTestId('embed-preview')).toHaveCount(0);
    await expect(field).toHaveAttribute('data-focused', 'false');
    await expect(field.getByTestId('action-buttons')).toHaveCount(0);
    await expect(field).toHaveCSS('height', '48px');
    await expect(editor).not.toBeFocused();
    await expect(page.getByTestId('composer-attachment-shortcut')).toBeVisible();
  });
}
