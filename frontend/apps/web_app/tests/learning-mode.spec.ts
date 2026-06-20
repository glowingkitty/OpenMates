/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Learning Mode settings E2E test.
 *
 * Verifies the backend-backed account-wide Learning Mode quick setting:
 * login, open settings, activate with age group/passcode prompts, persist active
 * UI state, then deactivate with the same passcode as cleanup. Playwright runs
 * against the deployed dev app, so this spec provides red evidence before the
 * feature is deployed and green evidence after deployment.
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const {
	archiveExistingScreenshots,
	createSignupLogger,
	createStepScreenshotter,
	getTestAccount
} = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
const LEARNING_MODE_TEST_PASSCODE = 'LearningModeE2E123';

async function openSettingsPanel(page: any, logCheckpoint: (message: string) => void): Promise<void> {
	const profileButton = page.getByTestId('profile-picture').first();
	await expect(profileButton).toBeVisible({ timeout: 10000 });
	await profileButton.click();

	const settingsMenu = page.getByTestId('settings-menu');
	await expect(settingsMenu).toBeVisible({ timeout: 10000 });
	logCheckpoint('Settings menu is visible.');
}

function learningModeRow(page: any) {
	return page.getByTestId('learning-mode-toggle-wrapper');
}

test.describe('Learning Mode settings', () => {
	test.describe.configure({ timeout: 120000 });
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	test('activates and deactivates account-wide Learning Mode from settings', async ({ page }: { page: any }) => {
		const logCheckpoint = createSignupLogger('LEARNING_MODE_SETTINGS');
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
			filenamePrefix: 'learning-mode-settings'
		});

		await archiveExistingScreenshots(logCheckpoint);
		await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
		await openSettingsPanel(page, logCheckpoint);
		await takeStepScreenshot(page, '01-settings-opened');

		const row = learningModeRow(page);
		await expect(row).toBeVisible({ timeout: 10000 });
		await expect(row).toContainText(/Learning/i);

		const toggle = row.getByRole('checkbox');
		await expect(toggle).toBeEnabled({ timeout: 15000 });

		if (await toggle.isChecked()) {
			await row.click();
			const cleanupPage = page.getByTestId('learning-mode-settings-page');
			await expect(cleanupPage).toBeVisible({ timeout: 10000 });
			await page.getByTestId('learning-mode-passcode-input').fill(LEARNING_MODE_TEST_PASSCODE);
			await page.getByTestId('learning-mode-disable-button').click();
			try {
				await expect(toggle).not.toBeChecked({ timeout: 10000 });
			} catch {
				test.skip(true, 'Learning Mode is already active with an unknown passcode; skipping to avoid lockout.');
			}
		}

		await row.click();
		const setupPage = page.getByTestId('learning-mode-settings-page');
		await expect(setupPage).toBeVisible({ timeout: 10000 });
		await page.getByTestId('learning-mode-age-group-dropdown').selectOption('13_15');
		await page.getByTestId('learning-mode-passcode-input').fill(LEARNING_MODE_TEST_PASSCODE);
		await page.getByTestId('learning-mode-enable-button').click();
		await expect(toggle).toBeChecked({ timeout: 15000 });
		await takeStepScreenshot(page, '02-learning-mode-active');

		await row.click();
		await expect(setupPage).toBeVisible({ timeout: 10000 });
		await page.getByTestId('learning-mode-passcode-input').fill(LEARNING_MODE_TEST_PASSCODE);
		await page.getByTestId('learning-mode-disable-button').click();
		await expect(toggle).not.toBeChecked({ timeout: 15000 });
		await takeStepScreenshot(page, '03-learning-mode-disabled');
	});
});
