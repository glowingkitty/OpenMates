/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
export {};
import { randomBytes } from 'node:crypto';
import type { Browser, Page, TestInfo } from '@playwright/test';
import type { ProofStep } from './cli-tui-proof-helpers';
import { createDirectChatFixture } from './helpers/direct-chat-fixture';
import { pairDirectChatCli, readDirectChatOffline } from './helpers/direct-chat-cli';

const { test, expect, captureProof, installRecorderDeps, requireIsolatedCliBuild,
	workflowApiUrl, createWorkflowCliHome } = require('./cli-tui-proof-helpers');
const { removeWorkflowCliHome, runWorkflowCliJson } = require('./helpers/workflow-cli-e2e-helpers');
const { waitForChatReady } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

const PROFILE = 'cli-terminal';
const proofContract = {
	id: 'cli-tui-team-direct-chat-real-terminal',
	title: 'Private Team direct chat in OpenMates CLI',
	surface: 'cli', devices: [PROFILE],
	transcript: [
		{ id: 'private-chat', text: 'A CLI-created Team direct chat opens in the terminal with its decrypted participant message.', checkpoint: 'private-chat', devices: [PROFILE] },
		{ id: 'team-scope', text: 'The terminal sidebar shows the private conversation in Team context.', checkpoint: 'sidebar-open', devices: [PROFILE] },
	],
	assertions: [
		{ id: 'teams.direct-chat.participant-isolation', checkpoint: 'private-chat', visual: 'The real terminal decrypts the participant-only Team DM.', devices: [PROFILE] },
		{ id: 'teams.direct-chat.member-entry-and-notifications', checkpoint: 'sidebar-open', visual: 'The private DM appears in its Team chat list.', devices: [PROFILE] },
	],
	tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1200, maximumHoldMs: 5000 },
};

