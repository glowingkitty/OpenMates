/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/** Dev-only, one-payment Stripe sandbox proof. Never dispatch this spec to CI. */
export {};
import { randomUUID } from 'node:crypto';
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import type { Page, Response } from '@playwright/test';

const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { fillStripeCardDetails, getE2EDebugUrl, getTestAccount, setToggleChecked } = require('./signup-flow-helpers');

const BASE_URL = process.env.PLAYWRIGHT_TEST_BASE_URL || '';
const API_URL = process.env.PLAYWRIGHT_TEST_API_URL || 'https://api.dev.openmates.org';
const EVIDENCE_DIR = resolve(process.env.OPENMATES_TEAM_STRIPE_EVIDENCE_DIR || 'test-results/teams-upload-followup-2026-10-10/billing');

function requireDevSandbox(): void {
	if (process.env.CI || process.env.GITHUB_ACTIONS || process.env.OPENMATES_CI_ISOLATED === '1')
		throw new Error('Real Stripe provider proof is restricted to coordinated dev.');
	if (process.env.OPENMATES_TEAM_STRIPE_DEV_PROOF !== '1' || process.env.E2E_USE_MOCKS || process.env.E2E_USE_LIVE_MOCKS)
		throw new Error('Explicit dev proof flag and disabled mocks are required.');
	if (!new URL(BASE_URL).hostname.endsWith('.dev.openmates.org') || !new URL(API_URL).hostname.endsWith('.dev.openmates.org'))
		throw new Error('Both browser and API targets must be dev hosts.');
	if (!getTestAccount().email || !getTestAccount().password || !getTestAccount().otpKey)
		throw new Error('A leased provisioned dev test account with TOTP is required.');
}

async function teamBalance(page: Page, teamId: string): Promise<number> {
	const response = await page.request.get(`${API_URL}/v1/teams/${encodeURIComponent(teamId)}/billing`);
	expect(response.ok()).toBe(true);
	const value = Number((await response.json()).billing?.balance_credits);
	expect(Number.isSafeInteger(value)).toBe(true);
	return value;
}

async function personalBalance(page: Page): Promise<number> {
	const response = await page.request.get(`${API_URL}/v1/settings/delete-account-preview`);
	expect(response.ok()).toBe(true);
	const value = Number((await response.json()).total_credits);
	expect(Number.isSafeInteger(value)).toBe(true);
	return value;
}

