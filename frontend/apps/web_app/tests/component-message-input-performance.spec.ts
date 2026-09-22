/**
 * Focused responsiveness check for the standalone MessageInput preview.
 * This stays independent from the broader visual-state proof so unrelated
 * microphone or model-menu assertions cannot hide a typing regression.
 */
import { expect, test } from './helpers/cookie-audit';

// playwright-account: not_required reason=isolated_component_preview

test.describe('MessageInput component responsiveness', () => {
	// contract-test: direct surface=gui.web assertions=message-input.actions.visibility,message-input.drafts.preview-persistence
	test('keeps the primary action clickable across the draft blur timeout', async ({ page }) => {
		await page.goto('/dev/preview/enter_message/MessageInput?chrome=0&width=680', {
			waitUntil: 'networkidle'
		});
		const editable = page.getByTestId('message-editor').locator('[contenteditable="true"]');
		await page.getByTestId('message-field').click();
		await editable.fill('Keep this draft ready to send.');
		const action = page.locator('[data-action="send-message"], [data-action="sign-up-to-send"]');
		await expect(action).toBeVisible();
		await action.hover();
		await page.mouse.down();
		try {
			// Hold past the 150ms editor-blur timer and the 250ms action-row outro.
			// A slow click must retain its original target while autosave can run.
			await page.waitForTimeout(450);
			await expect(editable).toBeVisible();
			await expect(action).toBeVisible();
			expect(await action.evaluate((element) => element.closest('[inert]'))).toBeNull();
			await expect(action).toBeFocused();
		} finally {
			// The isolated preview checks focus continuity without sending a request.
			await page.mouse.move(0, 0);
			await page.mouse.up();
		}
	});

	// contract-test: direct surface=gui.web assertions=message-input.drafts.preview-persistence
	test('keeps mid-draft typing responsive before a trailing delimiter', async ({ page }) => {
		const params = new URLSearchParams({
			theme: 'light',
			background: '#dbeafe',
			width: '680',
			chrome: '0'
		});

		await page.goto(`/dev/preview/enter_message/MessageInput?${params}`, {
			waitUntil: 'networkidle'
		});
		await expect(page.getByTestId('component-preview-canvas')).toHaveAttribute(
			'data-preview-ready',
			'true'
		);

		await page.getByTestId('message-field').click();
		const editable = page.getByTestId('message-editor').locator('[contenteditable="true"]');
		await expect(editable).toBeVisible();
		await editable.fill('Draft ending.');
		await editable.press('ArrowLeft');

		const typingStartedAt = Date.now();
		await editable.pressSequentially('quick');
		const typingDurationMs = Date.now() - typingStartedAt;

		await expect(editable).toContainText('Draft endingquick.');
		expect(
			typingDurationMs,
			'Mid-draft typing before a trailing delimiter must stay responsive'
		).toBeLessThan(2_000);
	});
});
