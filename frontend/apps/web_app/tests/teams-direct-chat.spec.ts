/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
export {};
import { randomBytes } from 'node:crypto';
import { resolve } from 'node:path';
import type { Browser, Page, Response, TestInfo } from '@playwright/test';
import { createDirectChatFixture } from './helpers/direct-chat-fixture';

const { expect, test } = require('./helpers/cookie-audit');
const { fillMessageEditor, waitForChatReady } = require('./helpers/chat-test-helpers');
const { waitForHydratedChat } = require('./helpers/chat-hydration');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

// Account chat identities cannot be reset between Playwright retries; each provisioned
// account must exercise the secure-pending enrollment transition exactly once.
test.describe.configure({ retries: 0 });

type Frame = { direction: 'sent' | 'received'; type: string; payload: Record<string, any> };

function captureFrames(page: Page, frames: Frame[]): void {
	page.on('websocket', socket => {
		const record = (direction: Frame['direction']) => (frame: { payload: string | Buffer }) => {
				try {
					const message = JSON.parse(String(frame.payload));
					if (message.type && message.payload) frames.push({ direction, type: message.type, payload: message.payload });
				} catch { /* WebSocket control frame. */ }
			};
		socket.on('framesent', record('sent'));
		socket.on('framereceived', record('received'));
	});
}

function apiResponse(response: Response, method: string, path: RegExp): boolean {
	return response.request().method() === method && path.test(new URL(response.url()).pathname);
}

async function sendHumanTurn(page: Page, line: string): Promise<void> {
	const field = page.getByTestId('message-field').last();
	const editor = field.getByTestId('message-editor');
	await fillMessageEditor(page, editor, line);
	await field.locator('[data-action="send-message"]').click();
	await expect(page.getByTestId('message-user').filter({ hasText: line })).toBeVisible({ timeout: 45_000 });
}

async function assertParticipantWindow(page: Page, apiOrigin: string, teamId: string, chatId: string, lines: string[]): Promise<void> {
	let response: Awaited<ReturnType<Page['request']['get']>> | undefined;
	await expect.poll(async () => {
		response = await page.request.get(`${apiOrigin}/v1/chats/${chatId}/messages/window?team_id=${teamId}&limit=100`);
		return response.ok() ? ((await response.json()).messages?.length ?? 0) : 0;
	}, { timeout: 45_000 }).toBeGreaterThanOrEqual(lines.length);
	const body = await response!.json();
	for (const line of lines) expect(JSON.stringify(body)).not.toContain(line);
	for (const row of body.messages.filter((message: any) => message.role === 'user')) {
		expect(row.encrypted_content).toBeTruthy();
		expect(row.content).toBeUndefined();
	}
}

async function assertThirdMemberDenied(page: Page, apiOrigin: string, teamId: string, chatId: string, embedId?: string): Promise<void> {
	const list = await page.request.get(`${apiOrigin}/v1/chats?team_id=${teamId}&limit=100`);
	expect(list.ok()).toBe(true);
	expect((await list.json()).chats.map((chat: any) => chat.id)).not.toContain(chatId);
	const window = await page.request.get(`${apiOrigin}/v1/chats/${chatId}/messages/window?team_id=${teamId}&limit=100`);
	expect([403, 404]).toContain(window.status());
	if (embedId) {
		const embed = await page.request.get(`${apiOrigin}/v1/embeds/chats/${chatId}/embeds/${embedId}?team_id=${teamId}`);
		expect([403, 404]).toContain(embed.status());
	}
}

async function waitForPrivateMail(recipient: string, excluded: string, chatId: string, since: number): Promise<void> {
	const base = process.env.OPENMATES_CI_MAILPIT_URL;
	if (!base) throw new Error('Private notification proof requires isolated Mailpit capture');
	let recipientMessage: any;
	let excludedMessage: any;
	await expect.poll(async () => {
		const listing = await fetch(`${base}/api/v1/messages?limit=100`, { signal: AbortSignal.timeout(10_000) });
		expect(listing.ok).toBe(true);
		const messages = (await listing.json()).messages ?? [];
		const candidates = messages.filter((message: any) => new Date(message.Created).getTime() >= since - 2_000 &&
			/message|OpenMates/i.test(String(message.Subject)));
		for (const candidate of candidates) {
			const full = await fetch(`${base}/api/v1/message/${encodeURIComponent(candidate.ID)}`, { signal: AbortSignal.timeout(10_000) });
			if (!full.ok) continue;
			const message = await full.json();
			if (!`${message.Text ?? ''}\n${message.HTML ?? ''}`.includes(chatId)) continue;
			const addresses = (message.To ?? []).map((to: any) => String(to.Address).toLowerCase());
			if (addresses.includes(recipient.toLowerCase())) recipientMessage = message;
			if (addresses.includes(excluded.toLowerCase())) excludedMessage = message;
		}
		return Boolean(recipientMessage);
	}, { timeout: 90_000 }).toBe(true);
	expect(excludedMessage, 'A third Team member received a private-chat notification').toBeUndefined();
}

