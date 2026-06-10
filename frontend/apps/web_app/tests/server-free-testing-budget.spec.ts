/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Admin Server settings Free testing credits budget contract.
 *
 * The spec mocks only the new admin budget endpoint so it can exercise the UI
 * without mutating the shared dev budget used by signup tests.
 */

const { test, expect } = require('./helpers/cookie-audit');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	getTestAccount
} = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

type BudgetResponse = {
	enabled: boolean;
	total_budget_credits: number;
	used_budget_credits: number;
	remaining_budget_credits: number;
	per_user_grant_credits: number;
	active: boolean;
	exhausted: boolean;
	exhausted_email_sent_at: string | null;
	updated_at: string | null;
};

function withAdminFlag(payload: any, isAdmin: boolean) {
	if (payload?.json?.user) {
		payload.json.user.is_admin = isAdmin;
	}
	if (payload?.user) {
		payload.user.is_admin = isAdmin;
	}
	return payload;
}

async function forceSessionAdminFlag(page: any, isAdmin: boolean) {
	const mutateResponse = async (route: any) => {
		const response = await route.fetch();
		const body = await response.json().catch(() => null);
		if (!body) {
			await route.fulfill({ response });
			return;
		}
		await route.fulfill({
			status: response.status(),
			contentType: 'application/json',
			body: JSON.stringify(withAdminFlag(body, isAdmin))
		});
	};

	await page.route('**/v1/auth/session', mutateResponse);
	await page.route('**/v1/auth/login', mutateResponse);
}

async function mockBudgetEndpoint(page: any) {
	let currentBudget: BudgetResponse = {
		enabled: false,
		total_budget_credits: 0,
		used_budget_credits: 0,
		remaining_budget_credits: 0,
		per_user_grant_credits: 1000,
		active: false,
		exhausted: false,
		exhausted_email_sent_at: null,
		updated_at: null
	};
	let lastPutBody: Record<string, unknown> | null = null;

	await page.route('**/v1/admin/free-testing-credits-budget', async (route: any) => {
		if (route.request().method() === 'PUT') {
			lastPutBody = route.request().postDataJSON();
			const total = Number(lastPutBody?.total_budget_credits ?? 0);
			const grant = Number(lastPutBody?.per_user_grant_credits ?? 0);
			currentBudget = {
				enabled: Boolean(lastPutBody?.enabled),
				total_budget_credits: total,
				used_budget_credits: 0,
				remaining_budget_credits: total,
				per_user_grant_credits: grant,
				active: Boolean(lastPutBody?.enabled) && total >= grant && grant > 0,
				exhausted: Boolean(lastPutBody?.enabled) && total < grant,
				exhausted_email_sent_at: null,
				updated_at: '2026-06-10T09:30:00Z'
			};
		}

		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify(currentBudget)
		});
	});

	return {
		getLastPutBody: () => lastPutBody
	};
}

async function openSettingsMenu(page: any) {
	const settingsToggle = page.locator('#settings-menu-toggle');
	await expect(settingsToggle).toBeVisible({ timeout: 10000 });
	await settingsToggle.click();
	await expect(page.getByTestId('settings-menu')).toBeVisible({ timeout: 10000 });
}

test('admin can open and save Free testing credits budget settings', async ({ page }: { page: any }) => {
	test.slow();
	test.setTimeout(180000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const log = createSignupLogger('SERVER_FREE_TESTING_BUDGET');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'server-free-testing-budget' });
	await archiveExistingScreenshots(log);

	await forceSessionAdminFlag(page, true);
	const budgetApi = await mockBudgetEndpoint(page);
	await loginToTestAccount(page, log, screenshot, { waitForEditor: true });
	await openSettingsMenu(page);

	await page.getByRole('menuitem', { name: /server/i }).click();
	await expect(page.getByText('Free testing credits', { exact: true })).toBeVisible({ timeout: 10000 });
	await page.getByText('Free testing credits', { exact: true }).click();
	await expect(page.getByTestId('free-testing-budget-settings')).toBeVisible({ timeout: 10000 });
	await expect(page.getByText('Free testing credits are currently inactive.')).toBeVisible();

	const enableToggle = page.getByRole('checkbox', { name: /enable free testing credits/i }).first();
	await enableToggle.click();
	await page.getByTestId('free-testing-total-budget-input').fill('50000');
	await page.getByTestId('free-testing-per-user-grant-input').fill('1000');
	await page.getByTestId('free-testing-budget-save-button').click();

	await expect(page.getByText('Free testing credits are active for new signups.')).toBeVisible({ timeout: 10000 });
	await expect(page.getByText('50,000')).toBeVisible();
	await expect(page.getByText('Never')).toBeVisible();
	expect(budgetApi.getLastPutBody()).toMatchObject({
		enabled: true,
		total_budget_credits: 50000,
		per_user_grant_credits: 1000
	});
});

test('non-admin users do not see the Server settings entry', async ({ page }: { page: any }) => {
	test.slow();
	test.setTimeout(180000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const log = createSignupLogger('SERVER_FREE_TESTING_NON_ADMIN');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'server-free-testing-non-admin' });
	await archiveExistingScreenshots(log);

	await forceSessionAdminFlag(page, false);
	await loginToTestAccount(page, log, screenshot, { waitForEditor: true });
	await openSettingsMenu(page);

	await expect(page.getByRole('menuitem', { name: /^server$/i })).toHaveCount(0);
});
