/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Example chat settings usage regression tests.
 *
 * Verifies that guest-accessible static example chats can show real historical
 * usage costs when the generated example data includes static usage_entries.
 * The flow stays unauthenticated and must not depend on private usage APIs.
 */

const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl } = require('./signup-flow-helpers');

const GENERATED_AUDIO_USAGE_CASES = [
	{
		chatId: 'example-audio-generate-product-success-chime',
		totalCredits: /31\s*credits/i,
		aiCredits: '17',
		audioLabel: 'audio | generate',
		audioCredits: '14'
	},
	{
		chatId: 'example-audio-speak-friendly-welcome-message',
		totalCredits: /28\s*credits/i,
		aiCredits: '18',
		audioLabel: 'audio | speak',
		audioCredits: '10'
	}
] as const;

async function openExampleUsageTab(page: any, exampleChatId: string): Promise<any> {
	await page.goto(getE2EDebugUrl(`/#chat-id=${exampleChatId}`), {
		waitUntil: 'domcontentloaded'
	});

	await expect(page.getByTestId('example-chat-badge')).toBeVisible({ timeout: 15000 });
	await expect(page.getByTestId('chat-details-button')).toBeVisible({ timeout: 10000 });

	await page.getByTestId('chat-details-button').click();
	const settingsMenu = page.getByTestId('settings-menu');
	await expect(settingsMenu).toBeVisible({ timeout: 10000 });
	await expect(settingsMenu.getByTestId('chat-settings-tab-share')).toBeVisible({ timeout: 10000 });
	await expect(settingsMenu.getByTestId('chat-settings-tab-usage')).toBeVisible({ timeout: 10000 });
	await expect(settingsMenu.getByTestId('chat-settings-tab-plan')).toHaveCount(0);
	await expect(settingsMenu.getByTestId('chat-settings-tab-tasks')).toHaveCount(0);
	await expect(settingsMenu.getByTestId('chat-settings-tab-files')).toHaveCount(0);

	await settingsMenu.getByTestId('chat-settings-tab-usage').click();
	await expect(settingsMenu).toHaveAttribute('data-active-view', `chats/${exampleChatId}`, {
		timeout: 10000
	});
	await expect(settingsMenu.getByTestId('chat-settings-tabpanel-usage')).toBeVisible({ timeout: 10000 });
	return settingsMenu;
}

test.describe('Example chat settings usage', () => {
	// contract-test: direct surface=gui.web assertions=billing.usage.receipt-token-breakdown,public-example-chats.surface.semantic-parity
	test('guest example chat with static usage exposes usage tab and rows', async ({ page }: { page: any }) => {
		test.setTimeout(60000);
		const exampleChatId = 'example-berlin-morning-bike-forecast';

		const settingsMenu = await openExampleUsageTab(page, exampleChatId);
		await expect(settingsMenu.getByTestId('chat-settings-usage-total')).toContainText(/25\s*credits/i);
		await expect(settingsMenu.getByTestId('chat-settings-usage-row')).toHaveCount(2);
		await expect(settingsMenu.getByTestId('chat-settings-usage-row').first()).toContainText('ai | ask');
		await expect(settingsMenu.getByTestId('chat-settings-usage-row').first()).toContainText('Google AI Studio / US');
		await expect(settingsMenu.getByTestId('chat-settings-usage-row').first()).toContainText('24');
		await expect(settingsMenu.getByTestId('chat-settings-usage-row').nth(1)).toContainText('weather | forecast');
		await expect(settingsMenu.getByTestId('chat-settings-usage-row').nth(1)).toContainText('1');
	});

	// contract-test: direct surface=gui.web assertions=billing.usage.receipt-token-breakdown,audio-generate.billing.success-only,audio-speak.billing.success-only
	test('generated audio example chats include audio app-skill usage rows', async ({ page }: { page: any }) => {
		test.setTimeout(90000);

		for (const exampleCase of GENERATED_AUDIO_USAGE_CASES) {
			const settingsMenu = await openExampleUsageTab(page, exampleCase.chatId);
			const rows = settingsMenu.getByTestId('chat-settings-usage-row');
			await expect(settingsMenu.getByTestId('chat-settings-usage-total')).toContainText(exampleCase.totalCredits);
			await expect(rows).toHaveCount(2);
			await expect(rows.first()).toContainText('ai | ask');
			await expect(rows.first()).toContainText('Google AI Studio / US');
			await expect(rows.first()).toContainText(exampleCase.aiCredits);
			await expect(rows.nth(1)).toContainText(exampleCase.audioLabel);
			await expect(rows.nth(1)).toContainText('ElevenLabs / US');
			await expect(rows.nth(1)).toContainText(exampleCase.audioCredits);
		}
	});
});
