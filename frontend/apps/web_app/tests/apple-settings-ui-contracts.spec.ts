/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Captures sanitized rendered settings contracts for Apple parity.
 * Uses the authenticated product UI at the compact phone viewport and records
 * root header expansion plus one representative destination header.
 * Runtime artifacts are promoted with scripts/apple_ui_contracts.py.
 * Spec source: docs/specs/apple-settings-billing-parity/spec.yml
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const {
	captureContractState,
	createContract,
	writeContractArtifact
} = require('./helpers/apple-ui-contract-helpers');

const COMPACT_VIEWPORT = { width: 390, height: 844 };
const ROOT_ELEMENTS = [
	{ testId: 'settings-menu', semanticId: 'authenticated-settings-root' },
	{ testId: 'settings-banner-shell', semanticId: 'settings-root-header' },
	{ testId: 'icon-button-close', semanticId: 'settings-close-button' },
	{ testId: 'credits-row', semanticId: 'settings-credits-row' },
	{ testId: 'incognito-toggle-wrapper', semanticId: 'settings-incognito-row' },
	{ testId: 'learning-mode-toggle-wrapper', semanticId: 'settings-learning-mode-row' }
];
const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

test.use({ viewport: COMPACT_VIEWPORT });

async function openAuthenticatedSettingsRoot(page: any): Promise<void> {
	await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
	const profileButton = page.getByTestId('profile-picture').first();
	await expect(profileButton).toBeVisible({ timeout: 20000 });
	await profileButton.click();

	const settingsMenu = page.getByTestId('settings-menu');
	await expect(settingsMenu).toBeVisible({ timeout: 20000 });
	await expect(settingsMenu).toHaveAttribute('data-active-view', 'main');
	await expect(page.getByTestId('settings-banner-shell')).toBeVisible();
}

test('captures compact authenticated settings headers for Apple parity', async ({ page }) => {
	test.setTimeout(120000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	await loginToTestAccount(page);
	await openAuthenticatedSettingsRoot(page);

	const states = [];
	states.push(await captureContractState(page, {
		id: 'authenticated-root-expanded',
		description: 'Authenticated compact settings root with the profile header fully expanded.',
		elements: ROOT_ELEMENTS
	}));

	const settingsMenu = page.getByTestId('settings-menu');
	await settingsMenu.hover({ position: { x: 160, y: 600 } });
	await page.mouse.wheel(0, 600);
	await expect(page.getByTestId('credits-row')).toHaveClass(/credits-row-collapsed/);
	states.push(await captureContractState(page, {
		id: 'authenticated-root-collapsed',
		description: 'Authenticated compact settings root after scrolling collapses the profile header.',
		elements: ROOT_ELEMENTS
	}));

	await page.goto(getE2EDebugUrl('/#settings/account'), { waitUntil: 'domcontentloaded' });
	await expect(settingsMenu).toBeVisible({ timeout: 20000 });
	await expect(settingsMenu).toHaveAttribute('data-active-view', 'account');
	await expect(page.getByTestId('settings-banner-shell')).toBeVisible();
	states.push(await captureContractState(page, {
		id: 'account-destination-header',
		description: 'Representative authenticated Account destination with its compact settings header.',
		elements: [
			{ testId: 'settings-menu', semanticId: 'account-settings-destination' },
			{ testId: 'settings-banner-shell', semanticId: 'settings-destination-header' },
			{ testId: 'icon-button-close', semanticId: 'settings-close-button' }
		]
	}));

	const contract = createContract('settings', COMPACT_VIEWPORT, states);
	const outputPath = writeContractArtifact(contract, 'settings.generated.json');
	expect(contract.states).toHaveLength(3);
	expect(outputPath).toContain('settings.generated.json');
});
