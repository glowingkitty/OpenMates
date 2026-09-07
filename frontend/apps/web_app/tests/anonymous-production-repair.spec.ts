/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Real anonymous-chat regression for production issue H753F.
 *
 * This opt-in test uses the deployed browser and anonymous inference paths
 * without request mocks. It is safe for dev and bounded production smoke runs.
 */

const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl, assertNoMissingTranslations } = require('./signup-flow-helpers');

const REPORTED_PROMPT =
	'is it practical to run clo3d in a VM in virtual box? heard there is a 256mb vram max for vms? is that true? if so, this would be a no go...';
const PROCESSING_ERROR = 'The AI service encountered an error while processing your request.';

async function startAnonymousChat(page: any): Promise<void> {
	await page.goto(getE2EDebugUrl('/#chat-id=demo-for-everyone'), { waitUntil: 'domcontentloaded' });
	await page.waitForLoadState('networkidle');
	const newChatCta = page.getByTestId('new-chat-cta-fullwidth');
	await expect(newChatCta).toBeVisible({ timeout: 15_000 });
	await newChatCta.click();
	await expect(page.getByTestId('message-editor').locator('[contenteditable="true"]').first()).toBeVisible({
		timeout: 10_000
	});
}

async function typeMessage(page: any, text: string): Promise<void> {
	const editor = page.getByTestId('message-editor');
	const editable = editor.locator('[contenteditable="true"]').first();
	await page.getByTestId('message-field').click();
	await editable.click();
	await editable.pressSequentially(text);
	await expect(editor).toContainText(text);
}

test.describe('Anonymous production repair', () => {
	// contract-test: direct surface=gui.web assertions=chats.streaming.ordered-final,chats.surface.semantic-parity
	test('completes the reported prompt with authoritative model attribution', async ({ page }: { page: any }) => {
		test.setTimeout(150_000);
		await page.setViewportSize({ width: 390, height: 844 });
		await page.addInitScript((anonymousId: string) => {
			localStorage.removeItem('openmates:last-auth-method');
			localStorage.setItem('openmates_anonymous_id', anonymousId);
		}, `h753f-web-${Date.now()}-${Math.random().toString(16).slice(2)}`);

		await startAnonymousChat(page);
		await typeMessage(page, REPORTED_PROMPT);
		await page.locator('[data-action="send-message"]').click();

		const assistant = page.getByTestId('message-assistant').last();
		await expect(assistant).toBeVisible({ timeout: 120_000 });
		await expect(assistant).toHaveAttribute('data-streaming', 'false', { timeout: 120_000 });
		await expect(assistant).not.toContainText(PROCESSING_ERROR);
		await expect(assistant).toContainText(/CLO3D|VirtualBox|VRAM/i);

		const attribution = page.getByTestId('generated-by').last();
		await expect(attribution).toBeVisible({ timeout: 15_000 });
		await expect(attribution).not.toContainText('openmates-ai');
		await expect(attribution).not.toHaveText('');
		await assertNoMissingTranslations(page);
	});
});
