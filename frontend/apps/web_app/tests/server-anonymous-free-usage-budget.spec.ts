/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Admin Server settings Anonymous free usage budget contract.
 *
 * The spec mocks only the anonymous free usage budget endpoint so it can
 * exercise the UI without mutating the shared dev budget used by anonymous
 * chat tests.
 */

const { test, expect } = require('./helpers/cookie-audit');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	getE2EDebugUrl,
	getTestAccount
} = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

type BudgetResponse = {
	enabled: boolean;
	monthly_budget_credits: number;
	daily_hard_cap_percent: number;
	daily_hard_cap_credits: number;
	weekly_cap_percent: number;
	weekly_cap_credits: number;
	per_identity_daily_cap_credits: number;
	daily_used_credits: number;
	weekly_used_credits: number;
	monthly_used_credits: number;
	monthly_remaining_credits: number;
	daily_remaining_credits: number;
	weekly_remaining_credits: number;
	active: boolean;
	reason: string | null;
	reset_at: string;
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

function buildServerStatus(isSelfHosted: boolean) {
	return {
		is_self_hosted: isSelfHosted,
		payment_enabled: true,
		server_edition: isSelfHosted ? 'self-hosted' : 'development',
		domain: isSelfHosted ? 'localhost' : 'app.dev.openmates.org',
		ai_models_configured: true,
		anonymous_free_usage: isSelfHosted
			? null
			: {
					active: true,
					reason: null,
					reset_at: '2026-06-18T00:00:00Z',
					cta: 'Create an account to keep using OpenMates.'
				}
	};
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

async function mockServerStatus(page: any, isSelfHosted = false) {
	await page.route('**/v1/settings/server-status', async (route: any) => {
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify(buildServerStatus(isSelfHosted))
		});
	});
}

