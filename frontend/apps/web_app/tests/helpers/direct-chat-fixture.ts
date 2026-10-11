/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
import type { Browser, BrowserContext, Page, TestInfo } from '@playwright/test';

const { expect } = require('./cookie-audit');
const { loginToTestAccount } = require('./chat-test-helpers');
const { getE2EDebugUrl } = require('../signup-flow-helpers');

export type DirectChatActor = {
	page: Page;
	context?: BrowserContext;
	video?: ReturnType<Page['video']>;
	userId?: string;
	userHash?: string;
};

export type DirectChatFixture = {
	teamId: string;
	apiOrigin: string;
	owner: DirectChatActor;
	alice: DirectChatActor;
	bob: DirectChatActor;
	close: () => Promise<void>;
};

function isResponse(response: { request: () => { method: () => string }; url: () => string; ok: () => boolean }, method: string, path: RegExp): boolean {
	return response.request().method() === method && path.test(new URL(response.url()).pathname) && response.ok();
}

/** Creates real Team memberships through fragment-key invites; owner stays outside the DM. */
export async function createDirectChatFixture(
	browser: Browser,
	ownerPage: Page,
	testInfo: TestInfo,
	accounts: Array<{ email: string; password: string; otpKey?: string }>,
	options: { withholdBobIdentity?: boolean; onActorPage?: (label: 'alice' | 'bob', page: Page) => void } = {}
): Promise<DirectChatFixture> {
	if (accounts.length !== 3 || new Set(accounts.map(account => account.email)).size !== 3) {
		throw new Error('Private DM proof requires three distinct isolated accounts');
	}
	const owner: DirectChatActor = { page: ownerPage };
	const actors: DirectChatActor[] = [];
	let teamId = '';
	let apiOrigin = '';
	await loginToTestAccount(ownerPage, undefined, undefined, { credentials: accounts[0] });
	await ownerPage.evaluate(() => Object.defineProperty(navigator, 'clipboard', {
		configurable: true,
		value: { writeText: async (value: string) => { document.body.dataset.secureInvite = value; } }
	}));
	await ownerPage.getByTestId('profile-container').click();
	await ownerPage.getByTestId('settings-teams-item').click();
	await ownerPage.getByTestId('team-create-open').click();
	await ownerPage.getByTestId('team-name-input').fill(`Private DM ${Date.now()}`);
	await ownerPage.getByTestId('team-create-continue').click();
	const created = ownerPage.waitForResponse(response => isResponse(response, 'POST', /^\/v1\/teams$/));
	await ownerPage.getByTestId('team-create-submit').click();
	const createdResponse = await created;
	apiOrigin = new URL(createdResponse.url()).origin;
	teamId = String((await createdResponse.json()).team.team_id);
	const viewport = ownerPage.viewportSize();
	if (!viewport) throw new Error('Recorded browser viewport required');
	const close = async (): Promise<void> => {
		const errors: unknown[] = [];
		if (teamId) {
			try { expect((await ownerPage.request.delete(`${apiOrigin}/v1/teams/${teamId}`)).ok()).toBe(true); }
			catch (error) { errors.push(error); }
		}
		for (const [index, actor] of actors.entries()) {
			try { await actor.context?.close(); }
			catch (error) { errors.push(error); }
			if (actor.video) {
				try { await testInfo.attach(`${index === 0 ? 'alice' : 'bob'}-private-dm-video`, { path: await actor.video.path(), contentType: 'video/webm' }); }
				catch (error) { errors.push(error); }
			}
		}
		if (errors.length) throw new AggregateError(errors, 'Direct chat fixture cleanup failed');
	};

	const invite = async (account: typeof accounts[number], label: 'alice' | 'bob', withholdIdentity: boolean): Promise<DirectChatActor> => {
		await ownerPage.getByTestId('team-members-open').click();
		await ownerPage.getByTestId('team-invite-email-input').fill(account.email);
		const invited = ownerPage.waitForResponse(response => isResponse(response, 'POST', /\/invites$/));
		await ownerPage.getByTestId('team-invite-submit').click();
		const inviteBody = (await (await invited).json()).invite;
		await ownerPage.getByTestId('team-invite-copy-secure-link').click();
		const secureLink = await ownerPage.locator('body').getAttribute('data-secure-invite');
		expect(secureLink).toMatch(/\/teams\/invites\/[^#]+#key=[A-Za-z0-9_-]{43}$/);
		const context = await browser.newContext({ baseURL: new URL(secureLink!).origin, viewport,
			recordVideo: { dir: testInfo.outputPath(`${label}-video`), size: viewport } });
		const page = await context.newPage();
		options.onActorPage?.(label, page);
		const actor: DirectChatActor = { page, context, video: page.video() };
		actors.push(actor);
		if (withholdIdentity) {
			await page.route('**/v1/account/chat-encryption-key', route =>
				route.request().method() === 'PUT' ? route.abort() : route.continue());
		}
		await page.goto(secureLink!);
		await expect.poll(() => page.url()).not.toContain('#key=');
		await loginToTestAccount(page, undefined, undefined, { credentials: account });
		await page.goto(getE2EDebugUrl(`/#settings/teams/invites/${encodeURIComponent(inviteBody.invite_id)}`));
		await page.getByTestId('team-invite-recipient-email').fill(account.email);
		const accepted = page.waitForResponse(response => isResponse(response, 'POST', /\/invites\/[^/]+\/accept$/));
		await page.getByTestId('team-invite-accept').click();
		const body = await (await accepted).json();
		expect(body.status).toBe('accepted');
		actor.userId = body.membership?.user_id;
		expect(actor.userId).toMatch(/^[0-9a-f-]{36}$/);
		if (!actor.userId) throw new Error('Accepted Team invite did not return a member ID');
		const { createHash } = require('node:crypto');
		actor.userHash = createHash('sha256').update(actor.userId).digest('hex');
		await expect(page.getByTestId('team-invite-result')).toContainText(/joined/i);
		await page.getByTestId('icon-button-close').click();
		await expect(page.getByTestId('settings-menu')).not.toHaveClass(/visible/);
		await ownerPage.getByTestId('banner-back-button').click();
		return actor;
	};

	try {
		const alice = await invite(accounts[1], 'alice', false);
		const bob = await invite(accounts[2], 'bob', Boolean(options.withholdBobIdentity));
		return { teamId, apiOrigin, owner, alice, bob, close };
	} catch (error) {
		try { await close(); } catch (cleanupError) { throw new AggregateError([error, cleanupError], 'Direct chat setup and cleanup failed'); }
		throw error;
	}
}
