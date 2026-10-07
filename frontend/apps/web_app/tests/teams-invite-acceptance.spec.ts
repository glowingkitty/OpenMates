/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
export {};
import type { Browser, Page, Response } from '@playwright/test';
const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const {
	createSignupEmailClient,
	generateTotp,
	getE2EDebugUrl,
	getTestAccount
} = require('./signup-flow-helpers');

const isProofCapture = Boolean(
	process.env.PLAYWRIGHT_VIDEO_WIDTH && process.env.PLAYWRIGHT_VIDEO_HEIGHT
);

async function holdProofState(page: Page): Promise<void> {
	if (isProofCapture) await page.waitForTimeout(1200);
}

function apiResponse(response: Response, method: string, suffix: RegExp): boolean {
	return response.request().method() === method && suffix.test(new URL(response.url()).pathname);
}

// contract-test: direct surface=gui.web assertions=teams.invites.fragment-key-web-flow,teams.security.join-policy,teams.membership.change-emails,teams.membership.role-gated
test('accepts a private direct invite and emails role changes and removal', async ({
	page,
	browser
}: {
	page: Page;
	browser: Browser;
}, testInfo: {
	outputPath: (name: string) => string;
	attach: (name: string, options: { path: string; contentType: string }) => Promise<void>;
}) => {
	test.setTimeout(300000);
	const owner = getTestAccount(1);
	const member = getTestAccount(2);
	test.skip(
		!owner.email || !member.email || owner.email === member.email,
		'Two isolated account identities required.'
	);
	await skipIfFeaturesDisabled(test, page, ['platform:teams']);
	await loginToTestAccount(page, undefined, undefined, { credentials: owner });
	let teamId: string | null = null;
	let teamApiOrigin: string | null = null;
	let memberContext: Awaited<ReturnType<Browser['newContext']>> | undefined;
	let recipientVideo: ReturnType<Page['video']> | undefined;
	let flowError: unknown;
	const cleanupErrors: unknown[] = [];
	try {
		await page.evaluate(() => {
			Object.defineProperty(navigator, 'clipboard', {
				configurable: true,
				value: {
					writeText: async (text: string) => {
						document.body.dataset.secureInvite = text;
					}
				}
			});
		});
		await page.getByTestId('profile-container').click();
		await page.getByTestId('settings-teams-item').click();
		await page.getByTestId('team-create-open').click();
		const teamName = `Private studio ${Date.now()}`;
		await page.getByTestId('team-name-input').fill(teamName);
		await page.getByTestId('team-create-continue').click();
		const created = page.waitForResponse(
			(response: Response) => apiResponse(response, 'POST', /^\/v1\/teams$/) && response.ok()
		);
		await page.getByTestId('team-create-submit').click();
		const createResponse = await created;
		teamApiOrigin = new URL(createResponse.url()).origin;
		teamId = String((await createResponse.json()).team.team_id);
		await expect(page.getByTestId('team-settings-header')).toContainText(teamName);
		await holdProofState(page);
		await page.getByTestId('team-security-open').click();
		const strongAuthEnabled = page.waitForResponse(
			(response: Response) =>
				apiResponse(response, 'PATCH', new RegExp(`^/v1/teams/${teamId}/security$`)) &&
				response.ok()
		);
		await page.getByTestId('team-security-strong-auth-toggle').click();
		expect((await strongAuthEnabled).request().postDataJSON()).toMatchObject({
			require_strong_auth: true
		});
		await expect(page.getByTestId('team-security-strong-auth-toggle')).toContainText(
			/passkey|2fa/i
		);
		await holdProofState(page);
		await page.getByTestId('banner-back-button').click();
		await page.getByTestId('team-members-open').click();
		await page.getByTestId('team-invite-email-input').fill(member.email);
		const invited = page.waitForResponse(
			(response: Response) => apiResponse(response, 'POST', /\/invites$/) && response.ok()
		);
		await page.getByTestId('team-invite-submit').click();
		const inviteBody = await (await invited).json();
		expect(inviteBody.invite.delivery_status).toBe('client_share_required');
		await page.getByTestId('team-invite-copy-secure-link').click();
		const secureUrl = await page.locator('body').getAttribute('data-secure-invite');
		expect(secureUrl).toMatch(/\/teams\/invites\/[^#]+#key=[A-Za-z0-9_-]{43}$/);
		const secret = new URL(secureUrl!).hash.slice('#key='.length);
		await expect(page.getByTestId('team-invite-status')).toBeVisible();
		await holdProofState(page);

		const ownerViewport = page.viewportSize();
		if (!ownerViewport) throw new Error('Owner viewport is required for recipient recording');
		memberContext = await browser.newContext({
			baseURL: new URL(secureUrl!).origin,
			viewport: ownerViewport,
			recordVideo: { dir: testInfo.outputPath('recipient-video'), size: ownerViewport }
		});
		const recipientPage = await memberContext.newPage();
		recipientVideo = recipientPage.video();
		const privatePayloads: string[] = [];
		recipientPage.on('request', (request) => {
			if (new URL(request.url()).pathname.startsWith('/v1/teams/')) {
				privatePayloads.push(request.url(), request.postData() ?? '');
			}
		});
		// Guest handoff removes the URL fragment and preserves its key only in this tab.
		await recipientPage.goto(secureUrl!);
		await expect.poll(() => recipientPage.url()).not.toContain('#key=');
		await expect
			.poll(() =>
				recipientPage.evaluate(
					(id: string) => !!sessionStorage.getItem(`openmates:team-invite:${id}`),
					inviteBody.invite.invite_id
				)
			)
			.toBe(true);
		await loginToTestAccount(recipientPage, undefined, undefined, {
			credentials: member
		});
		// CI provisions both identities with TOTP. Disable it through the recipient's
		// real authenticated Security screen so the join policy has a genuine
		// password-only account to reject.
		expect(member.otpKey).toBeTruthy();
		await recipientPage.goto(getE2EDebugUrl('/#settings/account/security/2fa'));
		await recipientPage.getByTestId('tfa-disable-button').click();
		const disableAuth = recipientPage.locator('[role="dialog"]');
		await expect(disableAuth.getByTestId('tfa-input')).toBeVisible();
		// A login TOTP cannot be reused for the sensitive factor-change proof.
		const secondsIntoStep = Math.floor(Date.now() / 1000) % 30;
		await recipientPage.waitForTimeout((30 - secondsIntoStep) * 1000 + 1000);
		const factorVerified = recipientPage.waitForResponse(
			(response: Response) =>
				apiResponse(response, 'POST', /\/auth\/sensitive\/totp\/verify$/) && response.ok()
		);
		await disableAuth.getByTestId('tfa-input').fill(generateTotp(member.otpKey!));
		expect((await factorVerified).request().postDataJSON()).toMatchObject({
			purpose: 'factor_change'
		});
		await expect(recipientPage.getByTestId('tfa-disable-confirm')).toBeVisible();
		const tfaDisabled = recipientPage.waitForResponse(
			(response: Response) =>
				apiResponse(response, 'POST', /\/settings\/user\/disable-2fa$/) && response.ok()
		);
		await recipientPage.getByTestId('tfa-disable-confirm-button').click();
		await tfaDisabled;
		await expect(recipientPage.getByTestId('tfa-enable-button')).toBeVisible();
		const authMethods = await recipientPage.request.get(`${teamApiOrigin}/v1/auth/methods`);
		expect(authMethods.ok()).toBe(true);
		expect(await authMethods.json()).toMatchObject({ has_2fa: false, has_passkey: false });
		await holdProofState(recipientPage);
		await recipientPage.goto(secureUrl!.split('#')[0]);
		await expect(recipientPage.getByTestId('team-invite-recipient-email')).toBeVisible();
		await recipientPage.getByTestId('team-invite-recipient-email').fill(owner.email);
		await recipientPage.getByTestId('team-invite-accept').click();
		await expect(recipientPage.getByTestId('team-invite-error')).toContainText('verified email');
		await expect(recipientPage.getByTestId('team-invite-error')).not.toContainText('TEAM_VERIFIED_EMAIL_REQUIRED');
		await recipientPage.getByTestId('team-invite-recipient-email').fill(member.email);
		const policyRejected = recipientPage.waitForResponse(
			(response: Response) =>
				apiResponse(response, 'POST', /\/invites\/[^/]+\/preview$/) && response.status() === 403
		);
		await recipientPage.getByTestId('team-invite-accept').click();
		expect((await policyRejected).request().postDataJSON()).toMatchObject({
			verified_email: member.email.toLowerCase()
		});
		expect(await (await policyRejected).json()).toMatchObject({
			detail: 'TEAM_STRONG_AUTH_REQUIRED'
		});
		await expect(recipientPage.getByTestId('team-invite-error')).toContainText(
			/passkey|two.factor|2fa/i
		);
		await expect(recipientPage.getByTestId('team-invite-recipient-email')).toHaveValue(
			member.email
		);
		await holdProofState(recipientPage);

		await page.getByTestId('banner-back-button').click();
		await page.getByTestId('team-security-open').click();
		const strongAuthDisabled = page.waitForResponse(
			(response: Response) =>
				apiResponse(response, 'PATCH', new RegExp(`^/v1/teams/${teamId}/security$`)) &&
				response.ok()
		);
		await page.getByTestId('team-security-strong-auth-toggle').click();
		expect((await strongAuthDisabled).request().postDataJSON()).toMatchObject({
			require_strong_auth: false
		});
		await page.getByTestId('banner-back-button').click();
		await page.getByTestId('team-members-open').click();
		// The recipient keeps the fragment key after a policy rejection and retries the same invite.
		const inviteResponses: Response[] = [];
		recipientPage.on('response', (response: Response) => {
			if (apiResponse(response, 'POST', /\/invites\/[^/]+\/(preview|accept)$/)) {
				inviteResponses.push(response);
			}
		});
		await recipientPage.getByTestId('team-invite-accept').click();
		await expect
			.poll(
				() =>
					inviteResponses.some((response) => /\/preview$/.test(new URL(response.url()).pathname)),
				{
					timeout: 15000,
					message: 'Correct-email invite preview was not requested'
				}
			)
			.toBe(true);
		const preview = inviteResponses.find((response) =>
			/\/preview$/.test(new URL(response.url()).pathname)
		)!;
		expect(preview.ok(), `Correct-email invite preview failed: ${await preview.text()}`).toBe(true);
		try {
			await expect
				.poll(
					() =>
						inviteResponses.some((response) => /\/accept$/.test(new URL(response.url()).pathname)),
					{
						timeout: 20000,
						message: 'Invite preview succeeded but acceptance was not requested'
					}
				)
				.toBe(true);
		} catch (error) {
			const uiError = await recipientPage
				.getByTestId('team-invite-error')
				.textContent()
				.catch(() => null);
			throw new Error(
				`Invite preview succeeded but acceptance was not requested; UI error: ${uiError ?? 'none'}`,
				{ cause: error }
			);
		}
		const accepted = inviteResponses.find((response) =>
			/\/accept$/.test(new URL(response.url()).pathname)
		)!;
		expect(accepted.ok(), `Invite acceptance failed: ${await accepted.text()}`).toBe(true);
		const acceptance = await accepted.json();
		expect(acceptance.status).toBe('accepted');
		expect(acceptance.membership).toBeTruthy();
		await expect(recipientPage.getByTestId('team-invite-result')).toContainText(/joined/i);
		await holdProofState(recipientPage);
		expect(privatePayloads.join('\n')).not.toContain(secret);
		expect(privatePayloads.join('\n')).not.toContain(teamName);
		await expect
			.poll(() =>
				recipientPage.evaluate(
					(id: string) => sessionStorage.getItem(`openmates:team-invite:${id}`),
					inviteBody.invite.invite_id
				)
			)
			.toBeNull();

		// The owner kept the Members page open while the recipient joined. Leave
		// and reopen that page so its member query replaces the pre-join snapshot.
		await page.getByTestId('banner-back-button').click();
		await expect(page.getByTestId('team-members-open')).toBeVisible();
		const membersReloaded = page.waitForResponse(
			(response: Response) =>
				response.request().method() === 'GET' &&
				new URL(response.url()).pathname === `/v1/teams/${teamId}/members` &&
				response.ok()
		);
		await page.getByTestId('team-members-open').click();
		await membersReloaded;
		await expect(page.getByTestId('team-member-row')).toHaveCount(2);
		await page.getByTestId('team-member-row').last().click();
		const inbox = createSignupEmailClient();
		expect(inbox?.provider).toBe('mailpit');
		const changedAfter = new Date().toISOString();
		const changed = page.waitForResponse(
			(response: Response) => apiResponse(response, 'PATCH', /\/members\/[^/]+$/) && response.ok()
		);
		await page.getByTestId('team-member-detail-role').selectOption('viewer');
		await changed;
		const roleEmail = await inbox!.waitForMessage({
			sentTo: member.email,
			subjectContains: 'role',
			receivedAfter: changedAfter
		});
		expect(`${roleEmail.text.body}\n${roleEmail.html.body}`).not.toContain(teamName);
		expect(`${roleEmail.text.body}\n${roleEmail.html.body}`).not.toContain(secret);
		await recipientPage.goto(getE2EDebugUrl(`/#settings/teams/${teamId}`));
		await expect(recipientPage.getByTestId('team-settings-header')).toContainText(teamName);
		await expect(recipientPage.getByTestId('team-billing-open')).toHaveCount(0);
		await expect(recipientPage.getByTestId('team-name-open')).toHaveCount(0);
		await recipientPage.getByTestId('team-security-open').click();
		await expect(recipientPage.getByTestId('team-security-strong-auth-toggle')).toHaveAttribute(
			'aria-disabled',
			'true'
		);
		await recipientPage.getByTestId('banner-back-button').click();
		await recipientPage.getByTestId('team-members-open').click();
		await expect(recipientPage.getByTestId('team-member-row')).toHaveCount(2);
		await expect(recipientPage.getByTestId('team-invite-email-input')).toHaveCount(0);
		await expect(recipientPage.getByTestId('team-invite-submit')).toHaveCount(0);
		await recipientPage.getByTestId('team-member-row').last().click();
		await expect(recipientPage.getByTestId('team-member-detail')).toContainText('viewer');
		await expect(recipientPage.getByTestId('team-member-detail-role')).toHaveCount(0);
		await expect(recipientPage.getByTestId('team-member-remove')).toHaveCount(0);
		await holdProofState(recipientPage);
		const removedAfter = new Date().toISOString();
		await page.getByRole('checkbox', { name: /lose access/i }).click();
		const removed = page.waitForResponse(
			(response: Response) =>
				apiResponse(response, 'POST', /\/members\/[^/]+\/remove$/) && response.ok()
		);
		await page.getByTestId('team-member-remove').click();
		await removed;
		const removalEmail = await inbox!.waitForMessage({
			sentTo: member.email,
			subjectContains: 'Team access ended',
			receivedAfter: removedAfter
		});
		expect(`${removalEmail.text.body}\n${removalEmail.html.body}`).not.toContain(teamName);
		const deniedTeam = await recipientPage.request.get(
			`${teamApiOrigin}/v1/teams/${encodeURIComponent(teamId)}`
		);
		expect(deniedTeam.status()).toBe(404);
		expect(await deniedTeam.json()).toMatchObject({ detail: 'Team not found' });
		await recipientPage.goto(secureUrl!.split('#')[0]);
		await expect(recipientPage.getByTestId('team-invite-missing-key')).toBeVisible();
		await holdProofState(recipientPage);
	} catch (error) {
		flowError = error;
	} finally {
		try {
			await memberContext?.close();
			if (recipientVideo) {
				await testInfo.attach('recipient-video', {
					path: await recipientVideo.path(),
					contentType: 'video/webm'
				});
			}
		} catch (error) {
			cleanupErrors.push(error);
		}
		if (teamId && teamApiOrigin) {
			try {
				const deleted = await page.request.delete(
					`${teamApiOrigin}/v1/teams/${encodeURIComponent(teamId)}`
				);
				expect(deleted.ok(), `Team cleanup failed with ${deleted.status()}`).toBe(true);
			} catch (error) {
				cleanupErrors.push(error);
			}
		}
		try {
			const ownerVideo = page.video();
			await page.close();
			if (ownerVideo) {
				await testInfo.attach('owner-video', {
					path: await ownerVideo.path(),
					contentType: 'video/webm'
				});
			}
		} catch (error) {
			cleanupErrors.push(error);
		}
	}
	if (flowError || cleanupErrors.length) {
		throw new AggregateError(
			[...(flowError ? [flowError] : []), ...cleanupErrors],
			'Team invite flow or cleanup failed'
		);
	}
});
