/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Exact-dimension proof-video source for default model settings.
 *
 * This spec is intentionally manual-only. It records login and the visible
 * default-model settings flow in one page per required proof profile so the
 * in-memory encryption key remains available for new-chat sends.
 *
 * Product regression coverage remains in default-model-settings.spec.ts; this
 * file exists to produce proof-video-compatible Playwright source artifacts.
 */

// contract-test-file: tooling
export {};

const fs = require('fs');
const path = require('path');

const {
	test,
	expect,
	attachConsoleListeners,
	attachNetworkListeners
} = require('./console-monitor');

const {
	createSignupLogger,
	getTestAccount,
	withMockMarker
} = require('./signup-flow-helpers');

const {
	fillMessageEditor,
	loginToTestAccount,
	startNewChat,
	deleteActiveChat,
	waitForAssistantMessage
} = require('./helpers/chat-test-helpers');

const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

const PROOF_RECORDING_DIR = 'test-results/proof-video-source/default-model-settings';
const MODEL_CHANGE_NOTIFICATION_RE = /Changed model for/i;
const MISTRAL_SELECTED_NOTIFICATION = "Changed model for Simple requests from 'Auto' to 'Mistral Small 3.2'";
const PROOF_PROFILE_TIMEOUT_MS = 360000;
const SECURITY_REMINDER_TITLE = 'Security Reminder';
const VISIBLE_SETTINGS_MENU = '[data-testid="settings-menu"].visible';
const AI_SETTINGS_PATH = 'ai';
const VISIBLE_PROOF_QUESTION = 'Capital of Germany?';

const PROOF_VIEWPORTS = [
	{ name: 'web-phone', width: 390, height: 844 },
	{ name: 'web-laptop', width: 1440, height: 900 }
] as const;

async function noopScreenshot(_page: any, _label: string): Promise<void> {}

async function dismissSecurityReminder(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void
): Promise<void> {
	const reminder = page.getByTestId('notification').filter({ hasText: SECURITY_REMINDER_TITLE });
	if (!(await reminder.isVisible({ timeout: 2000 }).catch(() => false))) return;

	await reminder.getByTestId('notification-dismiss').click({ timeout: 5000 });
	await expect(reminder).not.toBeVisible({ timeout: 10000 });
	logCheckpoint('Dismissed security reminder.');
}

async function requestAiSettingsPanel(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void
): Promise<void> {
	await page.evaluate((settingsPath: string) => {
		window.dispatchEvent(new CustomEvent('openSettingsMenu', { detail: { returnTo: settingsPath } }));
	}, AI_SETTINGS_PATH);
	logCheckpoint('Requested AI settings panel via app settings event.');
}

async function navigateToAiSettings(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void
): Promise<void> {
	const settingsMenu = page.locator(VISIBLE_SETTINGS_MENU);
	const aiSettings = page.getByTestId('ai-settings');
	if (
		await settingsMenu
			.getByTestId('ai-settings')
			.isVisible({ timeout: 500 })
			.catch(() => false)
	) {
		logCheckpoint('AI Settings page already loaded.');
		return;
	}

	await dismissSecurityReminder(page, logCheckpoint);

	if (!(await settingsMenu.isVisible({ timeout: 500 }).catch(() => false))) {
		const settingsToggle = page.locator('#settings-menu-toggle');
		await expect(settingsToggle).toBeVisible({ timeout: 10000 });
		await settingsToggle.click({ force: true, timeout: 5000 });
		if (!(await settingsMenu.isVisible({ timeout: 2000 }).catch(() => false))) {
			await settingsToggle.dispatchEvent('click');
		}
		if (!(await settingsMenu.isVisible({ timeout: 2000 }).catch(() => false))) {
			await requestAiSettingsPanel(page, logCheckpoint);
		}
	}

	await expect(settingsMenu).toBeVisible({ timeout: 10000 });
	logCheckpoint('Opened settings menu.');
	if (await aiSettings.isVisible({ timeout: 2000 }).catch(() => false)) {
		logCheckpoint('AI Settings page loaded.');
		return;
	}

	const aiMenuItem = settingsMenu.getByRole('menuitem', { name: /^AI$/i }).first();
	await expect(aiMenuItem).toBeVisible({ timeout: 5000 });
	await aiMenuItem.click();
	logCheckpoint('Clicked AI menu item.');

	await expect(aiSettings).toBeVisible({ timeout: 8000 });
	logCheckpoint('AI Settings page loaded.');
}