// contract-test: direct surface=cli assertions=teams.direct-chat.account-key-exchange,teams.direct-chat.participant-isolation,teams.direct-chat.member-entry-and-notifications
test('opens a CLI-created Team DM on web and reads a web-created Team DM in CLI and TUI', async (
	{ page, browser }: { page: Page; browser: Browser }, testInfo: TestInfo
) => {
	test.setTimeout(300_000);
	const scenarioTag = Array.from(randomBytes(12), byte => String.fromCharCode(97 + byte % 26)).join('');
	test.skip(process.env.GITHUB_ACTIONS !== 'true' || process.env.RUNNER_ENVIRONMENT !== 'github-hosted' ||
		process.env.CI_TEST_MODE !== 'e2e', 'Requires isolated GitHub product stack');
	const accounts = [getTestAccount(1), getTestAccount(2), getTestAccount(3)];
	test.skip(accounts.some(account => !account.email || !account.password) ||
		new Set(accounts.map(account => account.email)).size !== 3, 'Three isolated accounts required');
	await skipIfFeaturesDisabled(test, page, ['platform:teams']);
	const candidateCli = requireIsolatedCliBuild();
	installRecorderDeps();
	const apiUrl = workflowApiUrl();
	const home = createWorkflowCliHome('team-direct-chat');
	let fixture: Awaited<ReturnType<typeof createDirectChatFixture>> | undefined;
	let runError: unknown;
	try {
		fixture = await createDirectChatFixture(browser, page, testInfo,
			accounts as Array<{ email: string; password: string; otpKey?: string }>);
		const { teamId, owner, alice, bob } = fixture;
		await pairDirectChatCli(alice.page, apiUrl, home, candidateCli);
		const cliLine = `Please open our private Team chat for Bob ${scenarioTag}`;
		const cliCreated = await runWorkflowCliJson(apiUrl, home,
			['teams', 'member', 'message', teamId, bob.userHash!, cliLine], 'create Team DM from CLI');
		const cliChatId = String(cliCreated.chat_id);
		expect(cliChatId).toBeTruthy();
		expect(cliCreated.chat.chatVisibility).toBe('direct');
		expect(cliCreated.chat.title).toBe('Private Team message');
		expect(new Set(cliCreated.chat.participantUserHashes)).toEqual(new Set([alice.userHash, bob.userHash]));
		await bob.page.goto(getE2EDebugUrl(`/#chat-id=${encodeURIComponent(cliChatId)}&team-id=${encodeURIComponent(teamId)}`));
		await waitForChatReady(bob.page);
		await expect(bob.page.getByTestId('remote-human-message').filter({ hasText: cliLine })).toBeVisible({ timeout: 60_000 });
		const ownerList = await owner.page.request.get(`${fixture.apiOrigin}/v1/chats?team_id=${teamId}&limit=100`);
		expect(ownerList.ok()).toBe(true);
		expect((await ownerList.json()).chats.map((chat: any) => chat.id)).not.toContain(cliChatId);
		const ownerWindow = await owner.page.request.get(`${fixture.apiOrigin}/v1/chats/${cliChatId}/messages/window?team_id=${teamId}&limit=100`);
		expect([403, 404]).toContain(ownerWindow.status());

		// Owner's membership ID comes from the Team list; it is not a participant in the first DM.
		const members = await alice.page.request.get(`${fixture.apiOrigin}/v1/teams/${teamId}/members`);
		expect(members.ok()).toBe(true);
		const ownerMembership = (await members.json()).members.find((member: any) => member.role === 'owner');
		expect(ownerMembership?.user_id).toBeTruthy();
		await alice.page.goto(getE2EDebugUrl(`/#settings/teams/${teamId}/members/${ownerMembership.user_id}`));
		await expect(alice.page.getByTestId('team-member-message')).toBeVisible();
		const webCreated = alice.page.waitForResponse(response => response.request().method() === 'POST' &&
			new URL(response.url()).pathname === `/v1/teams/${teamId}/direct-chats` && response.ok());
		await alice.page.getByTestId('team-member-message').click();
		const webChat = (await (await webCreated).json()).chat;
		const webChatId = String(webChat.id ?? webChat.chat_id);
		expect(webChatId).toBeTruthy();
		const webLine = `Please review my private Team note ${scenarioTag}`;
		const field = alice.page.getByTestId('message-field').last();
		const { fillMessageEditor } = require('./helpers/chat-test-helpers');
		await fillMessageEditor(alice.page, field.getByTestId('message-editor'), webLine);
		await field.locator('[data-action="send-message"]').click();
		await expect(alice.page.getByTestId('message-user').filter({ hasText: webLine })).toBeVisible();
		// The local bubble is optimistic. Establish the server commit boundary before
		// asking a separate CLI process to read the newly created conversation.
		let committedRows = 0;
		await expect.poll(async () => {
			const window = await alice.page.request.get(`${fixture!.apiOrigin}/v1/chats/${webChatId}/messages/window?team_id=${teamId}&limit=100`);
			if (!window.ok()) return 0;
			const body = await window.json();
			committedRows = (body.messages ?? []).filter((message: any) => message.role === 'user' && Boolean(message.encrypted_content)).length;
			return committedRows;
		}, { timeout: 45_000 }).toBeGreaterThanOrEqual(1);
		await testInfo.attach('web-dm-commit-before-cli-read', {
			body: JSON.stringify({ committedEncryptedUserRows: committedRows }), contentType: 'application/json'
		});
		const cliRead = await runWorkflowCliJson(apiUrl, home,
			['chats', 'show', webChatId, '--team', teamId], 'read web-created DM in CLI');
		expect(cliRead.chat.id).toBe(webChatId);
		expect(cliRead.chat.chatVisibility).toBe('direct');
		expect(cliRead.chat.title).toBe('Private Team message');
		await testInfo.attach('cli-dm-read-after-server-commit', {
			body: JSON.stringify({ messages: cliRead.messages.length,
				containsExpectedMessage: cliRead.messages.some((message: any) => String(message.content).includes(webLine)) }),
			contentType: 'application/json'
		});
		expect(cliRead.messages.some((message: any) => String(message.content).includes(webLine))).toBe(true);
		const offlineRead = await readDirectChatOffline(apiUrl, home, candidateCli, teamId, webChatId);
		expect(offlineRead.networkAttempts).toBe(0);
		expect(offlineRead.messages.some(message => String(message.content).includes(webLine))).toBe(true);
		const terminalReply = `I read your private Team note ${scenarioTag}`;
		await runWorkflowCliJson(apiUrl, home,
			['chats', 'send', terminalReply, '--chat', webChatId, '--team', teamId], 'reply to web-created DM');
		await owner.page.goto(getE2EDebugUrl(`/#chat-id=${encodeURIComponent(webChatId)}&team-id=${encodeURIComponent(teamId)}`));
		await waitForChatReady(owner.page);
		await expect(owner.page.getByTestId('remote-human-message').filter({ hasText: terminalReply })).toBeVisible({ timeout: 60_000 });

		await runWorkflowCliJson(apiUrl, home, ['teams', 'switch', teamId], 'activate Team in terminal');
		const steps: ProofStep[] = [
			{ name: 'startup', wait_for: 'Chats' },
			{ name: 'members-command', text: '/members' },
			{ name: 'members-open', key: 'Return', wait_for: 'Message · Enter' },
			{ name: 'chat-command', text: `/message ${bob.userHash}` },
			{ name: 'private-chat', key: 'Return', wait_for: cliLine, hold_ms: 1200 },
			{ name: 'sidebar-command', key: 'ctrl+b' },
			{ name: 'sidebar-open', wait_for: 'Private Team message', hold_ms: 1200 },
			{ name: 'exit-command', text: '/exit' },
			{ name: 'exit', key: 'Return' },
		];
		const recording = await captureProof(apiUrl, home, candidateCli, steps, proofContract, testInfo);
		expect(recording.frame('private-chat').join('\n')).toContain(cliLine);
		expect(recording.frame('sidebar-open').join('\n')).toContain('Private Team message');
		await recording.attest();
	} catch (error) { runError = error; }
	finally {
		if (fixture) {
			try { await fixture.close(); } catch (error) { runError = runError ? new AggregateError([runError, error]) : error; }
		}
		removeWorkflowCliHome(home);
	}
	if (runError) throw runError;
});
