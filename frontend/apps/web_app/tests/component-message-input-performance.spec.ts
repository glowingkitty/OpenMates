/**
 * Focused responsiveness check for the standalone MessageInput preview.
 * This stays independent from the broader visual-state proof so unrelated
 * microphone or model-menu assertions cannot hide a typing regression.
 */
import { expect, test } from './helpers/cookie-audit';

// playwright-account: not_required reason=isolated_component_preview

test.describe('MessageInput component responsiveness', () => {
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
