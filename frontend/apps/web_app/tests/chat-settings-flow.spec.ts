/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Chat settings E2E contract.
 *
 * Covers the new deep-linked chat-specific Settings shell page. This spec is
 * intentionally red until the standalone ChatDetailsSettingsPage overlay is
 * replaced by the Settings / Chats route and tabbed page.
 */
export {};

const { test, expect, attachConsoleListeners, attachNetworkListeners, saveWarnErrorLogs } =
	require('./console-monitor');

const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	assertNoMissingTranslations,
	getTestAccount,
	withLiveMockMarker
} = require('./signup-flow-helpers');

const {
	loginToTestAccount,
	startNewChat,
	sendMessage,
	deleteActiveChat,
	waitForAssistantMessage
} = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
const CHAT_SETTINGS_TABS = ['plan', 'tasks', 'files', 'usage', 'share'];

async function createChatWithSummary(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void,
	takeStepScreenshot: (page: any, label: string) => Promise<void>
): Promise<void> {
	await startNewChat(page, logCheckpoint);
	await sendMessage(
		page,
		withLiveMockMarker(
			'Create a concise project plan for testing a chat settings page, including files, usage, sharing, and tasks.',
			'chat_settings_flow'
		),
		logCheckpoint,
		takeStepScreenshot,
		'chat-settings'
	);
	await waitForAssistantMessage(page, { which: 'last', logCheckpoint });
	await expect(page.getByTestId('chat-header-title')).not.toContainText(/processing|untitled/i, {
		timeout: 30_000
	});
}

async function expectChatSettingsShell(page: any): Promise<any> {
	const settingsMenu = page.getByTestId('settings-menu');
	await expect(settingsMenu).toBeVisible({ timeout: 15_000 });
	await expect(settingsMenu).toHaveAttribute('data-active-view', /^chats\/[a-zA-Z0-9-]+$/, {
		timeout: 10_000
	});
	await expect(page.getByTestId('chat-details-settings-panel')).not.toBeVisible({ timeout: 2_000 });
	await expect(settingsMenu.getByTestId('chat-settings-page')).toBeVisible({ timeout: 10_000 });
	await expect(settingsMenu.getByText(/Settings\s*\/\s*Chats/i)).toBeVisible({ timeout: 5_000 });
	return settingsMenu;
}

test('chat Share opens Settings / Chats and supports tab deep links', async ({ page }: { page: any }) => {
	attachConsoleListeners(page);
	attachNetworkListeners(page);

	test.slow();
	test.setTimeout(300_000);

	const logCheckpoint = createSignupLogger('CHAT_SETTINGS_FLOW');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
		filenamePrefix: 'chat-settings-flow'
	});

	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	await archiveExistingScreenshots(logCheckpoint);
	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
	await createChatWithSummary(page, logCheckpoint, takeStepScreenshot);
	await takeStepScreenshot(page, 'chat-ready');

	await page.getByTestId('chat-share-button').click();
	logCheckpoint('Clicked chat Share button.');

	const settingsMenu = await expectChatSettingsShell(page);
	await expect(settingsMenu.getByTestId('chat-settings-header')).toBeVisible({ timeout: 10_000 });
	await expect(settingsMenu.getByTestId('chat-settings-title')).toBeVisible({ timeout: 10_000 });
	await expect(settingsMenu.getByTestId('chat-settings-credits')).toContainText(/credit/i, { timeout: 10_000 });
	await expect(settingsMenu.getByTestId('chat-settings-summary')).toBeVisible({ timeout: 10_000 });
	await expect(settingsMenu.getByTestId('chat-settings-tabs')).toBeVisible({ timeout: 10_000 });
	await expect(settingsMenu.getByTestId('chat-settings-tabpanel-share')).toBeVisible({ timeout: 10_000 });
	await takeStepScreenshot(page, 'share-tab-opened');

	for (const tab of CHAT_SETTINGS_TABS) {
		await page.evaluate((requestedTab: string) => {
			window.dispatchEvent(new CustomEvent('openmates-open-chat-details', {
				detail: { tab: requestedTab }
			}));
		}, tab);
		await expect(settingsMenu.getByTestId(`chat-settings-tabpanel-${tab}`)).toBeVisible({
			timeout: 10_000
		});
		await expect(settingsMenu.getByTestId(`chat-settings-tab-${tab}`)).toHaveAttribute('aria-selected', 'true');
		logCheckpoint(`Deep-linked chat settings tab rendered: ${tab}`);
	}

	await page.evaluate(() => {
		window.dispatchEvent(new CustomEvent('openmates-open-chat-details', {
			detail: { tab: 'not-a-real-tab' }
		}));
	});
	await expect(settingsMenu.getByTestId('chat-settings-tabpanel-plan')).toBeVisible({ timeout: 10_000 });
	await expect(settingsMenu.getByTestId('chat-settings-tab-plan')).toHaveAttribute('aria-selected', 'true');
	logCheckpoint('Invalid chat settings tab falls back to Plan.');

	await assertNoMissingTranslations(page);
	saveWarnErrorLogs('chat-settings-flow', 'after_assertions');
	await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'chat-settings-cleanup');
});
