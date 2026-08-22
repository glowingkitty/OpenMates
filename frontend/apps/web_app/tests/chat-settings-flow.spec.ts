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
	withMockMarker
} = require('./signup-flow-helpers');

const {
	loginToTestAccount,
	startNewChat,
	sendMessage,
	deleteActiveChat,
	waitForAssistantMessage,
	dismissSecurityReminderIfPresent
} = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
const CHAT_SETTINGS_TABS = ['plan', 'tasks', 'files', 'usage', 'share'];

async function createChatWithSummary(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void,
	takeStepScreenshot: (page: any, label: string) => Promise<void>
): Promise<string> {
	await startNewChat(page, logCheckpoint);
	await sendMessage(
		page,
		withMockMarker(
			'Create a concise project plan for testing a chat settings page, including files, usage, sharing, and tasks.',
			'chat_flow_capital'
		),
		logCheckpoint,
		takeStepScreenshot,
		'chat-settings'
	);
	await waitForAssistantMessage(page, { which: 'last', logCheckpoint });
	await expect(page.getByTestId('chat-header-title')).not.toContainText(/processing|untitled/i, {
		timeout: 30_000
	});
	return (await page.getByTestId('chat-header-title').innerText()).trim();
}

async function expectChatSettingsShell(page: any): Promise<any> {
	const settingsMenu = page.getByTestId('settings-menu');
	await expect(settingsMenu).toBeVisible({ timeout: 15_000 });
	await expect(settingsMenu).toHaveAttribute('data-active-view', /^chats\/[a-zA-Z0-9-]+$/, {
		timeout: 10_000
	});
	await expect(page.getByTestId('chat-details-settings-panel')).not.toBeVisible({ timeout: 2_000 });
	await expect(settingsMenu.getByTestId('chat-settings-page')).toBeVisible({ timeout: 10_000 });
	await expect(settingsMenu.getByTestId('banner-back-button')).toContainText(/Settings\s*\/\s*Chats/i, {
		timeout: 5_000
	});
	return settingsMenu;
}

