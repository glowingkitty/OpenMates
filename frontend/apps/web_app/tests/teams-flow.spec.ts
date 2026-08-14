/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Teams V1 web flow coverage.
 *
 * Verifies the deployed web app can create encrypted Teams from /teams, switch
 * the visible workspace context, keep personal memories/accounts out of the
 * team context, and create an email invite request through the Teams UI.
 */

const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

function isApiPath(response, method, matcher) {
	if (response.request().method() !== method) return false;
	try {
		return matcher(new URL(response.url()).pathname);
	} catch {
		return false;
	}
}

test.describe('Teams V1 web flow', () => {
	// contract-test: direct surface=gui.web assertions=teams.lifecycle.encrypted-profiled,teams.invites.fragment-key-web-flow,teams.context.full-switch-local,teams.chat-billing.team-credit-boundary,teams.workspace.surface-parity
	test('creates an encrypted team, switches context, and creates an email invite request', async ({ page }) => {
		test.setTimeout(180000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:teams']);

		const uniqueSuffix = Date.now();
		const teamName = `E2E team ${uniqueSuffix}`;
		const teamDescription = `Encrypted web parity team ${uniqueSuffix}`;
		const inviteEmail = `teams-web-${uniqueSuffix}@example.invalid`;
		let createRequestPayload = '';
		let inviteRequestPayload = '';

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page);
		await page.goto(getE2EDebugUrl('/teams'), { waitUntil: 'domcontentloaded' });

		await expect(page.getByTestId('teams-page')).toBeVisible({ timeout: 30000 });
		await expect(page.getByTestId('teams-workspace-home')).toBeVisible({ timeout: 30000 });
		await expect(page.getByTestId('teams-nav-link')).toBeVisible({ timeout: 15000 });

		const createResponse = page.waitForResponse((response) => {
			if (!isApiPath(response, 'POST', (pathname) => pathname === '/v1/teams')) return false;
			createRequestPayload = response.request().postData() ?? '';
			return response.ok();
		});

		await page.getByTestId('team-name-input').fill(teamName);
		await page.getByTestId('team-description-input').fill(teamDescription);
		await page.getByTestId('team-create-submit').click();
		await createResponse;

		expect(createRequestPayload).not.toContain(teamName);
		expect(createRequestPayload).not.toContain(teamDescription);
		const createPayload = JSON.parse(createRequestPayload);
		expect(createPayload.encrypted_name).toBeTruthy();
		expect(createPayload.encrypted_profile_image_metadata).toBeTruthy();
		expect(createPayload.encrypted_team_key).toBeTruthy();
		expect(createPayload.encrypted_zero_balance).toBeTruthy();

		const teamCard = page.getByTestId('team-card').filter({ hasText: teamName }).first();
		await expect(teamCard).toBeVisible({ timeout: 30000 });
		await expect(teamCard).toHaveAttribute('data-team-role', 'owner');
		await teamCard.click();

		await expect(page.getByTestId('active-team-name')).toContainText(teamName, { timeout: 15000 });
		await expect(page.getByTestId('active-team-description')).toContainText(teamDescription, { timeout: 15000 });
		await expect(page.getByTestId('team-role-badge')).toContainText(/owner/i, { timeout: 15000 });
		await expect(page.getByTestId('team-context-badge')).toContainText(/team context/i, { timeout: 15000 });

		await expect(page.getByTestId('team-billing-panel')).toContainText(/team credits/i, { timeout: 30000 });
		await expect(page.getByTestId('team-credit-balance')).toContainText(/0/i, { timeout: 30000 });
		await expect(page.getByTestId('team-memories-panel')).toContainText(/team memories/i, { timeout: 30000 });
		await expect(page.getByTestId('team-connected-accounts-panel')).toContainText(/team connected accounts/i, { timeout: 30000 });
		await expect(page.getByTestId('team-personal-data-guard')).toContainText(/personal memories stay in personal context/i, { timeout: 15000 });
		await expect(page.getByTestId('team-personal-data-guard')).toContainText(/personal connected accounts stay in personal context/i, { timeout: 15000 });

		const inviteResponse = page.waitForResponse((response) => {
			if (!isApiPath(response, 'POST', (pathname) => /^\/v1\/teams\/[^/]+\/invites$/.test(pathname))) return false;
			inviteRequestPayload = response.request().postData() ?? '';
			return response.ok();
		});

		await page.getByTestId('team-invite-email-input').fill(inviteEmail);
		await page.getByTestId('team-invite-submit').click();
		await inviteResponse;

		expect(inviteRequestPayload).not.toContain(teamName);
		expect(inviteRequestPayload).not.toContain(teamDescription);
		const invitePayload = JSON.parse(inviteRequestPayload);
		expect(invitePayload.recipient_email).toBe(inviteEmail);
		expect(invitePayload.encrypted_recipient_hint).toBeTruthy();
		await expect(page.getByTestId('team-invite-status')).toContainText(/invite created|invite sent/i, { timeout: 15000 });
	});
});
