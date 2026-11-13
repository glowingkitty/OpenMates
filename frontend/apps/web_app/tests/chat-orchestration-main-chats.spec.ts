/**
 * Chat orchestration E2E (TASK-2269): any chat starts and coordinates other main chats.
 * Real stack, real AI, no mocks; dev server only, run through
 * scripts/chat_orchestration_web_real_test.py (personal dev test account, leases). Plan: docs/plans/chat-orchestration-main-chats/plan.yml
 * Spec: specifications/features/chat-orchestration/specification.yml
 *
 * 1. Ask a new chat to start a second chat with a brief and report back.
 * 2. The creator chat shows a "Started chat" event; clicking it opens the spawned chat,
 *    whose first message is the brief and which links back to its creator.
 * 3. The spawned chat answers; via the creator link the creator shows a report and/or finished event.
 * 4. Cross-chat safety: the automatic turn that interprets the report writes nothing to the spawned
 *    chat; a follow-up the user asks for is sent and shows "Sent to" in the creator chat, and the
 *    spawned chat shows the message and its own "Reported to" event.
 *
 * REQUIRED ENV VARS: OPENMATES_TEST_ACCOUNT_EMAIL / _PASSWORD / _OTP_KEY, PLAYWRIGHT_TEST_BASE_URL
 */

import {
	test,
	expect,
	attachConsoleListeners,
	attachNetworkListeners,
	allowConsoleErrorPatterns
} from './console-monitor';
import {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	getTestAccount
} from './signup-flow-helpers';
import {
	loginToTestAccount,
	startNewChat,
	sendMessage,
	waitForAssistantMessage,
	deleteActiveChat
} from './helpers/chat-test-helpers';
import { skipWithoutCredentials } from './helpers/env-guard';

// eslint-disable-next-line @typescript-eslint/no-require-imports -- the proof helper is CommonJS like in the other real specs
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount(1);

const proofContract = defineVideoProof({
	id: 'chat-orchestration-main-chats',
	title: 'A chat starts another main chat, follows its work and receives its report',
	surface: 'web',
	devices: ['web-laptop'],
	domain: 'app.dev.openmates.org',
	transcript: [
		{ id: 'started', text: 'The creator chat shows a Started chat event for the new chat.', checkpoint: 'creator-started-event', devices: ['web-laptop'] },
		{ id: 'spawned', text: 'Tapping the event opens the spawned chat: the brief is its first message and it links back to its creator.', checkpoint: 'spawned-chat-opened', devices: ['web-laptop'] },
		{ id: 'answer', text: 'The spawned chat answers the brief like any chat.', checkpoint: 'spawned-chat-answer', devices: ['web-laptop'] },
		{ id: 'report', text: 'Back in the creator chat a report or finished event from the spawned chat appears.', checkpoint: 'creator-report-or-finished', devices: ['web-laptop'] },
		{ id: 'follow-up', text: 'The automatic answer sent nothing on its own; the user asks for a follow-up and the creator chat shows Sent to.', checkpoint: 'creator-sent-follow-up', devices: ['web-laptop'] },
		{ id: 'both-sides', text: 'The spawned chat shows the follow-up message and its own Reported to event.', checkpoint: 'spawned-both-sides', devices: ['web-laptop'] }
	],
	assertions: [
		{ id: 'chat_orchestration.started_event', checkpoint: 'creator-started-event', visual: 'A compact system event reads Started chat with the new chat title.', devices: ['web-laptop'] },
		{ id: 'chat_orchestration.spawned_chat', checkpoint: 'spawned-chat-opened', visual: 'The spawned chat shows the brief as its first message and a Started from link.', devices: ['web-laptop'] },
		{ id: 'chat_orchestration.answer', checkpoint: 'spawned-chat-answer', visual: 'An assistant answer listing kitchen floor tiles is visible in the spawned chat.', devices: ['web-laptop'] },
		{ id: 'chat_orchestration.report', checkpoint: 'creator-report-or-finished', visual: 'The creator chat shows a Report from or finished event for the spawned chat.', devices: ['web-laptop'] },
		{ id: 'chat_orchestration.sent_follow_up', checkpoint: 'creator-sent-follow-up', visual: 'The creator chat shows a Sent to event with the follow-up text.', devices: ['web-laptop'] },
		{ id: 'chat_orchestration.visible_both_sides', checkpoint: 'spawned-both-sides', visual: 'The spawned chat shows the follow-up message and a Reported to event.', devices: ['web-laptop'] }
	],
	tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 }
});

