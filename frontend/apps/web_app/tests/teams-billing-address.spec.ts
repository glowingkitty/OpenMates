/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
export {};
import { randomUUID } from 'node:crypto';
import { readFileSync } from 'node:fs';
import type { Page, Response, TestInfo } from '@playwright/test';
import { waitForSettingsView } from './helpers/settings-readiness';
import {
	cleanupTeamUsage,
	extractUsagePdfText,
	personalBalanceDigest,
	seedTeamUsage,
	type UsageItem
} from './helpers/team-usage-fixture';

const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

test.describe('Team billing address boundary', () => {
	// contract-test: direct surface=gui.web assertions=teams.chat-billing.team-credit-boundary,billing.documents.visible-downloadable,billing.access.authenticated-first-party
	test('owner saves an optional Team invoice address without touching Personal billing', async ({
		page
	}: {
		page: Page;
	}) => {
		test.setTimeout(180000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:teams']);

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page);
		await page.getByTestId('profile-container').click();
		await page.getByTestId('settings-teams-item').click();
		await expect(page.getByTestId('teams-settings-page')).toBeVisible({ timeout: 30000 });

		const teamName = `Billing proof ${Date.now()}`;
		await page.getByTestId('team-create-open').click();
		await page.getByTestId('team-name-input').fill(teamName);
		await page.getByTestId('team-create-continue').click();
		await expect(page.getByTestId('team-avatar-preview')).toBeVisible({ timeout: 30000 });
		await page.getByTestId('team-create-submit').click();
		await expect(page.getByTestId('team-settings-header')).toContainText(teamName, {
			timeout: 30000
		});

		const personalBillingRequests: string[] = [];
		page.on('request', (request) => {
			const path = new URL(request.url()).pathname;
			if (
				path.startsWith('/v1/payments/buyer-address') ||
				path.startsWith('/v1/payments/invoices') ||
				path.startsWith('/v1/payments/create-order') ||
				path.startsWith('/v1/payments/create-bank-transfer-order')
			) {
				personalBillingRequests.push(`${request.method()} ${path}`);
			}
		});

		await page.getByTestId('team-billing-open').click();
		await expect(page.getByTestId('team-billing-page')).toBeVisible({ timeout: 30000 });
		await expect(page.getByTestId('team-billing-address')).toBeVisible({ timeout: 30000 });
		await page.getByTestId('team-billing-address').click();
		await expect(page.getByTestId('billing-address-form')).toBeVisible({ timeout: 30000 });
		await page.getByTestId('billing-address-name').fill('Example Team GmbH');
		await page.getByTestId('billing-address-street').fill('Main Street 1');
		await page.getByTestId('billing-address-postal-code').fill('10115');
		await page.getByTestId('billing-address-city').fill('Berlin');
		await page.getByTestId('billing-address-country').fill('DE');
		const saved = page.waitForResponse(
			(response) =>
				response.request().method() === 'PUT' &&
				/\/v1\/teams\/[^/]+\/billing\/buyer-address$/.test(new URL(response.url()).pathname)
		);
		await page.getByTestId('billing-address-save').click();
		expect((await saved).ok()).toBe(true);
		await expect(page.getByTestId('billing-address-saved')).toBeVisible();

		let bankPayload: Record<string, unknown> | null = null;
		await page.route('**/v1/teams/*/billing/bank-transfer-orders', async (route) => {
			bankPayload = JSON.parse(route.request().postData() ?? '{}');
			await route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({
					order_id: 'bt_team_billing_proof',
					reference: 'OM-TEAM-PROOF',
					iban: 'DE02100100109307118603',
					bic: 'PBNKDEFF',
					bank_name: 'Proof Bank',
					account_holder_name: 'OpenMates',
					amount_eur: '100.00',
					credits_amount: 110000,
					expires_at: new Date(Date.now() + 86400000).toISOString()
				})
			});
		});
		await page.getByTestId('banner-back-button').click();
		await expect(page.getByTestId('team-billing-buy-credits')).toBeVisible();
		await page.getByTestId('team-billing-buy-credits').click();
		await page
			.locator('[data-testid="settings-menu"].visible [data-testid="menu-item"][role="menuitem"]')
			.filter({ hasText: /110.*credits|110\.000/i })
			.click();
		await expect(page.getByTestId('bank-transfer-details')).toBeVisible({ timeout: 30000 });
		expect(bankPayload).toMatchObject({
			credits_amount: 110000,
			buyer_address: { name: 'Example Team GmbH', street_line_1: 'Main Street 1', country: 'DE' }
		});
		expect(personalBillingRequests).toEqual([]);
	});

	// contract-test: direct surface=gui.web assertions=teams.billing.context-parity,teams.context.full-switch-local
	test('Team usage and exports show only the selected Team ledger across context switches', async ({
		page
	}: {
		page: Page;
	}, testInfo: TestInfo) => {
		test.setTimeout(300000);
		test.skip(
			process.env.GITHUB_ACTIONS !== 'true' ||
				process.env.RUNNER_ENVIRONMENT !== 'github-hosted' ||
				process.env.CI_TEST_MODE !== 'e2e',
			'Requires the disposable isolated GitHub E2E stack'
		);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:teams']);

		const syncErrors: string[] = [];
		page.on('console', (message) => {
			if (message.type() === 'error' && message.text().includes('Error during startPhasedSync')) {
				syncErrors.push(message.text());
			}
		});
		const suffix = randomUUID().slice(0, 8);
		const teams: Array<{
			id: string;
			name: string;
			ownerId: string;
			apiUrl: string;
			items: UsageItem[];
			seeded: boolean;
		}> = [];
		let originalPersonalBalance = '';
		let primaryError: unknown;
		const cleanupErrors: unknown[] = [];

		async function createDisposableTeam(name: string, items: UsageItem[]): Promise<(typeof teams)[number]> {
			const created = page.waitForResponse(
				(response: Response) =>
					response.request().method() === 'POST' &&
					new URL(response.url()).pathname === '/v1/teams' &&
					response.ok()
			);
			await page.getByTestId('team-create-open').click();
			await page.getByTestId('team-name-input').fill(name);
			await page.getByTestId('team-create-continue').click();
			await expect(page.getByTestId('team-avatar-preview')).toBeVisible({ timeout: 30000 });
			await page.getByTestId('team-create-submit').click();
			const response = await created;
			const id = String((await response.json()).team?.team_id ?? '');
			expect(id).toBeTruthy();
			const apiUrl = new URL(`/v1/teams/${encodeURIComponent(id)}`, response.url()).toString();
			const record = { id, name, ownerId: '', apiUrl, items, seeded: false };
			teams.push(record);
			await waitForSettingsView(page, testInfo, `teams/${id}`, 'teams-settings-detail');
			await expect(page.getByTestId('team-settings-header')).toContainText(name);
			const members = await page.request.get(`${apiUrl}/members`);
			expect(members.ok()).toBe(true);
			const owner = ((await members.json()).members as Array<{ role: string; user_id: string }>).find(
				(member) => member.role === 'owner'
			);
			expect(owner?.user_id).toBeTruthy();
			record.ownerId = owner!.user_id;
			const balanceBefore = seedTeamUsage(id, record.ownerId, items);
			record.seeded = true;
			if (!originalPersonalBalance) originalPersonalBalance = balanceBefore;
			else expect(balanceBefore).toBe(originalPersonalBalance);
			return record;
		}

		async function expectTeamUsage(
			team: (typeof teams)[number],
			expectedCredits: number,
			foreign: (typeof teams)[number]
		): Promise<void> {
			const usagePath = `/v1/teams/${encodeURIComponent(team.id)}/billing/usage`;
			const usageResponse = page.waitForResponse(
				(response: Response) =>
					response.request().method() === 'GET' &&
					new URL(response.url()).pathname === usagePath &&
					response.ok()
			);
			await page.getByTestId('team-billing-open').click();
			const usage = (await (await usageResponse).json()).usage as Array<{
				event_id: string;
				credit_amount: number;
			}>;
			expect(usage.map((entry) => entry.event_id).sort()).toEqual(
				team.items.map((item) => item.eventId).sort()
			);
			expect(usage.reduce((sum, entry) => sum + entry.credit_amount, 0)).toBe(expectedCredits);
			await waitForSettingsView(page, testInfo, `teams/${team.id}/billing`, 'team-usage-ledger');
			await expect(page.getByTestId('team-usage-day-heading')).toContainText(
				String(expectedCredits)
			);
			await expect(page.getByTestId('team-usage-workspace')).toHaveCount(team.items.length);
			const dayHeading = page.getByTestId('team-usage-day-heading').first();
			await dayHeading.scrollIntoViewIfNeeded();
			await expect(dayHeading).toBeVisible();
			await testInfo.attach(`selected-team-usage-${expectedCredits}-credits`, {
				body: await page.screenshot(),
				contentType: 'image/png'
			});
			const csvPath = `${usagePath}/export`;
			const csvResponse = page.waitForResponse(
				(response: Response) =>
					new URL(response.url()).pathname === csvPath &&
					new URL(response.url()).searchParams.get('format') === 'csv' &&
					response.ok()
			);
			await page.getByTestId('team-usage-download').click();
			const csvDownload = page.waitForEvent('download');
			await page.getByTestId('team-usage-csv').click();
			expect((await csvResponse).headers()['content-type']).toContain('text/csv');
			const csvPathOnDisk = await (await csvDownload).path();
			expect(csvPathOnDisk).toBeTruthy();
			await waitForSettingsView(page, testInfo, `teams/${team.id}/billing`, 'team-usage-ledger');
			const csv = readFileSync(csvPathOnDisk!, 'utf8');
			expect(csv).toContain('workspace_type,object_id_hash,credit_amount,event_id');
			for (const item of team.items) {
				expect(csv).toContain(`,${item.workspaceType},`);
				expect(csv).toContain(`,${item.credits},${item.eventId}`);
			}
			for (const item of foreign.items) expect(csv).not.toContain(item.eventId);
		}

		try {
			await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
			await loginToTestAccount(page);
			await page.getByTestId('profile-container').click();
			await page.getByTestId('settings-teams-item').click();
			await expect(page.getByTestId('team-create-open')).toBeVisible({ timeout: 30000 });

			const first = await createDisposableTeam(`Usage studio ${suffix}`, [
				{ eventId: `team-usage-e2e-${randomUUID()}`, workspaceType: 'chat', credits: 12 },
				{ eventId: `team-usage-e2e-${randomUUID()}`, workspaceType: 'app', credits: 8 },
				{ eventId: `team-usage-e2e-${randomUUID()}`, workspaceType: 'workflow', credits: 5 }
			]);
			await page.getByTestId('banner-back-button').click();
			await waitForSettingsView(page, testInfo, 'teams', 'team-create-open');
			const second = await createDisposableTeam(`Other studio ${suffix}`, [
				{ eventId: `team-usage-e2e-${randomUUID()}`, workspaceType: 'project', credits: 19 }
			]);
			await expectTeamUsage(second, 19, first);
			await page.getByTestId('team-usage-tab-chats').click();
			await expect(page.getByTestId('team-usage-empty')).toBeVisible();
			await page.getByTestId('team-usage-tab-work').click();
			await expect(page.getByTestId('team-usage-day-heading')).toContainText('19');
			await page.getByTestId('banner-back-button').click();
			await page.getByTestId('banner-back-button').click();
			await waitForSettingsView(page, testInfo, 'teams', 'team-create-open');
			await page.getByTestId('team-settings-team-row').filter({ hasText: first.name }).first().click();
			await waitForSettingsView(page, testInfo, `teams/${first.id}`, 'teams-settings-detail');
			await expectTeamUsage(first, 25, second);
			for (const [tab, credits] of [
				['chats', 12],
				['apps', 8],
				['work', 5]
			] as const) {
				await page.getByTestId(`team-usage-tab-${tab}`).click();
				await expect(page.getByTestId('team-usage-day-heading')).toContainText(String(credits));
			}
			await page.getByTestId('team-usage-tab-overview').click();
			if (!(await page.getByTestId('team-usage-pdf').isVisible())) {
				await page.getByTestId('team-usage-download').click();
			}
			const pdfResponse = page.waitForResponse(
				(response: Response) =>
					new URL(response.url()).pathname === `/v1/teams/${encodeURIComponent(first.id)}/billing/usage/export` &&
					new URL(response.url()).searchParams.get('format') === 'pdf' &&
					response.ok()
			);
			const pdfDownload = page.waitForEvent('download');
			await page.getByTestId('team-usage-pdf').click();
			expect((await pdfResponse).headers()['content-type']).toContain('application/pdf');
			const pdfPath = await (await pdfDownload).path();
			expect(pdfPath).toBeTruthy();
			await waitForSettingsView(page, testInfo, `teams/${first.id}/billing`, 'team-usage-ledger');
			const pdfBytes = readFileSync(pdfPath!);
			expect(pdfBytes.subarray(0, 5).toString()).toBe('%PDF-');
			const pdfText = extractUsagePdfText(pdfBytes);
			expect(pdfText).toContain('Team credit usage');
			for (const item of first.items) {
				expect(pdfText).toMatch(
					new RegExp(`${item.workspaceType}\\s*\\|\\s*${item.credits}\\s*\\|`)
				);
			}
			expect(pdfText).not.toContain('project');

			await page.getByTestId('banner-back-button').click();
			await page.getByTestId('banner-back-button').click();
			await page.getByTestId('banner-back-button').click();
			await waitForSettingsView(page, testInfo, 'main', 'team-context-dropdown');
			await page.getByTestId('team-context-dropdown').click();
			await page.getByTestId(`team-context-option-${first.id}`).click();
			await expect(page.getByTestId('team-context-dropdown')).toContainText(first.name);
			await page.getByTestId('team-context-dropdown').click();
			await page.getByTestId('team-context-personal').click();
			await expect(page.getByTestId('team-context-dropdown')).toContainText(/personal/i);
			await expect(page.getByTestId('profile-open-active-team-avatar')).toHaveCount(0);
			const teamBillingRequestsWhilePersonal: string[] = [];
			const onPersonalRequest = (request: { url(): string }) => {
				const pathname = new URL(request.url()).pathname;
				if (/^\/v1\/teams\/[^/]+\/billing(?:\/|$)/.test(pathname)) {
					teamBillingRequestsWhilePersonal.push(pathname);
				}
			};
			page.on('request', onPersonalRequest);
			const personalUsage = await page.request.get(
				new URL('/v1/settings/usage', first.apiUrl).toString()
			);
			expect(personalUsage.ok()).toBe(true);
			const personalUsageBody = await personalUsage.text();
			for (const team of teams) {
				for (const item of team.items) expect(personalUsageBody).not.toContain(item.eventId);
			}
			expect(teamBillingRequestsWhilePersonal).toEqual([]);
			page.off('request', onPersonalRequest);
			await page.getByTestId('team-context-dropdown').click();
			await page.getByTestId(`team-context-option-${second.id}`).click();
			await expect(page.getByTestId('team-context-dropdown')).toContainText(second.name);
			expect(personalBalanceDigest(first.ownerId)).toBe(originalPersonalBalance);
			await page.getByTestId('settings-teams-item').click();
			await waitForSettingsView(page, testInfo, 'teams', 'team-create-open');
			await page.getByTestId('team-settings-team-row').filter({ hasText: second.name }).first().click();
			await waitForSettingsView(page, testInfo, `teams/${second.id}`, 'teams-settings-detail');
			await expectTeamUsage(second, 19, first);

			const personalBillingRequests: string[] = [];
			const onBillingDeepLinkRequest = (request: { url(): string }) => {
				const pathname = new URL(request.url()).pathname;
				if (pathname.startsWith('/v1/payments/') || pathname.startsWith('/v1/settings/usage')) {
					personalBillingRequests.push(pathname);
				}
			};
			page.on('request', onBillingDeepLinkRequest);
			const invoiceResponse = page.waitForResponse(
				(response: Response) =>
					response.request().method() === 'GET' &&
					new URL(response.url()).pathname === `/v1/teams/${encodeURIComponent(second.id)}/billing/invoices` &&
					response.ok()
			);
			await page.evaluate(() => { window.location.hash = '#settings/billing/invoices'; });
			const invoices = (await (await invoiceResponse).json()).invoices;
			expect(invoices).toEqual([]);
			await waitForSettingsView(page, testInfo, `teams/${second.id}/billing/invoices`, 'team-billing-page');
			await expect(page.getByTestId('team-settings-header')).toContainText(/invoices/i);
			await expect(page.getByTestId('billing-address-page')).toHaveCount(0);

			const addressResponse = page.waitForResponse(
				(response: Response) =>
					response.request().method() === 'GET' &&
					new URL(response.url()).pathname === `/v1/teams/${encodeURIComponent(second.id)}/billing/buyer-address` &&
					response.ok()
			);
			await page.evaluate(() => { window.location.hash = '#settings/billing/address'; });
			expect((await (await addressResponse).json()).buyer_address).toBeNull();
			await waitForSettingsView(page, testInfo, `teams/${second.id}/billing/address`, 'billing-address-form');
			await expect(page.getByTestId('team-settings-header')).toContainText(/billing address/i);
			expect(personalBillingRequests).toEqual([]);
			page.off('request', onBillingDeepLinkRequest);
			await expect(page.getByText('Failed to start chat synchronization.', { exact: true })).toHaveCount(0);
			expect(syncErrors, 'Team switching must not fail phased chat synchronization').toEqual([]);
		} catch (error) {
			primaryError = error;
			await testInfo.attach('team-usage-primary-error', {
				body: error instanceof Error ? (error.stack ?? error.message) : String(error),
				contentType: 'text/plain'
			});
		} finally {
			for (const team of teams.reverse()) {
				if (team.seeded) {
					try {
						cleanupTeamUsage(team.id, team.ownerId, team.items);
					} catch (error) {
						cleanupErrors.push(error);
					}
				}
				try {
					const deleted = await page.request.delete(team.apiUrl);
					expect(deleted.ok()).toBe(true);
				} catch (error) {
					cleanupErrors.push(error);
				}
			}
		}
		if (primaryError || cleanupErrors.length) {
			throw new AggregateError(
				[...(primaryError ? [primaryError] : []), ...cleanupErrors],
				'Team usage journey or disposable fixture cleanup failed'
			);
		}
	});
});