// contract-test: direct surface=gui.web assertions=billing.purchase.provider-routing,billing.credits.idempotent-charge,billing.documents.visible-downloadable,teams.chat-billing.team-credit-boundary
test('one Team Stripe sandbox card purchase settles once and produces a Team invoice', async ({ page }: { page: Page }) => {
	test.setTimeout(420_000);
	requireDevSandbox();
	const accountSlot = process.env.OPENMATES_TEST_ACCOUNT_SOURCE_SLOT || 'unknown';
	const proofId = randomUUID();
	const receipt: Record<string, unknown> = { proof_id: proofId, account_slot: accountSlot, target: API_URL, stage: 'preflight' };
	await mkdir(EVIDENCE_DIR, { recursive: true });
	const persist = async () => writeFile(resolve(EVIDENCE_DIR, `team-stripe-${proofId}.json`), JSON.stringify(receipt, null, 2));
	try {
		const configResponse = await page.request.get(`${API_URL}/v1/payments/config?provider_override=stripe`);
		expect(configResponse.ok()).toBe(true);
		const config = await configResponse.json();
		expect(config.provider).toBe('stripe');
		expect(config.environment).toBe('sandbox');
		expect(String(config.public_key).startsWith('pk_test_')).toBe(true);
		receipt.stage = 'test_key_confirmed';
		await persist();

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page);
		await page.getByTestId('profile-container').click();
		await page.getByTestId('settings-teams-item').click();
		await expect(page.getByTestId('teams-settings-page')).toBeVisible();
		await page.getByTestId('team-create-open').click();
		await page.getByTestId('team-name-input').fill(`Stripe sandbox proof ${proofId.slice(0, 8)}`);
		await page.getByTestId('team-create-continue').click();
		await expect(page.getByTestId('team-avatar-preview')).toBeVisible();
		const created = page.waitForResponse((response: Response) =>
			response.request().method() === 'POST' && new URL(response.url()).pathname === '/v1/teams' && response.ok());
		await page.getByTestId('team-create-submit').click();
		const teamId = String((await (await created).json()).team?.team_id || '');
		expect(teamId).toBeTruthy();
		receipt.team_id = teamId;
		receipt.stage = 'team_created';
		await persist();

		const beforeTeam = await teamBalance(page, teamId);
		const beforePersonal = await personalBalance(page);
		expect(beforeTeam).toBe(0);
		receipt.before = { team: beforeTeam, personal: beforePersonal };
		await page.getByTestId('team-billing-open').click();
		await expect(page.getByTestId('team-billing-buy-credits')).toBeVisible();
		await page.getByTestId('team-billing-buy-credits').click();
		const tier = page.locator('[data-testid="settings-menu"].visible [data-testid="menu-item"][role="menuitem"]')
			.filter({ hasText: /credits/i }).first();
		await expect(tier).toBeVisible();
		await expect(tier).toContainText(/1[.,]?000\s+credits/i);
		const orderResponse = page.waitForResponse((response: Response) =>
			response.request().method() === 'POST' &&
			new URL(response.url()).pathname === `/v1/teams/${encodeURIComponent(teamId)}/billing/card-orders`);
		await tier.click();
		const order = await orderResponse;
		expect(order.ok()).toBe(true);
		const orderBody = await order.json();
		const orderId = String(orderBody.order_id || '');
		expect(orderId).toBeTruthy();
		receipt.order_id = orderId;
		receipt.stage = 'card_order_created';
		await persist();

		const addCard = page.getByTestId('add-payment-method');
		if (await addCard.isVisible({ timeout: 3000 }).catch(() => false)) await addCard.click();
		const switchToEu = page.getByTestId('switch-to-stripe');
		if (await switchToEu.isVisible({ timeout: 3000 }).catch(() => false)) await switchToEu.click();
		const consent = page.locator('#limited-refund-consent-toggle');
		if (await consent.isVisible({ timeout: 3000 }).catch(() => false)) await setToggleChecked(consent, true);
		await expect(page.locator('iframe[title="Secure payment input frame"]')).toBeAttached({ timeout: 30_000 });
		// Existing EU checkout proof uses a Finnish test card because the EU Radar rule blocks US-issued cards.
		await fillStripeCardDetails(page, '4000002460000001');
		const submit = page.locator('button[type="submit"].buy-button, button[type="submit"]:has-text("Buy for"), button[type="submit"]:has-text("Pay")').first();
		await expect(submit).toBeEnabled();
		receipt.stage = 'payment_submission_started';
		await persist();
		await submit.click();

		await expect.poll(async () => {
			const response = await page.request.get(`${API_URL}/v1/teams/${encodeURIComponent(teamId)}/billing/card-orders/${encodeURIComponent(orderId)}`);
			return response.ok() ? (await response.json()).state : `HTTP ${response.status()}`;
		}, { timeout: 120_000, intervals: [1000, 2000, 5000] }).toBe('COMPLETED');
		receipt.stage = 'provider_settled';
		await persist();

		const firstBalance = await teamBalance(page, teamId);
		expect(firstBalance).toBe(beforeTeam + 1000);
		expect(await personalBalance(page)).toBe(beforePersonal);
		const invoicesUrl = `${API_URL}/v1/teams/${encodeURIComponent(teamId)}/billing/invoices`;
		let invoice: Record<string, unknown> | undefined;
		await expect.poll(async () => {
			const response = await page.request.get(invoicesUrl);
			if (!response.ok()) return `HTTP ${response.status()}`;
			invoice = (await response.json()).invoices?.find((row: Record<string, unknown>) => row.order_id === orderId);
			return invoice?.document_status;
		}, { timeout: 120_000, intervals: [1000, 2000, 5000] }).toBe('ready');
		const pdf = await page.request.get(`${invoicesUrl}/${encodeURIComponent(String(invoice!.id))}/download`);
		expect(pdf.ok()).toBe(true);
		expect(pdf.headers()['content-type']).toContain('application/pdf');
		expect((await pdf.body()).subarray(0, 4).toString()).toBe('%PDF');
		await page.reload({ waitUntil: 'domcontentloaded' });
		expect(await teamBalance(page, teamId)).toBe(firstBalance);
		expect(await personalBalance(page)).toBe(beforePersonal);
		const invoices = (await (await page.request.get(invoicesUrl)).json()).invoices;
		expect(invoices.filter((row: Record<string, unknown>) => row.order_id === orderId)).toHaveLength(1);
		receipt.after = { team: firstBalance, personal: beforePersonal, invoice_ready: true, pdf_downloaded: true };
		receipt.stage = 'complete';
		await persist();
	} catch (error) {
		receipt.failure = error instanceof Error ? error.message.slice(0, 250) : 'unknown';
		await persist();
		throw error;
	}
});