async function mockBudgetEndpoint(page: any) {
	let currentBudget: BudgetResponse = {
		enabled: false,
		monthly_budget_credits: 0,
		daily_hard_cap_percent: 5,
		daily_hard_cap_credits: 0,
		weekly_cap_percent: 25,
		weekly_cap_credits: 0,
		per_identity_daily_cap_credits: 400,
		daily_used_credits: 0,
		weekly_used_credits: 0,
		monthly_used_credits: 0,
		monthly_remaining_credits: 0,
		daily_remaining_credits: 0,
		weekly_remaining_credits: 0,
		active: false,
		reason: 'inactive',
		reset_at: '2026-06-18T00:00:00Z',
		updated_at: null
	};
	let lastPutBody: Record<string, unknown> | null = null;

	await page.route('**/v1/admin/anonymous-free-usage-budget', async (route: any) => {
		if (route.request().method() === 'PUT') {
			lastPutBody = route.request().postDataJSON();
			const monthly = Number(lastPutBody?.monthly_budget_credits ?? 0);
			const dailyPercent = Number(lastPutBody?.daily_hard_cap_percent ?? 0);
			const weeklyPercent = Number(lastPutBody?.weekly_cap_percent ?? 0);
			const dailyCap = Math.floor(monthly * dailyPercent / 100);
			const weeklyCap = Math.floor(monthly * weeklyPercent / 100);
			currentBudget = {
				enabled: Boolean(lastPutBody?.enabled),
				monthly_budget_credits: monthly,
				daily_hard_cap_percent: dailyPercent,
				daily_hard_cap_credits: dailyCap,
				weekly_cap_percent: weeklyPercent,
				weekly_cap_credits: weeklyCap,
				per_identity_daily_cap_credits: Number(lastPutBody?.per_identity_daily_cap_credits ?? 0),
				daily_used_credits: 0,
				weekly_used_credits: 0,
				monthly_used_credits: 0,
				monthly_remaining_credits: monthly,
				daily_remaining_credits: dailyCap,
				weekly_remaining_credits: weeklyCap,
				active: Boolean(lastPutBody?.enabled) && dailyCap > 0 && weeklyCap > 0,
				reason: Boolean(lastPutBody?.enabled) && dailyCap > 0 && weeklyCap > 0 ? null : 'inactive',
				reset_at: '2026-06-18T00:00:00Z',
				updated_at: '2026-06-17T09:30:00Z'
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

async function openSettingsPath(page: any, settingsPath: string) {
	await page.goto(getE2EDebugUrl(`/#settings/${settingsPath}`), { waitUntil: 'domcontentloaded' });
	const settingsMenu = page.getByTestId('settings-menu');
	await expect(settingsMenu).toBeVisible({ timeout: 10000 });
	await expect(settingsMenu).toHaveAttribute('data-active-view', settingsPath.replaceAll('-', '_'), { timeout: 10000 });
}

test('admin can view and save anonymous free usage budget settings', async ({ page }: { page: any }) => {
	test.slow();
	test.setTimeout(180000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const log = createSignupLogger('SERVER_ANONYMOUS_FREE_USAGE_BUDGET');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'server-anonymous-free-usage-budget' });
	await archiveExistingScreenshots(log);

	await forceSessionAdminFlag(page, true);
	await mockServerStatus(page, false);
	const budgetApi = await mockBudgetEndpoint(page);
	await loginToTestAccount(page, log, screenshot, { waitForEditor: true });
	await openSettingsPath(page, 'server/anonymous-free-usage');
	await expect(page.getByText('Anonymous free usage', { exact: true })).toBeVisible({ timeout: 10000 });
	await expect(page.getByTestId('anonymous-free-usage-budget-settings')).toBeVisible({ timeout: 10000 });
	await expect(page.getByText('Anonymous free usage is currently inactive.')).toBeVisible();

	await expect(page.getByRole('checkbox', { name: /enable anonymous free usage/i })).toHaveCount(0);
	await page.getByTestId('anonymous-free-usage-monthly-budget-input').fill('60000');
	await page.getByTestId('anonymous-free-usage-daily-percent-input').fill('5');
	await page.getByTestId('anonymous-free-usage-weekly-percent-input').fill('25');
	await page.getByTestId('anonymous-free-usage-per-identity-cap-input').fill('0');
	await expect(
		page.getByText('Per-identity daily cap must be at least 1 credit when the monthly budget is above 0.')
	).toBeVisible();
	await expect(page.getByTestId('anonymous-free-usage-budget-save-button')).toBeDisabled();
	await page.getByTestId('anonymous-free-usage-per-identity-cap-input').fill('400');
	await expect(
		page.getByText('Per-identity daily cap must be at least 1 credit when the monthly budget is above 0.')
	).toHaveCount(0);
	await expect(page.getByText('3,000')).toBeVisible();
	await expect(page.getByText('15,000')).toBeVisible();
	await page.getByTestId('anonymous-free-usage-budget-save-button').click();

	await expect(page.getByText('Anonymous free usage is active for new logged-out users.')).toBeVisible({ timeout: 10000 });
	await expect(page.getByTestId('anonymous-free-usage-budget-settings').getByText('3,000').first()).toBeVisible();
	await expect(page.getByTestId('anonymous-free-usage-budget-settings').getByText('15,000').first()).toBeVisible();
	await expect(page.getByTestId('anonymous-free-usage-budget-settings').getByText('60,000').first()).toBeVisible();
	expect(budgetApi.getLastPutBody()).toMatchObject({
		enabled: true,
		monthly_budget_credits: 60000,
		daily_hard_cap_percent: 5,
		weekly_cap_percent: 25,
		per_identity_daily_cap_credits: 400
	});
});

test('self-hosted server settings hide anonymous free usage settings', async ({ page }: { page: any }) => {
	test.slow();
	test.setTimeout(180000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const log = createSignupLogger('SERVER_ANONYMOUS_FREE_USAGE_SELF_HOST');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'server-anonymous-free-usage-self-host' });
	await archiveExistingScreenshots(log);

	await forceSessionAdminFlag(page, true);
	await mockServerStatus(page, true);
	await loginToTestAccount(page, log, screenshot, { waitForEditor: true });
	await openSettingsPath(page, 'server');
	await expect(page.getByText('Anonymous free usage', { exact: true })).toHaveCount(0);
});