// contract-test: direct surface=gui.web assertions=teams.direct-chat.account-key-exchange,teams.direct-chat.participant-isolation,teams.direct-chat.member-entry-and-notifications
test('keeps a Team DM between two members across reload, image upload, and removal', async (
	{ page, browser }: { page: Page; browser: Browser }, testInfo: TestInfo
) => {
	test.setTimeout(360_000);
	const scenarioTag = Array.from(randomBytes(12), byte => String.fromCharCode(97 + byte % 26)).join('');
	const accounts = [getTestAccount(1), getTestAccount(2), getTestAccount(3)];
	test.skip(accounts.some(account => !account.email || !account.password) ||
		new Set(accounts.map(account => account.email)).size !== 3, 'Three isolated accounts required');
	await skipIfFeaturesDisabled(test, page, ['platform:teams']);
	const ownerFrames: Frame[] = [], aliceFrames: Frame[] = [], bobFrames: Frame[] = [];
	captureFrames(page, ownerFrames);
	const fixture = await createDirectChatFixture(browser, page, testInfo, accounts as Array<{ email: string; password: string; otpKey?: string }>,
		{ withholdBobIdentity: true, onActorPage: (label, actorPage) =>
			captureFrames(actorPage, label === 'alice' ? aliceFrames : bobFrames) });
	const { teamId, apiOrigin, alice, bob } = fixture;
	let runError: unknown;
	try {
		const bobKeyBefore = await alice.page.request.get(`${apiOrigin}/v1/teams/${teamId}/members/${bob.userHash}/chat-encryption-key`);
		expect(bobKeyBefore.status()).toBe(404);
		await alice.page.goto(getE2EDebugUrl(`/#settings/teams/${teamId}/members/${bob.userId}`));
		await expect(alice.page.getByTestId('team-member-detail')).toBeVisible();
		await expect(alice.page.getByText('Only you and this member can read this chat.')).toBeVisible();
		const prematureCreates: string[] = [];
		alice.page.on('request', request => {
			if (request.method() === 'POST' && /\/v1\/teams\/[^/]+\/direct-chats$/.test(new URL(request.url()).pathname))
				prematureCreates.push(request.postData() ?? '');
		});
		await alice.page.getByTestId('team-member-message').click();
		await expect(alice.page.getByRole('alert')).toContainText('Secure messaging setup is pending');
		expect(prematureCreates).toEqual([]);

		await bob.page.unroute('**/v1/account/chat-encryption-key');
		await bob.page.reload({ waitUntil: 'domcontentloaded' });
		await waitForChatReady(bob.page);
		await expect.poll(async () => {
			const ownKey = await bob.page.request.get(`${apiOrigin}/v1/account/chat-encryption-key`);
			return ownKey.ok() && Boolean((await ownKey.json()).key?.key_id);
		}, { timeout: 30_000 }).toBe(true);
		const bobKey = await alice.page.request.get(`${apiOrigin}/v1/teams/${teamId}/members/${bob.userHash}/chat-encryption-key`);
		expect(bobKey.ok()).toBe(true);
		expect(JSON.stringify(await bobKey.json())).not.toContain(accounts[2].password);
		await alice.page.reload({ waitUntil: 'domcontentloaded' });
		await alice.page.goto(getE2EDebugUrl(`/#settings/teams/${teamId}/members/${bob.userId}`));
		const creationStart = [ownerFrames.length, aliceFrames.length, bobFrames.length];
		const created = alice.page.waitForResponse(response => apiResponse(response, 'POST', new RegExp(`^/v1/teams/${teamId}/direct-chats$`)) && response.ok());
		await alice.page.getByTestId('team-member-message').click();
		const createResponse = await created;
		const requestBody = createResponse.request().postDataJSON();
		const chat = (await createResponse.json()).chat;
		const chatId = String(chat.id ?? chat.chat_id);
		expect(chatId).toBeTruthy();
		expect(chat.chat_visibility).toBe('direct');
		expect(new Set(chat.participant_user_hashes)).toEqual(new Set([alice.userHash, bob.userHash]));
		expect(Object.keys(requestBody.participant_key_envelopes).sort()).toEqual([alice.userHash, bob.userHash].sort());
		for (const envelope of Object.values(requestBody.participant_key_envelopes) as Array<any>) {
			expect(envelope.key_id).toBeTruthy();
			expect(envelope.encrypted_chat_key).toBeTruthy();
		}
		expect(requestBody.encrypted_title).toBeTruthy();
		expect(JSON.stringify(requestBody)).not.toContain('Private Team message');
		expect(JSON.stringify(chat)).not.toContain(accounts[2].email);
		expect(chat.encrypted_chat_key).toMatch(/^OMDM1\./);
		await waitForChatReady(alice.page);
		await expect(alice.page.getByTestId('direct-chat-badge')).toContainText('Only you and this member can read this chat.');
		await expect.poll(() => bobFrames.slice(creationStart[2]).some(frame => frame.direction === 'received' &&
			frame.type === 'team_chat_created' && (frame.payload.chat?.id ?? frame.payload.chat?.chat_id) === chatId), { timeout: 30_000 }).toBe(true);
		expect(ownerFrames.slice(creationStart[0]).filter(frame => frame.direction === 'received' &&
			(frame.payload.chat_id === chatId || (frame.payload.chat?.id ?? frame.payload.chat?.chat_id) === chatId))).toEqual([]);
		await bob.page.goto(getE2EDebugUrl(`/#chat-id=${encodeURIComponent(chatId)}&team-id=${encodeURIComponent(teamId)}`));
		await waitForChatReady(bob.page);
		await expect(bob.page.getByTestId('direct-chat-badge')).toContainText('Only you and this member can read this chat.', { timeout: 30_000 });
		const aliceLine = `Please review our private schedule for Bob ${scenarioTag}`;
		const bobLine = `I reviewed the private schedule for Alice ${scenarioTag}`;
		const start = [ownerFrames.length, aliceFrames.length, bobFrames.length];
		await sendHumanTurn(alice.page, aliceLine);
		await assertParticipantWindow(alice.page, apiOrigin, teamId, chatId, [aliceLine]);
		await expect(bob.page.getByTestId('remote-human-message').filter({ hasText: aliceLine })).toBeVisible({ timeout: 45_000 });
		await sendHumanTurn(bob.page, bobLine);
		await expect(alice.page.getByTestId('remote-human-message').filter({ hasText: bobLine })).toBeVisible({ timeout: 45_000 });
		for (const [actor, own, remote] of [[alice.page, aliceLine, bobLine], [bob.page, bobLine, aliceLine]] as const) {
			await expect(actor.getByTestId('message-user').filter({ hasText: own })).toBeVisible();
			await expect(actor.getByTestId('remote-human-message').filter({ hasText: remote }).getByTestId('remote-human-name')).not.toBeEmpty();
			await assertParticipantWindow(actor, apiOrigin, teamId, chatId, [aliceLine, bobLine]);
		}
		await assertThirdMemberDenied(page, apiOrigin, teamId, chatId);
		const aliceSent = aliceFrames.slice(start[1]).filter(frame => frame.direction === 'sent' && frame.type === 'chat_message_added' && frame.payload.chat_id === chatId);
		const bobSent = bobFrames.slice(start[2]).filter(frame => frame.direction === 'sent' && frame.type === 'chat_message_added' && frame.payload.chat_id === chatId);
		expect(aliceSent.length).toBeGreaterThan(0);
		expect(bobSent.length).toBeGreaterThan(0);
		for (const frame of [...aliceSent, ...bobSent]) {
			expect(frame.payload.team_ai_invocation).toBeUndefined();
			expect(frame.payload.message.encrypted_content).toBeTruthy();
			expect(JSON.stringify(frame.payload)).not.toContain(aliceLine);
			expect(JSON.stringify(frame.payload)).not.toContain(bobLine);
		}
		expect(ownerFrames.slice(start[0]).filter(frame => frame.direction === 'received' && frame.payload.chat_id === chatId)).toEqual([]);
		expect([...aliceFrames.slice(start[1]), ...bobFrames.slice(start[2])]
			.filter(frame => /ai_task_initiated|team_ai_processing|team_ai_response_completed/.test(frame.type) && frame.payload.chat_id === chatId)).toEqual([]);

		const uploaded = alice.page.waitForResponse(response => apiResponse(response, 'POST', /^\/v1\/upload\/file$/) && response.ok());
		await alice.page.getByTestId('message-file-input').setInputFiles(resolve(__dirname, 'fixtures/humans_group.jpg'));
		const uploadBody = await (await uploaded).json();
		await expect(alice.page.getByTestId('message-field').last().getByTestId('embed-preview')).toHaveAttribute('data-status', 'finished', { timeout: 90_000 });
		const imageLine = `Here is our private image for Bob ${scenarioTag}`;
		// The generic text helper's select-all fallback would remove the rich image node.
		const imageEditor = alice.page.getByTestId('message-field').last().getByTestId('message-editor');
		await imageEditor.press('Control+End');
		await alice.page.keyboard.insertText(imageLine);
		await expect(imageEditor.getByTestId('embed-preview')).toHaveAttribute('data-status', 'finished');
		await alice.page.getByTestId('message-field').last().locator('[data-action="send-message"]').click();
		const bobImage = bob.page.getByTestId('remote-human-message').filter({ hasText: imageLine }).getByTestId('embed-preview').getByRole('img', { name: 'humans_group.jpg' });
		await expect(bobImage).toBeVisible({ timeout: 60_000 });
		await expect.poll(() => bobImage.evaluate((image: HTMLImageElement) => image.naturalWidth)).toBeGreaterThan(0);
		const recipientEmbed = await bob.page.request.get(`${apiOrigin}/v1/embeds/chats/${chatId}/embeds/${uploadBody.embed_id}?team_id=${teamId}`);
		expect(recipientEmbed.ok()).toBe(true);
		expect((await recipientEmbed.json()).embed.encrypted_content).toBeTruthy();
		await assertThirdMemberDenied(page, apiOrigin, teamId, chatId, uploadBody.embed_id);
		const coldIdentityRequests: string[] = [];
		await alice.page.route('**/v1/account/chat-encryption-key', route => {
			coldIdentityRequests.push(route.request().method());
			return route.abort();
		});
		await alice.page.reload({ waitUntil: 'domcontentloaded' });
		await waitForChatReady(alice.page);
		await waitForHydratedChat(alice.page, chatId, testInfo,
			alice.page.getByTestId('remote-human-message').filter({ hasText: bobLine }));
		await expect(alice.page.getByTestId('message-user').filter({ hasText: aliceLine })).toBeVisible();
		expect(coldIdentityRequests, 'A cached direct-chat identity still requested the account key after reload').toEqual([]);
		await alice.page.unroute('**/v1/account/chat-encryption-key');
		await bob.page.reload({ waitUntil: 'domcontentloaded' });
		await waitForChatReady(bob.page);
		await waitForHydratedChat(bob.page, chatId, testInfo,
			bob.page.getByTestId('remote-human-message').filter({ hasText: aliceLine }));
		await expect(bob.page.getByTestId('remote-human-message').filter({ hasText: imageLine }).getByTestId('embed-preview')).toBeVisible();
		// The recipient leaves the chat before the next committed message. The real
		// notification worker must deliver the DM link only to that participant.
		await bob.page.close();
		const notificationSince = Date.now();
		const notificationLine = `Please check our private update for Bob ${scenarioTag}`;
		await sendHumanTurn(alice.page, notificationLine);
		await waitForPrivateMail(accounts[2].email!, accounts[0].email!, chatId, notificationSince);

		// A removed participant loses message, key and artifact access even with the old URL.
		await page.goto(getE2EDebugUrl(`/#settings/teams/${teamId}/members/${bob.userId}`));
		await page.getByRole('checkbox', { name: /lose access/i }).click();
		const removed = page.waitForResponse(response => apiResponse(response, 'POST', /\/members\/[^/]+\/remove$/) && response.ok());
		await page.getByTestId('team-member-remove').click();
		await removed;
		const removedList = await bob.context!.request.get(`${apiOrigin}/v1/chats?team_id=${teamId}&limit=100`);
		expect([403, 404]).toContain(removedList.status());
		const removedWindow = await bob.context!.request.get(`${apiOrigin}/v1/chats/${chatId}/messages/window?team_id=${teamId}&limit=100`);
		expect([403, 404]).toContain(removedWindow.status());
		const removedKey = await bob.context!.request.get(`${apiOrigin}/v1/teams/${teamId}/members/${alice.userHash}/chat-encryption-key`);
		expect([403, 404]).toContain(removedKey.status());
		const removedEmbed = await bob.context!.request.get(`${apiOrigin}/v1/embeds/chats/${chatId}/embeds/${uploadBody.embed_id}?team_id=${teamId}`);
		expect([403, 404]).toContain(removedEmbed.status());
	} catch (error) { runError = error; }
	finally {
		try { await fixture.close(); } catch (error) { runError = runError ? new AggregateError([runError, error]) : error; }
	}
	if (runError) throw runError;
});
