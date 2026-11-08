/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Learning Mode settings E2E tests.
 *
 * Account: backend-backed account-wide Learning Mode quick setting: login, open
 * settings, check the "Allow collaborative building" toggle (default on, hidden
 * for under 10), activate with age group/passcode, turn collaborative off freely
 * and on again only with the passcode, then deactivate with the passcode.
 * Guest: browser-local, passcode-locked Learning Mode that persists across a
 * reload, shows the honest limits notice and gates deactivation and enabling
 * collaborative building behind the passcode. Playwright runs against the
 * deployed dev app, so this spec provides red evidence before the feature is
 * deployed and green evidence after deployment.
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
const { getE2EDebugUrl } = require('./signup-flow-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
const LEARNING_MODE_TEST_PASSCODE = 'LearningModeE2E123';
const GUEST_PASSCODE = 'GuestLearning123';

async function openSettingsPanel(page: any, logCheckpoint: (message: string) => void): Promise<void> {
	const profileButton = page.getByTestId('profile-picture').first();
	await expect(profileButton).toBeVisible({ timeout: 10000 });
	await profileButton.click();

	const settingsMenu = page.getByTestId('settings-menu');
	await expect(settingsMenu).toBeVisible({ timeout: 10000 });
	logCheckpoint('Settings menu is visible.');
}

function collaborativeRow(page: any) {
	return page.getByTestId('learning-mode-collaborative');
}

function collaborativeToggle(page: any) {
	return page.getByTestId('learning-mode-collaborative-toggle');
}

function collaborativeCheckbox(page: any) {
	return collaborativeToggle(page).getByRole('checkbox');
}

/** Setup page rules: toggle defaults on, is hidden for under 10 and returns on for older learners. */
async function expectCollaborativeToggleRules(page: any): Promise<void> {
	await expect(collaborativeRow(page)).toBeVisible({ timeout: 10000 });
	await expect(collaborativeCheckbox(page)).toBeChecked();
	await page.getByTestId('learning-mode-age-group-dropdown').selectOption('under_10');
	await expect(collaborativeRow(page)).toHaveCount(0);
	await page.getByTestId('learning-mode-age-group-dropdown').selectOption('10_12');
	await expect(collaborativeRow(page)).toBeVisible();
	await expect(collaborativeCheckbox(page)).toBeChecked();
}

async function openGuestLearningModeSetup(page: any): Promise<void> {
	await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
	await page.waitForLoadState('networkidle');
	const profileContainer = page.getByTestId('profile-container');
	await expect(profileContainer).toBeVisible({ timeout: 15000 });
	await profileContainer.click();
	const settingsMenu = page.getByTestId('settings-menu');
	await expect(settingsMenu).toBeVisible({ timeout: 10000 });
	await learningModeRow(page).click();
	await expect(settingsMenu).toHaveAttribute('data-active-view', 'learning-mode/setup', { timeout: 8000 });
	await expect(page.getByTestId('learning-mode-settings-page')).toBeVisible({ timeout: 10000 });
}

function learningModeRow(page: any) {
	return page.getByTestId('learning-mode-toggle-wrapper');
}

test.describe('Learning Mode settings', () => {
	test.describe.configure({ timeout: 120000 });
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	// contract-test: direct surface=gui.web assertions=learning-mode.collaborative-toggle
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
		await expectCollaborativeToggleRules(page);
		await page.getByTestId('learning-mode-age-group-dropdown').selectOption('13_15');
		await page.getByTestId('learning-mode-passcode-input').fill(LEARNING_MODE_TEST_PASSCODE);
		await page.getByTestId('learning-mode-enable-button').click();
		await expect(toggle).toBeChecked({ timeout: 15000 });
		await takeStepScreenshot(page, '02-learning-mode-active');

		await row.click();
		await expect(setupPage).toBeVisible({ timeout: 10000 });
		// Collaborative building is on after activation; off is free, on needs the passcode.
		await expect(collaborativeCheckbox(page)).toBeChecked({ timeout: 10000 });
		await collaborativeToggle(page).click();
		await expect(collaborativeCheckbox(page)).not.toBeChecked({ timeout: 10000 });
		await collaborativeRow(page).click();
		await expect(page.getByTestId('learning-mode-collaborative-passcode-input')).toBeVisible({ timeout: 5000 });
		await page.getByTestId('learning-mode-collaborative-passcode-input').fill(LEARNING_MODE_TEST_PASSCODE);
		await page.getByTestId('learning-mode-collaborative-confirm-button').click();
		await expect(collaborativeCheckbox(page)).toBeChecked({ timeout: 10000 });
		await takeStepScreenshot(page, '02b-collaborative-toggled');
		await page.getByTestId('learning-mode-passcode-input').fill(LEARNING_MODE_TEST_PASSCODE);
		await page.getByTestId('learning-mode-disable-button').click();
		await expect(toggle).not.toBeChecked({ timeout: 15000 });
		await takeStepScreenshot(page, '03-learning-mode-disabled');
	});
});

