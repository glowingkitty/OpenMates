/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
export {};

import type { Page, Response } from '@playwright/test';
/**
 * Teams V1 web flow coverage.
 *
 * Verifies the deployed web app can create encrypted Teams only from Settings,
 * switch personal/team context from the profile menu, keep personal
 * memories/accounts out of team context, and create an email invite request.
 */

const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

const PROOF_STATE_HOLD_MS = 1200;
const isProofCapture = Boolean(
	process.env.PLAYWRIGHT_VIDEO_WIDTH && process.env.PLAYWRIGHT_VIDEO_HEIGHT
);

async function holdProofState(page: Page): Promise<void> {
	if (isProofCapture) await page.waitForTimeout(PROOF_STATE_HOLD_MS);
}

function isApiPath(
	response: Response,
	method: string,
	matcher: (pathname: string) => boolean
): boolean {
	if (response.request().method() !== method) return false;
	try {
		return matcher(new URL(response.url()).pathname);
	} catch {
		return false;
	}
}

test.describe('Teams V1 web flow', () => {
	// contract-test: direct surface=gui.web assertions=teams.lifecycle.encrypted-profiled,teams.invites.fragment-key-web-flow,teams.context.full-switch-local,teams.chat-billing.team-credit-boundary,teams.workspace.surface-parity
	test('creates a settings-only encrypted team and switches context from the profile menu', async ({
		page
	}: {
		page: Page;
	}) => {
		test.setTimeout(180000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:teams']);

		const uniqueSuffix = Date.now();
		const teamName = `E2E team ${uniqueSuffix}`;
		const inviteEmail = `teams-web-${uniqueSuffix}@example.invalid`;
		let createRequestPayload = '';
		let inviteRequestPayload = '';

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page);

		await expect(page.getByTestId('teams-nav-link')).toHaveCount(0);
		await page.getByTestId('profile-container').click();
		await expect(page.getByTestId('settings-menu')).toBeVisible({ timeout: 15000 });
		await page.getByTestId('settings-teams-item').click();
		await expect(page.getByTestId('teams-settings-page')).toBeVisible({ timeout: 30000 });
		await expect(page.getByTestId('settings-menu')).toHaveAttribute('data-active-view', 'teams');
		await holdProofState(page);

		const createResponse = page.waitForResponse((response) => {
			if (!isApiPath(response, 'POST', (pathname) => pathname === '/v1/teams')) return false;
			createRequestPayload = response.request().postData() ?? '';
			return response.ok();
		});

		await page.getByTestId('team-create-open').click();
		await page.getByTestId('team-name-input').fill(teamName);
		await page.getByTestId('team-create-continue').click();
		await page.getByTestId('team-create-submit').click();
		await createResponse;

		expect(createRequestPayload).not.toContain(teamName);
		const createPayload = JSON.parse(createRequestPayload);
		expect(createPayload.encrypted_name).toBeTruthy();
		expect(createPayload.encrypted_profile_image_metadata).toBeTruthy();
		expect(createPayload.encrypted_team_key).toBeTruthy();
		expect(createPayload.encrypted_zero_balance).toBeTruthy();

		await expect(page.getByTestId('settings-menu')).toHaveAttribute('data-active-view', /teams\//, {
			timeout: 30000
		});
		await expect(page.getByTestId('team-settings-header')).toContainText(teamName, {
			timeout: 30000
		});
		await expect(page.getByTestId('teams-settings-detail')).toContainText(/billing|credits/i, {
			timeout: 30000
		});
		// contract-test: direct surface=gui.web assertions=billing.storage.weekly-quote,billing.storage.team-policy-gate
		await expect(page.getByTestId('team-storage-summary')).toContainText('Free team storage', { timeout: 30000 });
		await expect(page.getByTestId('team-storage-summary')).toContainText('0 credits / week');
		await expect(page.getByTestId('team-storage-policy')).toContainText('Sundays at 03:00 UTC');
		await expect(page.getByTestId('team-storage-preview')).toContainText('not yet enabled');
		await expect(page.getByTestId('team-storage-active-notice')).toHaveCount(0);
		await holdProofState(page);

		const inviteResponse = page.waitForResponse((response) => {
			if (
				!isApiPath(response, 'POST', (pathname) => /^\/v1\/teams\/[^/]+\/invites$/.test(pathname))
			)
				return false;
			inviteRequestPayload = response.request().postData() ?? '';
			return response.ok();
		});

		await page.getByTestId('team-members-open').click();
		await page.getByTestId('team-invite-email-input').fill(inviteEmail);
		await page.getByTestId('team-invite-submit').click();
		await inviteResponse;

		expect(inviteRequestPayload).not.toContain(teamName);
		const invitePayload = JSON.parse(inviteRequestPayload);
		expect(invitePayload.recipient_email).toBe(inviteEmail);
		expect(invitePayload.encrypted_recipient_hint).toBeTruthy();
		expect(invitePayload.encrypted_invite_team_key).toBeTruthy();
		expect(invitePayload.invite_key_kdf_context).toBeTruthy();
		await expect(page.getByTestId('team-invite-status')).toContainText(
			/invite ready.*secure link/i,
			{ timeout: 15000 }
		);
		await expect(page.getByTestId('team-invite-open-email')).toBeVisible();
		await holdProofState(page);

		await page.getByTestId('banner-back-button').click();
		await expect(page.getByTestId('teams-settings-detail')).toBeVisible();
		await page.getByTestId('banner-back-button').click();
		await expect(page.getByTestId('settings-menu')).toHaveAttribute('data-active-view', 'teams');
		const createdTeamRow = page
			.getByTestId('team-settings-team-row')
			.filter({ hasText: teamName })
			.first();
		await expect(createdTeamRow).toBeVisible({ timeout: 15000 });
		await expect(createdTeamRow).toContainText(/owner/i);
		await page.getByTestId('banner-back-button').click();
		await expect(page.getByTestId('settings-menu')).toHaveAttribute('data-active-view', 'main');

		await expect(page.getByTestId('team-context-dropdown')).toBeVisible({ timeout: 30000 });
		await expect(page.getByTestId('team-context-dropdown')).toContainText(/personal/i);
		await expect(page.getByTestId('profile-open-active-team-avatar')).toHaveCount(0);
		await holdProofState(page);
		await page.getByTestId('team-context-dropdown').click();
		await page
			.getByTestId('team-context-menu')
			.getByRole('menuitemradio', { name: teamName })
			.click();
		await expect(page.getByTestId('team-context-dropdown')).toContainText(teamName, {
			timeout: 15000
		});
		await expect(page.getByTestId('profile-open-active-team-avatar')).toBeVisible({
			timeout: 15000
		});
		await holdProofState(page);

		await page.getByTestId('icon-button-close').click();
		await expect(page.getByTestId('settings-menu')).not.toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('profile-active-team-avatar')).toBeVisible({ timeout: 15000 });
		await holdProofState(page);
	});
});