async function closeSettings(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void
): Promise<void> {
	const settingsMenu = page.getByTestId('settings-menu');
	if (await settingsMenu.isVisible().catch(() => false)) {
		await page.getByTestId('icon-button-close').click({ timeout: 5000 });
		logCheckpoint('Closed settings.');
		await page.waitForTimeout(500);
	}
}

function modelChangeNotifications(page: any) {
	return page.getByTestId('notification').filter({ hasText: MODEL_CHANGE_NOTIFICATION_RE });
}

function modelChangeNotification(page: any, expectedText: string) {
	return modelChangeNotifications(page).filter({ hasText: expectedText });
}

async function sendProofQuestionWithHiddenFixture(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void,
	stepLabel: string
): Promise<void> {
	const messageField = page.getByTestId('message-field').last();
	const messageEditor = messageField.getByTestId('message-editor');
	await expect(messageEditor).toBeVisible({ timeout: 10000 });
	await fillMessageEditor(page, messageEditor, VISIBLE_PROOF_QUESTION);
	await expect(messageEditor).toContainText(VISIBLE_PROOF_QUESTION, { timeout: 5000 });
	logCheckpoint(`Typed visible proof question: "${VISIBLE_PROOF_QUESTION}"`);

	await messageEditor.evaluate((editor: HTMLElement, serverContent: string) => {
		editor.dispatchEvent(
			new CustomEvent('custom-send-message', {
				bubbles: true,
				detail: { testMockMarker: serverContent }
			})
		);
	}, withMockMarker(VISIBLE_PROOF_QUESTION, 'default_model_mistral'));
	logCheckpoint(`Sent visible proof question with hidden fixture marker for ${stepLabel}.`);
}

async function ensureAutoSelectOn(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void
): Promise<void> {
	const aiSettings = page.getByTestId('settings-menu').getByTestId('ai-settings');
	const autoSelectRow = aiSettings.getByTestId('setting-row').first();
	await expect(autoSelectRow).toBeVisible({ timeout: 5000 });

	const toggleInput = autoSelectRow.locator('input[type="checkbox"]');
	const isAutoOn = await toggleInput.evaluate((el: HTMLInputElement) => el.checked);
	if (isAutoOn) {
		logCheckpoint('Auto-select is already ON.');
		return;
	}

	await autoSelectRow.locator('[role="button"]').first().click();
	logCheckpoint('Toggled auto-select ON.');
	const notification = modelChangeNotifications(page).first();
	await expect(notification).toBeVisible({ timeout: 5000 });
	await expect(aiSettings.locator('#default-simple-select')).not.toBeVisible({ timeout: 5000 });
	await page.waitForTimeout(1200);
}

async function setMistralAsSimpleDefault(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void
): Promise<void> {
	const aiSettings = page.getByTestId('settings-menu').getByTestId('ai-settings');
	const autoSelectRow = aiSettings.getByTestId('setting-row').first();
	await expect(autoSelectRow).toBeVisible({ timeout: 5000 });

	const toggleInput = autoSelectRow.locator('input[type="checkbox"]');
	const isAutoOn = await toggleInput.evaluate((el: HTMLInputElement) => el.checked);
	if (isAutoOn) {
		await autoSelectRow.locator('[role="button"]').first().click();
		logCheckpoint('Toggled auto-select OFF.');
	}

	const simpleDropdown = page.locator('#default-simple-select');
	await expect(simpleDropdown).toBeAttached({ timeout: 10000 });
	await simpleDropdown.scrollIntoViewIfNeeded();
	await expect(simpleDropdown).toBeVisible({ timeout: 10000 });
	await simpleDropdown.selectOption({ label: 'Mistral Small 3.2' });
	logCheckpoint('Selected Mistral Small 3.2 for Simple requests.');

	const notification = modelChangeNotification(page, MISTRAL_SELECTED_NOTIFICATION);
	await expect(notification).toBeVisible({ timeout: 5000 });
	await expect(notification).toContainText(MISTRAL_SELECTED_NOTIFICATION);
	await page.waitForTimeout(1200);
}