const PROMPT =
	"Start a new chat titled 'Kitchen tile quotes' with the brief: list three kinds of kitchen floor tiles " +
	'in one short sentence each, then report back to me.';

const FOLLOW_UP = 'Please tell the chat you started to also name one tile that suits underfloor heating.';

// Old chats of the shared dev account fail output recovery at login; that is unrelated account
// history. The orchestrated chats are still checked: any console error naming them fails the test.
const ACCOUNT_HISTORY_NOISE = [
	/\[ChatSyncService:Recovery\] Output recovery failed: .*Canonical store_embed storage was rejected/,
	/\[WebSocketService\] Connection failed, cannot send message: \{type: get_chat_model_preference/
];

// contract-test: direct surface=gui.web assertions=chat-orchestration.spawn.main-chat-is-normal,chat-orchestration.events.creator-system-events,chat-orchestration.report.creator-skill,chat-orchestration.status.automatic,chat-orchestration.safety.user-requested-writes-only,chat-orchestration.safety.visible-both-sides
test('a chat starts another main chat, follows its work and receives its report', async (
	{ page }: { page: any },
	testInfo: any
) => {
	attachConsoleListeners(page);
	attachNetworkListeners(page);
	allowConsoleErrorPatterns(ACCOUNT_HISTORY_NOISE);
	const consoleErrors: string[] = [];
	page.on('console', (msg: any) => {
		if (msg.type() === 'error') consoleErrors.push(msg.text());
	});
	test.slow();
	test.setTimeout(600000);

	const log = createSignupLogger('CHAT_ORCHESTRATION');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'chat-orchestration' });
	const proof = createVideoProofRuntime(proofContract, {
		device: 'web-laptop',
		attach: testInfo.attach.bind(testInfo),
		captureFrame: () => page.screenshot({ type: 'png' })
	});
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	await archiveExistingScreenshots(log);

	await loginToTestAccount(page, log, screenshot);
	await startNewChat(page, log);
	await sendMessage(page, PROMPT, log, screenshot, 'creator-request');
	await expect(page).toHaveURL(/chat-id=[0-9a-f]{8}-/, { timeout: 30000 });
	const chatIdOf = (url: string) => url.match(/chat-id=([0-9a-f-]{36})/)?.[1];
	const creatorChatId = chatIdOf(page.url());
	expect(creatorChatId).toBeTruthy();

	// The creator chat shows the "Started chat" event once the device spawned the chat.
	const startedEvent = page
		.getByTestId('chat-orchestration-event')
		.filter({ hasText: /Started chat/ })
		.first();
	await expect(startedEvent).toBeVisible({ timeout: 240000 });
	await screenshot(page, 'creator-started-event');
	await proof.checkpoint('creator-started-event');

	// Open the spawned chat: the brief is its first user message and it links back to the creator.
	await startedEvent.click();
	await expect(page.getByTestId('chat-creator-link')).toBeVisible({ timeout: 60000 });
	await expect(page.getByTestId('message-user').first()).toContainText(/kitchen floor tiles/i, {
		timeout: 60000
	});
	// The URL hash follows the opened chat through an async URL queue: wait for the spawned chat's id.
	await expect
		.poll(() => {
			const id = chatIdOf(page.url());
			return id && id !== creatorChatId ? id : null;
		}, { timeout: 30000 })
		.not.toBeNull();
	const spawnedChatId = chatIdOf(page.url());
	await screenshot(page, 'spawned-chat-opened');
	await proof.checkpoint('spawned-chat-opened');

	await waitForAssistantMessage(page, { which: 'last', logCheckpoint: log });
	await expect(page.getByTestId('stop-processing-button')).not.toBeVisible({ timeout: 180000 });
	await screenshot(page, 'spawned-chat-answer');
	await proof.checkpoint('spawned-chat-answer');

	// Back to the creator via the link: a report and/or finished event follows.
	await page.getByTestId('chat-creator-link').click();
	await expect(page).toHaveURL(new RegExp(`chat-id=${creatorChatId}`), { timeout: 30000 });
	const followUp = page
		.getByTestId('chat-orchestration-event')
		.filter({ hasText: /Report from|finished/ })
		.first();
	await expect(followUp).toBeVisible({ timeout: 240000 });
	await followUp.scrollIntoViewIfNeeded();
	// The brief was sent by the creator, not typed by the user in the spawned chat.
	await expect(
		page.getByTestId('chat-orchestration-event').filter({ hasText: /You wrote/ })
	).toHaveCount(0);
	await screenshot(page, 'creator-report-or-finished');
	await proof.checkpoint('creator-report-or-finished');

	// The automatic turn interprets the report in the creator chat and writes to no other chat.
	await waitForAssistantMessage(page, { which: 'last', logCheckpoint: log });
	await expect(page.getByTestId('stop-processing-button')).not.toBeVisible({ timeout: 180000 });
	const sentEvents = page.getByTestId('chat-orchestration-event').filter({ hasText: /Sent to/ });
	await expect(sentEvents).toHaveCount(0);

	// A follow-up the user explicitly asks for is sent and shows "Sent to" here.
	await sendMessage(page, FOLLOW_UP, log, screenshot, 'creator-follow-up');
	const sentEvent = sentEvents.first();
	await expect(sentEvent).toBeVisible({ timeout: 240000 });
	await sentEvent.scrollIntoViewIfNeeded();
	await expect(sentEvent).toContainText(/underfloor heating/i);
	await screenshot(page, 'creator-sent-follow-up');
	await proof.checkpoint('creator-sent-follow-up');

	// The spawned chat shows the follow-up message and its own "Reported to" event.
	await sentEvent.click();
	await expect(page).toHaveURL(new RegExp(`chat-id=${spawnedChatId}`), { timeout: 30000 });
	await expect(
		page.getByTestId('message-user').filter({ hasText: /underfloor heating/i }).first()
	).toBeVisible({ timeout: 120000 });
	const reportedEvent = page
		.getByTestId('chat-orchestration-event')
		.filter({ hasText: /Reported to/ })
		.first();
	await expect(reportedEvent).toBeVisible({ timeout: 120000 });
	await reportedEvent.scrollIntoViewIfNeeded();
	await screenshot(page, 'spawned-both-sides');
	await proof.checkpoint('spawned-both-sides');
	await expect(page.getByTestId('stop-processing-button')).not.toBeVisible({ timeout: 180000 });
	await page.getByTestId('chat-creator-link').click();
	await expect(page).toHaveURL(new RegExp(`chat-id=${creatorChatId}`), { timeout: 30000 });
	const orchestratedErrors = consoleErrors.filter(
		(text) => text.includes(creatorChatId!) || text.includes(spawnedChatId!)
	);
	expect(orchestratedErrors).toEqual([]);

	// Cleanup: delete the creator chat, then the spawned chat.
	await deleteActiveChat(page, log, screenshot);
	await page.goto(`/#chat-id=${spawnedChatId}`);
	await expect(page.getByTestId('chat-creator-link')).toBeVisible({ timeout: 60000 });
	await deleteActiveChat(page, log, screenshot);
	await screenshot(page, 'done');
});
