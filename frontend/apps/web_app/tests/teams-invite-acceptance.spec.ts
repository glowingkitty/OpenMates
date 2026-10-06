/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
export {};
import type { Browser, Page, Response } from '@playwright/test';
const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { createSignupEmailClient, getTestAccount } = require('./signup-flow-helpers');

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
	const teamId = String((await (await created).json()).team.team_id);
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

	const memberContext = await browser.newContext({
		baseURL: new URL(secureUrl!).origin,
		recordVideo: { dir: testInfo.outputPath('recipient-video') }
	});
	let flowError: unknown;
	let cleanupError: unknown;
	let recipientVideo: ReturnType<Page['video']> | undefined;
	try {
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
		await loginToTestAccount(recipientPage, undefined, undefined, { credentials: member });
		await recipientPage.goto(secureUrl!.split('#')[0]);
		await expect(recipientPage.getByTestId('team-invite-recipient-email')).toBeVisible();
		await recipientPage.getByTestId('team-invite-recipient-email').fill(owner.email);
		await recipientPage.getByTestId('team-invite-accept').click();
		await expect(recipientPage.getByTestId('team-invite-error')).toBeVisible();
		await recipientPage.getByTestId('team-invite-recipient-email').fill(member.email);
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
		await recipientPage.goto(secureUrl!.split('#')[0]);
		await expect(recipientPage.getByTestId('team-invite-missing-key')).toBeVisible();
	} catch (error) {
		flowError = error;
	} finally {
		try {
			await memberContext.close();
			if (recipientVideo) {
				await testInfo.attach('recipient-video', {
					path: await recipientVideo.path(),
					contentType: 'video/webm'
				});
			}
		} catch (error) {
			cleanupError = error;
		}
	}
	if (flowError) throw flowError;
	if (cleanupError) throw cleanupError;
});
