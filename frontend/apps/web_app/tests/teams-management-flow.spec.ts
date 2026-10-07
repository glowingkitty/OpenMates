/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
export {};

import path from 'node:path';
import type { Page, Response, TestInfo } from '@playwright/test';
import { waitForSettingsView } from './helpers/settings-readiness';

const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

function isRequest(response: Response, method: string, path: RegExp): boolean {
	return response.request().method() === method && path.test(new URL(response.url()).pathname);
}

async function holdVisibleProofState(page: Page): Promise<void> {
	// playwright-determinism: allow - recorded proof needs a short hold after an asserted UI state.
	if (page.video()) await page.waitForTimeout(1200);
}

test.describe('Teams management', () => {
	// contract-test: direct surface=gui.web assertions=teams.lifecycle.encrypted-profiled,teams.name.transient-policy,teams.profile-image.safe-parity,teams.security.join-policy,teams.invites.fragment-key-web-flow
	test('creates and manages a team, then revokes a private invite link', async ({
		page
	}: { page: Page }, testInfo: TestInfo) => {
		test.setTimeout(300000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:teams']);
		const suffix = Date.now();
		const teamName = `Web studio ${suffix}`;
		const renamedTeam = `Web studio updated ${suffix}`;
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
		const createResponse = await created;
		const teamId = String((await createResponse.json()).team.team_id);
		expect(teamId).toBeTruthy();
		const teamApiUrl = new URL(`/v1/teams/${teamId}`, createResponse.url()).toString();
		let deletionCompleted = false;
		let primaryError: unknown;
		let cleanupError: unknown;
		try {
			expect(createPayload.encrypted_name).toBeTruthy();
			expect(createPayload.encrypted_profile_image_metadata).toBeTruthy();
			expect(createPayload.name_approval_token).toBeTruthy();
			expect(JSON.stringify(createPayload)).not.toContain(teamName);
			await expect(page.getByTestId('settings-menu')).toHaveAttribute(
				'data-active-view',
				`teams/${teamId}`
			);
			await expect(page.getByTestId('team-settings-header')).toContainText(teamName);
			await expect(page.getByTestId('team-setup-checklist')).toBeVisible();
			await holdVisibleProofState(page);
			await page.getByTestId('team-name-open').click();
			await page.getByTestId('team-edit-name-input').fill(renamedTeam);
			const renameApproval = page.waitForResponse(
				(response) => isRequest(response, 'POST', /^\/v1\/teams\/name-approval$/) && response.ok()
			);
			let renamePayload: Record<string, unknown> = {};
			const renamed = page.waitForResponse((response) => {
				if (!isRequest(response, 'PATCH', new RegExp(`^/v1/teams/${teamId}$`))) return false;
				renamePayload = JSON.parse(response.request().postData() ?? '{}');
				return response.ok();
			});
			await page.getByTestId('team-edit-name-save').click();
			await renameApproval;
			await renamed;
			expect(renamePayload.encrypted_name).toBeTruthy();
			expect(renamePayload.name_approval_token).toBeTruthy();
			expect(JSON.stringify(renamePayload)).not.toContain(renamedTeam);
			await expect(page.getByTestId('team-settings-header')).toContainText(renamedTeam);
			await page.reload({ waitUntil: 'domcontentloaded' });
			await waitForSettingsView(page, testInfo, `teams/${teamId}`, 'teams-settings-detail');
			await expect(page.getByTestId('team-settings-header')).toContainText(renamedTeam);
			await holdVisibleProofState(page);
			await page.getByTestId('team-name-open').click();
			await expect(page.getByTestId('team-edit-name-input')).toHaveAttribute(
				'placeholder',
				renamedTeam
			);
			await expect(page.getByTestId('team-edit-name-input')).toHaveValue('');
			await page.getByTestId('banner-back-button').click();

			await page.getByTestId('team-avatar-open').click();
			await page
				.getByTestId('team-avatar-file-input')
				.setInputFiles(path.join(__dirname, 'fixtures', 'golden_gate_bridge.jpg'));
			const stagedImage = page.locator('.avatar-stage img');
			await expect(stagedImage).toBeVisible();
			await expect
				.poll(() =>
					stagedImage.evaluate((image: HTMLImageElement) => [
						image.naturalWidth,
						image.naturalHeight
					])
				)
				.toEqual([340, 340]);
			await page.evaluate(() => {
				const originalFetch = window.fetch.bind(window);
				window.fetch = (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
					const url = input instanceof Request ? input.url : String(input);
					if (url.includes('/v1/upload/team-profile-image') && init?.body instanceof FormData) {
						window.fetch = originalFetch;
						const form = init.body;
						void (async () => {
							const file = form.get('file');
							if (!(file instanceof File)) throw new Error('Upload file is missing');
							const signature = new Uint8Array(await file.slice(0, 3).arrayBuffer());
							const image = await createImageBitmap(file);
							const dimensions = [image.width, image.height];
							image.close();
							const metadata = form.get('encrypted_profile_image_metadata');
							return {
								teamId: form.get('team_id'),
								encryptedMetadataPresent: typeof metadata === 'string' && metadata.length > 0,
								fileType: file.type,
								fileSize: file.size,
								jpegSignature: signature.join(','),
								dimensions
							};
						})()
							.then((audit) => {
								document.body.dataset.teamUploadAudit = JSON.stringify(audit);
							})
							.catch((error) => {
								document.body.dataset.teamUploadAudit = JSON.stringify({ error: String(error) });
							});
					}
					return originalFetch(input, init);
				};
			});
			const uploaded = page.waitForResponse(
				(response) =>
					isRequest(response, 'POST', /^\/v1\/upload\/team-profile-image$/) && response.ok()
			);
			const refreshedTeam = page.waitForResponse(
				(response) =>
					isRequest(response, 'GET', new RegExp(`^/v1/teams/${teamId}$`)) && response.ok()
			);
			await page.getByTestId('team-avatar-save').click();
			const uploadResponse = await uploaded;
			await refreshedTeam;
			expect(uploadResponse.request().headers()['content-type']).toContain('multipart/form-data');
			await expect
				.poll(() => page.evaluate(() => document.body.dataset.teamUploadAudit ?? ''), {
					timeout: 15000
				})
				.not.toBe('');
			const uploadAudit = JSON.parse(
				(await page.evaluate(() => document.body.dataset.teamUploadAudit)) ?? '{}'
			) as {
				teamId?: string;
				encryptedMetadataPresent?: boolean;
				fileType?: string;
				fileSize?: number;
				jpegSignature?: string;
				dimensions?: number[];
				error?: string;
			};
			expect(uploadAudit.error).toBeUndefined();
			expect(uploadAudit.teamId).toBe(teamId);
			expect(uploadAudit.encryptedMetadataPresent).toBe(true);
			expect(uploadAudit.fileType).toBe('image/jpeg');
			expect(uploadAudit.fileSize).toBeGreaterThan(0);
			expect(uploadAudit.jpegSignature).toBe('255,216,255');
			expect(uploadAudit.dimensions).toEqual([340, 340]);
			await expect(page.getByTestId('team-settings-header-avatar').locator('img')).toBeVisible();
			const proxyImage = page.waitForResponse(
				(response) =>
					isRequest(response, 'GET', new RegExp(`^/v1/teams/${teamId}/profile-image$`)) &&
					response.ok() &&
					(response.headers()['content-type'] ?? '').startsWith('image/')
			);
			await page.reload({ waitUntil: 'domcontentloaded' });
			await proxyImage;
			await waitForSettingsView(page, testInfo, `teams/${teamId}`, 'teams-settings-detail');
			await expect(page.getByTestId('settings-menu')).toHaveAttribute(
				'data-active-view',
				`teams/${teamId}`
			);
			await expect(page.getByTestId('team-settings-header-avatar').locator('img')).toBeVisible();
			await expect
				.poll(() =>
					page
						.getByTestId('team-settings-header-avatar')
						.locator('img')
						.evaluate((image: HTMLImageElement) => [image.naturalWidth, image.naturalHeight])
				)
				.toEqual([340, 340]);
			await holdVisibleProofState(page);
			await page.getByTestId('team-avatar-open').click();
			await expect(page.locator('.avatar-stage img')).toBeVisible();
			await page.getByTestId('banner-back-button').click();
			await expect(page.getByTestId('settings-menu')).toHaveAttribute(
				'data-active-view',
				`teams/${teamId}`
			);
			await page.getByTestId('banner-back-button').click();
			await expect(page.getByTestId('settings-menu')).toHaveAttribute('data-active-view', 'teams');
			await page.getByTestId('banner-back-button').click();
			await expect(page.getByTestId('settings-menu')).toHaveAttribute('data-active-view', 'main');
			await page.getByTestId('team-context-dropdown').click();
			await page.getByTestId(`team-context-option-${teamId}`).click();
			await expect(page.getByTestId('team-context-dropdown')).toContainText(renamedTeam);
			await page.getByTestId('icon-button-close').click();
			await expect(page.getByTestId('settings-menu')).not.toBeVisible();
			const profileTeamImage = page.getByTestId('profile-active-team-avatar').locator('img');
			await expect(profileTeamImage).toBeVisible();
			await expect
				.poll(() =>
					profileTeamImage.evaluate((image: HTMLImageElement) => [
						image.naturalWidth,
						image.naturalHeight
					])
				)
				.toEqual([340, 340]);
			await expect(page.getByTestId('profile-active-team-avatar')).toHaveAttribute(
				'aria-label',
				`Active team: ${renamedTeam}`
			);
			await expect(page.getByTestId('profile-active-team-avatar')).toHaveText('');
			await expect(page.getByTestId('welcome-content')).toBeVisible();
			const chatTeamAvatar = page.getByTestId('chats-workspace-team-avatar');
			const chatBackgroundIcon = page.getByTestId('guest-workspace-icon');
			await expect(chatTeamAvatar.locator('img')).toBeVisible();
			await expect
				.poll(() =>
					chatTeamAvatar
						.locator('img')
						.evaluate((image: HTMLImageElement) => [image.naturalWidth, image.naturalHeight])
				)
				.toEqual([340, 340]);
			await expect(chatTeamAvatar).toHaveCSS('opacity', '0.3');
			const teamBox = await chatTeamAvatar.boundingBox();
			const iconBox = await chatBackgroundIcon.boundingBox();
			expect(teamBox).toBeTruthy();
			expect(iconBox).toBeTruthy();
			expect(teamBox!.x + teamBox!.width).toBeLessThan(iconBox!.x);
			expect(teamBox!.width).toBeCloseTo(iconBox!.width, 0);
			expect(teamBox!.height).toBeCloseTo(iconBox!.height, 0);
			expect(teamBox!.y + teamBox!.height / 2).toBeCloseTo(iconBox!.y + iconBox!.height / 2, 0);
			await holdVisibleProofState(page);
			await page.getByTestId('profile-container').click();
			await expect(page.getByTestId('settings-menu')).toBeVisible();
			await page.getByTestId('settings-teams-item').click();
			await page.getByTestId('team-settings-team-row').filter({ hasText: renamedTeam }).click();
			await expect(page.getByTestId('settings-menu')).toHaveAttribute(
				'data-active-view',
				`teams/${teamId}`
			);

			await page.getByTestId('team-security-open').click();
			await waitForSettingsView(
				page,
				testInfo,
				`teams/${teamId}/security`,
				'team-security-domain-toggle'
			);
			const domainToggle = page.waitForResponse(
				(response) =>
					isRequest(response, 'PATCH', /^\/v1\/teams\/[^/]+\/security$/) && response.ok()
			);
			await page.getByTestId('team-security-domain-toggle').click();
			await domainToggle;
			await page.getByTestId('team-security-domain-input').fill(allowedDomain);
			const domainAdded = page.waitForResponse(
				(response) =>
					isRequest(response, 'PATCH', /^\/v1\/teams\/[^/]+\/security$/) && response.ok()
			);
			await page.getByTestId('team-security-domain-add').click();
			await domainAdded;
			await expect(page.getByText(allowedDomain, { exact: true })).toBeVisible();
			const approvalToggle = page
				.getByTestId('team-security-approval-toggle')
				.locator('input[type="checkbox"]');
			const strongAuthToggle = page
				.getByTestId('team-security-strong-auth-toggle')
				.locator('input[type="checkbox"]');
			await expect(approvalToggle).toBeChecked();
			await expect(strongAuthToggle).not.toBeChecked();
			const approvalChanged = page.waitForResponse(
				(response) =>
					isRequest(response, 'PATCH', /^\/v1\/teams\/[^/]+\/security$/) &&
					response.ok() &&
					JSON.parse(response.request().postData() ?? '{}').require_invite_link_approval === false
			);
			await page.getByTestId('team-security-approval-toggle').click();
			await approvalChanged;
			await expect(approvalToggle).not.toBeChecked();
			const strongAuthChanged = page.waitForResponse(
				(response) =>
					isRequest(response, 'PATCH', /^\/v1\/teams\/[^/]+\/security$/) &&
					response.ok() &&
					JSON.parse(response.request().postData() ?? '{}').require_strong_auth === true
			);
			await page.getByTestId('team-security-strong-auth-toggle').click();
			await strongAuthChanged;
			await expect(strongAuthToggle).toBeChecked();
			await page.reload({ waitUntil: 'domcontentloaded' });
			await waitForSettingsView(
				page,
				testInfo,
				`teams/${teamId}/security`,
				'team-security-domain-toggle'
			);
			await expect(
				page.getByTestId('team-security-domain-toggle').locator('input[type="checkbox"]')
			).toBeChecked();
			await expect(page.getByText(allowedDomain, { exact: true })).toBeVisible();
			await expect(approvalToggle).not.toBeChecked();
			await expect(strongAuthToggle).toBeChecked();
			await holdVisibleProofState(page);

			await page.getByTestId('banner-back-button').click();
			await page.getByTestId('team-members-open').click();
			await waitForSettingsView(
				page,
				testInfo,
				`teams/${teamId}/members`,
				'team-invite-email-input'
			);
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
			await expect(
				page.getByTestId('team-pending-invite-row').filter({ hasText: recipient })
			).toBeVisible();
			await holdVisibleProofState(page);

			// A share link has an owner-readable lookup before revocation; its disappearance
			// proves the pending invite became unusable, independently of recipient identity.
			await page.evaluate(() => {
				Object.defineProperty(navigator, 'clipboard', {
					configurable: true,
					value: {
						writeText: async (value: string) => {
							document.body.dataset.secureInvite = value;
						}
					}
				});
			});
			const linkCreated = page.waitForResponse(
				(response) => isRequest(response, 'POST', /^\/v1\/teams\/[^/]+\/invites$/) && response.ok()
			);
			await page.getByTestId('team-copy-invite-link').click();
			const linkResponse = await linkCreated;
			const linkBody = await linkResponse.json();
			const linkInviteId = String(linkBody.invite.invite_id);
			const secureLink = await page.locator('body').getAttribute('data-secure-invite');
			expect(secureLink).toMatch(
				new RegExp(`/teams/invites/${linkInviteId}#key=[A-Za-z0-9_-]{43}$`)
			);
			const inviteLookup = new URL(
				`/v1/teams/invites/${linkInviteId}`,
				linkResponse.url()
			).toString();
			const beforeRevoke = await page.request.get(inviteLookup);
			expect(beforeRevoke.status()).toBe(409); // Security policy requires the private preview path.
			await expect(page.getByTestId(`team-invite-revoke-${linkInviteId}`)).toBeVisible();
			const revoked = page.waitForResponse(
				(response) =>
					isRequest(
						response,
						'POST',
						new RegExp(`^/v1/teams/${teamId}/invites/${linkInviteId}/revoke$`)
					) && response.ok()
			);
			await page.getByTestId(`team-invite-revoke-${linkInviteId}`).click();
			await revoked;
			await expect(page.getByTestId(`team-invite-revoke-${linkInviteId}`)).toHaveCount(0);
			const afterRevoke = await page.request.get(inviteLookup);
			expect(afterRevoke.status()).toBe(404);
			await page.reload({ waitUntil: 'domcontentloaded' });
			await waitForSettingsView(
				page,
				testInfo,
				`teams/${teamId}/members`,
				'team-invite-email-input'
			);
			await expect(page.getByTestId(`team-invite-revoke-${linkInviteId}`)).toHaveCount(0);
			await expect(
				page.getByTestId('team-pending-invite-row').filter({ hasText: recipient })
			).toBeVisible();
			await holdVisibleProofState(page);

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
			deletionCompleted = true;
			await expect(page.getByTestId('settings-menu')).toHaveAttribute('data-active-view', 'teams');
			await expect(
				page.getByTestId('team-settings-team-row').filter({ hasText: renamedTeam })
			).toHaveCount(0);
			await expect(page.getByTestId('profile-active-team-avatar')).toHaveCount(0);
			await holdVisibleProofState(page);
		} catch (error) {
			primaryError = error;
		}
		if (!deletionCompleted) {
			try {
				const cleanup = await page.request.delete(teamApiUrl);
				expect(cleanup.ok()).toBe(true);
			} catch (error) {
				cleanupError = error;
			}
		}
		if (primaryError && cleanupError) {
			throw new AggregateError([primaryError, cleanupError], 'Teams journey and cleanup failed');
		}
		if (primaryError) throw primaryError;
		if (cleanupError) throw cleanupError;
	});
});