test.describe('Guest Learning Mode settings', () => {
	test.describe.configure({ timeout: 120000 });

	// contract-test: direct surface=gui.web assertions=learning-mode.anonymous-client-side
	test('guest Learning Mode is passcode-locked, persists across reload and gates collaborative building', async ({
		page
	}: {
		page: any;
	}) => {
		await openGuestLearningModeSetup(page);

		// Honest limits notice and collaborative toggle rules on the setup page.
		await expect(page.getByTestId('learning-mode-guest-notice')).toBeVisible();
		await expectCollaborativeToggleRules(page);

		// Too-short passcodes are rejected without activating anything.
		await page.getByTestId('learning-mode-passcode-input').fill('abc');
		await page.getByTestId('learning-mode-enable-button').click();
		await expect(page.getByTestId('learning-mode-enable-button')).toBeVisible();

		await page.getByTestId('learning-mode-passcode-input').fill(GUEST_PASSCODE);
		await page.getByTestId('learning-mode-enable-button').click();

		// The guest record lives in localStorage and never stores the plain passcode.
		await expect
			.poll(() => page.evaluate(() => window.localStorage.getItem('openmates.learningMode.guest')), { timeout: 10000 })
			.not.toBeNull();
		const stored = await page.evaluate(() => window.localStorage.getItem('openmates.learningMode.guest'));
		expect(stored).not.toContain('GuestLearning123');
		expect(JSON.parse(stored as string)).toMatchObject({ enabled: true, age_group: '10_12', collaborative_build: true });

		// Persists after reload: Learning Mode is still on and offers the passcode-gated off switch.
		await openGuestLearningModeSetup(page);
		await expect(page.getByTestId('learning-mode-disable-button')).toBeVisible({ timeout: 10000 });
		await expect(collaborativeCheckbox(page)).toBeChecked();

		// Collaborative off is free; on again needs the passcode.
		await collaborativeToggle(page).click();
		await expect(collaborativeCheckbox(page)).not.toBeChecked({ timeout: 10000 });
		await collaborativeRow(page).click();
		await page.getByTestId('learning-mode-collaborative-passcode-input').fill('wrong-passcode');
		await page.getByTestId('learning-mode-collaborative-confirm-button').click();
		await expect(collaborativeCheckbox(page)).not.toBeChecked();
		await page.getByTestId('learning-mode-collaborative-passcode-input').fill(GUEST_PASSCODE);
		await page.getByTestId('learning-mode-collaborative-confirm-button').click();
		await expect(collaborativeCheckbox(page)).toBeChecked({ timeout: 10000 });

		// Deactivation needs the passcode: a wrong one keeps Learning Mode on.
		await page.getByTestId('learning-mode-passcode-input').fill('wrong-passcode');
		await page.getByTestId('learning-mode-disable-button').click();
		await expect(page.getByTestId('learning-mode-disable-button')).toBeVisible();
		await page.getByTestId('learning-mode-passcode-input').fill(GUEST_PASSCODE);
		await page.getByTestId('learning-mode-disable-button').click();
		await expect
			.poll(() => page.evaluate(() => JSON.parse(window.localStorage.getItem('openmates.learningMode.guest') ?? '{}').enabled), {
				timeout: 10000
			})
			.toBe(false);
		await openGuestLearningModeSetup(page);
		await expect(page.getByTestId('learning-mode-enable-button')).toBeVisible({ timeout: 10000 });
	});
});
