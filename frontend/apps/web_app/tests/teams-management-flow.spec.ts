/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
export {};

import type { Page, Response } from '@playwright/test';

const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

function isRequest(response: Response, method: string, path: RegExp): boolean {
	return response.request().method() === method && path.test(new URL(response.url()).pathname);
}

test.describe('Teams management', () => {
	// contract-test: direct surface=gui.web assertions=teams.lifecycle.encrypted-profiled,teams.name.transient-policy,teams.profile-image.safe-parity,teams.security.join-policy,teams.invites.fragment-key-web-flow
	test('creates a team, restricts domains and prepares a client-key email invite', async ({
		page
	}: {
		page: Page;
	}) => {
		test.setTimeout(180000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:teams']);
		const suffix = Date.now();
		const teamName = `Web studio ${suffix}`;
		const allowedDomain = 'example.org';
		const recipient = `teammate-${suffix}@${allowedDomain}`;

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page);
		await page.getByTestId('profile-container').click();
		await page.getByTestId('settings-teams-item').click();
		await expect(page.getByTestId('team-create-open')).toBeVisible();
		await page.getByTestId('team-create-open').click();
		await expect(page.getByTestId('settings-menu')).toHaveAttribute(
			'data-active-view',
			'teams/new'
		);
		await page.getByTestId('team-name-input').fill(teamName);
		const nameApproval = page.waitForResponse(
			(response) => isRequest(response, 'POST', /^\/v1\/teams\/name-approval$/) && response.ok()
		);
		await page.getByTestId('team-create-continue').click();
		await nameApproval;
		await expect(page.getByTestId('settings-menu')).toHaveAttribute(
			'data-active-view',
			'teams/new/avatar'
		);
		await expect(page.getByTestId('team-avatar-preview')).toBeVisible();
		await page.getByTestId('team-avatar-regenerate').click();
		await page.getByTestId('team-avatar-color').selectOption('#8b62c9');
		let createPayload: Record<string, unknown> = {};
		const created = page.waitForResponse((response) => {
			if (!isRequest(response, 'POST', /^\/v1\/teams$/)) return false;
			createPayload = JSON.parse(response.request().postData() ?? '{}');
			return response.ok();
		});
		await page.getByTestId('team-create-submit').click();
		await created;
		expect(createPayload.encrypted_name).toBeTruthy();
		expect(createPayload.encrypted_profile_image_metadata).toBeTruthy();
		expect(createPayload.name_approval_token).toBeTruthy();
		expect(JSON.stringify(createPayload)).not.toContain(teamName);
		await expect(page.getByTestId('settings-menu')).toHaveAttribute(
			'data-active-view',
			/^teams\/[^/]+$/
		);
		await expect(page.getByTestId('team-settings-header')).toContainText(teamName);
		await expect(page.getByTestId('team-setup-checklist')).toBeVisible();

		await page.getByTestId('team-security-open').click();
		await expect(page.getByTestId('team-security-domain-toggle')).toBeVisible();
		const domainToggle = page.waitForResponse(
			(response) => isRequest(response, 'PATCH', /^\/v1\/teams\/[^/]+\/security$/) && response.ok()
		);
		await page.getByTestId('team-security-domain-toggle').click();
		await domainToggle;
		await page.getByTestId('team-security-domain-input').fill(allowedDomain);
		const domainAdded = page.waitForResponse(
			(response) => isRequest(response, 'PATCH', /^\/v1\/teams\/[^/]+\/security$/) && response.ok()
		);
		await page.getByTestId('team-security-domain-add').click();
		await domainAdded;
		await expect(page.getByText(allowedDomain, { exact: true })).toBeVisible();

		await page.getByTestId('banner-back-button').click();
		await page.getByTestId('team-members-open').click();
		await expect(page.getByTestId('team-member-row').first()).toBeVisible();
		await page.getByTestId('team-invite-email-input').fill(`blocked-${suffix}@example.invalid`);
		await page.getByTestId('team-invite-submit').click();
		await expect(page.getByTestId('team-invite-inline-error')).toContainText('not allowed');
		await expect(
			page
				.getByTestId('team-invite-inline-error')
				.getByRole('link', { name: 'Change allowed domains in Security' })
		).toBeVisible();
		await page.getByTestId('team-invite-email-input').fill(recipient);
		let invitePayload: Record<string, unknown> = {};
		const invited = page.waitForResponse((response) => {
			if (!isRequest(response, 'POST', /^\/v1\/teams\/[^/]+\/invites$/)) return false;
			invitePayload = JSON.parse(response.request().postData() ?? '{}');
			return response.ok();
		});
		await page.getByTestId('team-invite-submit').click();
		await invited;
		expect(invitePayload).toMatchObject({ recipient_email: recipient });
		expect(invitePayload.encrypted_invite_team_key).toBeTruthy();
		expect(invitePayload.invite_key_kdf_context).toBeTruthy();
		await expect(page.getByTestId('team-invite-status')).toContainText('Invite ready');
		await expect(page.getByTestId('team-invite-open-email')).toBeVisible();
		await expect(page.getByTestId('team-invite-copy-secure-link')).toBeVisible();

		await page.getByTestId('banner-back-button').click();
		await page.getByTestId('team-delete-open').click();
		const deleteButton = page.getByTestId('team-delete-submit');
		await expect(deleteButton).toBeDisabled();
		await page
			.getByRole('checkbox', {
				name: 'I understand this team will be permanently deleted',
				exact: true
			})
			.check();
		await expect(deleteButton).toBeEnabled();
		const deleted = page.waitForResponse(
			(response) => isRequest(response, 'DELETE', /^\/v1\/teams\/[^/]+$/) && response.ok()
		);
		await deleteButton.click();
		await deleted;
		await expect(page.getByTestId('settings-menu')).toHaveAttribute('data-active-view', 'teams');
		await expect(
			page.getByTestId('team-settings-team-row').filter({ hasText: teamName })
		).toHaveCount(0);
	});
});