async function sendQuestionAndAssertMistral(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void,
	_stepLabel: string
): Promise<string | null> {
	await startNewChat(page, logCheckpoint);
	await sendProofQuestionWithHiddenFixture(page, logCheckpoint, _stepLabel);

	await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 15000 });
	const chatId = page.url().match(/chat-id=([a-zA-Z0-9-]+)/)?.[1] ?? null;
	const assistantMessage = await waitForAssistantMessage(page, {
		which: 'last',
		logCheckpoint
	});

	await expect(async () => {
		const msgText = await assistantMessage.textContent();
		expect((msgText || '').trim().length).toBeGreaterThan(5);
	}).toPass({ timeout: 60000, intervals: [2000, 3000, 5000] });

	const userMessage = page.getByTestId('message-user').last();
	await expect(userMessage).toContainText(VISIBLE_PROOF_QUESTION, { timeout: 10000 });
	await expect(userMessage).not.toContainText('<<<TEST_MOCK', { timeout: 10000 });

	const generatedByElement = assistantMessage.getByTestId('generated-by');
	await expect(generatedByElement).toBeVisible({ timeout: 90000 });
	await expect(generatedByElement).toContainText(/Mistral Small 3\.2/i);
	await expect(assistantMessage).toContainText('Berlin', { timeout: 15000 });
	logCheckpoint('Verified generated-by text and Berlin response are visible.');
	return chatId;
}

async function recordProofProfile(
	browser: any,
	baseURL: string,
	viewport: { name: string; width: number; height: number }
): Promise<void> {
	const logCheckpoint = createSignupLogger(`DEFAULT_MODEL_PROOF_${viewport.name.toUpperCase()}`);
	fs.mkdirSync(PROOF_RECORDING_DIR, { recursive: true });

	const videoPath = path.join(PROOF_RECORDING_DIR, `${viewport.name}.webm`);
	fs.rmSync(videoPath, { force: true });

	const context = await browser.newContext({
		baseURL,
		recordVideo: {
			dir: PROOF_RECORDING_DIR,
			size: { width: viewport.width, height: viewport.height }
		},
		viewport: { width: viewport.width, height: viewport.height }
	});

	const page = await context.newPage();
	attachConsoleListeners(page);
	attachNetworkListeners(page);
	const video = page.video();
	let chatCreated = false;

	try {
		await loginToTestAccount(page, logCheckpoint, noopScreenshot);

		await navigateToAiSettings(page, logCheckpoint);
		await ensureAutoSelectOn(page, logCheckpoint);
		await setMistralAsSimpleDefault(page, logCheckpoint);
		await closeSettings(page, logCheckpoint);

		chatCreated = Boolean(await sendQuestionAndAssertMistral(page, logCheckpoint, `proof-${viewport.name}`));
	} finally {
		try {
			await navigateToAiSettings(page, logCheckpoint);
			await ensureAutoSelectOn(page, logCheckpoint);
			await closeSettings(page, logCheckpoint);
		} catch (error: any) {
			console.warn(`[default-model-proof] Failed to reset auto-select for ${viewport.name}: ${error.message}`);
		}

		if (chatCreated) {
			try {
				await deleteActiveChat(page, logCheckpoint, noopScreenshot, `cleanup-${viewport.name}`);
			} catch (error: any) {
				console.warn(`[default-model-proof] Failed to delete proof chat for ${viewport.name}: ${error.message}`);
			}
		}
		await page.waitForTimeout(1000);
		await context.close();
	}

	if (!video) {
		throw new Error(`Playwright did not create a video for ${viewport.name}`);
	}
	const generatedVideoPath = await video.path();
	await video.saveAs(videoPath);
	if (generatedVideoPath !== videoPath) {
		fs.rmSync(generatedVideoPath, { force: true });
	}
}

test.describe('Default model settings proof video source', () => {
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	for (const viewport of PROOF_VIEWPORTS) {
		test(`records exact ${viewport.name} proof profile after login`, async ({ browser, baseURL }: { browser: any; baseURL: string }) => {
			test.setTimeout(PROOF_PROFILE_TIMEOUT_MS);
			fs.mkdirSync(PROOF_RECORDING_DIR, { recursive: true });
			await recordProofProfile(browser, baseURL, viewport);
		});
	}
});