// contract-test: direct surface=gui.web assertions=chat-share-settings.shell-navigation,chat-share-settings.generated-link-controls
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
	await dismissSecurityReminderIfPresent(page, logCheckpoint);
	const chatHeaderTitle = await createChatWithSummary(page, logCheckpoint, takeStepScreenshot);
	await takeStepScreenshot(page, 'chat-ready');

	await page.getByTestId('chat-share-button').click();
	logCheckpoint('Clicked chat Share button.');

	const settingsMenu = await expectChatSettingsShell(page);
	await expect(settingsMenu.getByTestId('chat-settings-header')).toBeVisible({ timeout: 10_000 });
	await expect(settingsMenu.getByTestId('chat-settings-title')).toHaveText(chatHeaderTitle, { timeout: 10_000 });
	await expect(settingsMenu.getByTestId('chat-settings-title')).not.toContainText(/untitled/i);
	await expect(settingsMenu.getByTestId('chat-settings-credits')).toContainText(/\d+/, { timeout: 10_000 });
	const expandedHeaderMetrics = await settingsMenu.getByTestId('chat-settings-header').evaluate((header: HTMLElement) => {
		const title = header.querySelector<HTMLElement>('[data-testid="chat-settings-title"]');
		const credits = header.querySelector<HTMLElement>('[data-testid="chat-settings-credits"]');
		if (!title || !credits) throw new Error('chat settings header identity missing');
		const headerRect = header.getBoundingClientRect();
		const titleRect = title.getBoundingClientRect();
		const creditsRect = credits.getBoundingClientRect();
		const identityCenterX = (Math.min(titleRect.left, creditsRect.left) + Math.max(titleRect.right, creditsRect.right)) / 2;
		return {
			headerCenterX: headerRect.left + headerRect.width / 2,
			identityCenterX,
			creditsBelowTitle: creditsRect.top > titleRect.bottom
		};
	});
	expect(Math.abs(expandedHeaderMetrics.identityCenterX - expandedHeaderMetrics.headerCenterX)).toBeLessThan(8);
	expect(expandedHeaderMetrics.creditsBelowTitle).toBe(true);

	const settingsSlider = settingsMenu.getByTestId('settings-content-slider');
	await settingsSlider.evaluate((element: HTMLElement) => {
		element.parentElement?.scrollTo({ top: element.parentElement.scrollHeight });
	});
	await expect(async () => {
		const collapsedTitle = await settingsMenu.getByTestId('chat-settings-title').evaluate((title: HTMLElement) => {
			const styles = window.getComputedStyle(title);
			return {
				whiteSpace: styles.whiteSpace,
				overflow: styles.overflow,
				textOverflow: styles.textOverflow,
				singleLine: title.getBoundingClientRect().height <= parseFloat(styles.lineHeight) * 1.35
			};
		});
		expect(collapsedTitle.whiteSpace).toBe('nowrap');
		expect(collapsedTitle.overflow).toBe('hidden');
		expect(collapsedTitle.textOverflow).toBe('ellipsis');
		expect(collapsedTitle.singleLine).toBe(true);
	}).toPass({ timeout: 10_000 });
	await settingsSlider.evaluate((element: HTMLElement) => {
		element.parentElement?.scrollTo({ top: 0 });
	});
	await expect(settingsMenu.getByTestId('chat-settings-title')).not.toHaveCSS('white-space', 'nowrap', { timeout: 10_000 });
	const settingsSummary = settingsMenu.getByTestId('chat-settings-summary');
	await expect(settingsSummary).toBeVisible({ timeout: 10_000 });
	await expect(settingsSummary).not.toContainText(/```json|"embed_id"|\[!\]\(embed:/i);
	const renderedSummaryText = (await settingsSummary.innerText()).trim();
	await expect(settingsMenu.getByTestId('chat-settings-tabs')).toBeVisible({ timeout: 10_000 });
	await expect(settingsMenu.getByTestId('chat-settings-tabpanel-share')).toBeVisible({ timeout: 10_000 });
	await expect(settingsMenu.getByTestId('chat-settings-share-community')).toBeVisible({ timeout: 10_000 });
	await expect(settingsMenu.getByTestId('chat-settings-share-password')).toBeVisible({ timeout: 10_000 });
	await expect(settingsMenu.getByTestId('chat-settings-share-expire')).toBeVisible({ timeout: 10_000 });
	await takeStepScreenshot(page, 'share-tab-opened');

	for (const tab of CHAT_SETTINGS_TABS) {
		await settingsMenu.getByTestId(`chat-settings-tab-${tab}`).click();
		const tabPanel = settingsMenu.getByTestId(`chat-settings-tabpanel-${tab}`);
		await expect(settingsMenu).toHaveAttribute('data-active-view', /^chats\/[a-zA-Z0-9-]+$/);
		await expect(settingsSummary).toHaveText(renderedSummaryText);
		await expect(settingsMenu.getByTestId(`chat-settings-tabpanel-${tab}`)).toBeVisible({
			timeout: 10_000
		});
		await expect(settingsMenu.getByTestId(`chat-settings-tab-${tab}`)).toHaveAttribute('aria-selected', 'true');
		if (tab === 'files') {
			await expect(tabPanel.getByText('No downloadable files found for this chat yet.')).toBeVisible({ timeout: 10_000 });
			await expect(tabPanel.getByTestId('chat-settings-download-files')).toHaveAttribute('aria-disabled', 'true');
		}
		if (tab === 'usage') {
			await expect(tabPanel.getByTestId('chat-settings-usage-total')).toContainText(/\d+\s*credits/i, { timeout: 10_000 });
			await expect(tabPanel.getByTestId('chat-settings-download-usage')).toBeVisible();
			await expect(tabPanel.getByTestId('chat-settings-download-usage')).toContainText('CSV & YAML');
		}
		if (tab === 'tasks') {
			await expect(tabPanel).not.toContainText(/Research Whisper usecases|Implement Whisper code|Debug code/i);
			await expect(tabPanel.getByText(/No tasks are linked to this chat yet|Loading chat tasks|Tasks/i)).toBeVisible({ timeout: 10_000 });
		}
		logCheckpoint(`Deep-linked chat settings tab rendered: ${tab}`);
	}

	await page.evaluate(() => {
		window.dispatchEvent(new CustomEvent('openmates-open-chat-details', {
			detail: { tab: 'share' }
		}));
	});
	await expect(settingsMenu.getByTestId('chat-settings-tabpanel-share')).toBeVisible({ timeout: 10_000 });

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
