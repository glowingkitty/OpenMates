/* eslint-disable @typescript-eslint/no-require-imports */
/** Signed provider replay through normal encrypted chat and owner billing APIs. */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { getTestAccount, withLiveMockMarker, installE2EServerContentOverrideGate } = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat, sendMessage, deleteActiveChat } = require('./helpers/chat-test-helpers');
test.describe.configure({ retries: 0 });

const API_URL = process.env.PLAYWRIGHT_TEST_API_URL?.replace(/\/$/, '');
const GROUP = 'native_cache_tools_v1';
const PROMPTS = [
	'@ai-model:gpt-6.1-sol:openai What is the square root of 144?',
	'@ai-model:gpt-6.1-sol:openai Why does twelve make sense as that answer?',
	'@ai-model:gpt-6.1-sol:openai What is the square root of 169?',
	'@ai-model:gpt-6.1-sol:openai How do those two examples help explain square roots?',
	'@ai-model:gpt-6.1-sol:openai What simple rule should I remember from both examples?'
];
const EXPECTED_REPLIES = [
	'The square root is 12.',
	'Yes. Twelve times twelve is 144.',
	'The square root is 13.',
	'Thirteen times thirteen is 169, so the two examples agree.',
	'A square root is the number that multiplies by itself to make the target.'
];
const STANDARD_FAILURE_REPLY = /the AI service encountered an error|sorry, something went wrong|please try again in a moment/i;

async function accountCredits(page: any): Promise<number> {
	const session = await page.evaluate(async (apiUrl: string) => {
		const sessionId = sessionStorage.getItem('session_id');
		if (!sessionId) return { status: 0, success: false, credits: null };
		const response = await fetch(`${apiUrl}/v1/auth/session`, {
			method: 'POST',
			headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
			credentials: 'include',
			cache: 'no-store',
			body: JSON.stringify({ session_id: sessionId })
		});
		const body = await response.json();
		return { status: response.status, success: body.success, credits: body.user?.credits };
	}, API_URL);
	expect(session.status).toBe(200);
	expect(session.success).toBe(true);
	expect(Number.isInteger(session.credits)).toBe(true);
	return session.credits;
}

type PersistEvent = {
	direction: 'sent' | 'received'; type: string; jobId?: string;
	requestId?: string; assistantId?: string; state?: string; committedVersion?: number;
	chatId?: string; turnId?: string; messageId?: string;
	createdAt?: number;
};

function safeProtocolSummary(events: PersistEvent[], currentStage: string, turnsAttempted: number,
	successfulReplies: number, usageStatus: number | null, usageCounts: { all: number; asks: number; math: number } | null,
	observedAssistantIds: string[], observedChatIds: string[], initialWalletCredits: number | null,
	preTurnWalletCredits: number[], standardErrorReplies: boolean[], fixtureAnswerMatches: boolean[],
	billingState: { settledAsks: number; unsettledAsks: number; heldCredits: number | null }) {
	const preflights = events.filter((event) => event.direction === 'sent' && event.type === 'chat_turn_preflight');
	const preflightAcks = events.filter((event) => event.direction === 'received' && event.type === 'chat_turn_preflight_ack');
	const persists = events.filter((event) => event.direction === 'sent' && event.type === 'recovery_job_persist');
	const acks = events.filter((event) => event.direction === 'received' && event.type === 'recovery_job_persisted');
	const matchedAcks = persists.filter((request) => acks.some((ack) => ack.jobId === request.jobId
		&& ack.requestId === request.requestId && ack.state === 'TERMINAL'));
	const orderedSuccessors = preflights.slice(1).filter((preflight, index) => {
		const prior = persists[index];
		if (!prior) return false;
		const ackIndex = events.findIndex((ack) => ack.direction === 'received'
			&& ack.type === 'recovery_job_persisted' && ack.jobId === prior.jobId
			&& ack.requestId === prior.requestId && ack.state === 'TERMINAL');
		return ackIndex >= 0 && ackIndex < events.indexOf(preflight);
	});
	const known = (values: Array<string | undefined>) => values.filter((value): value is string => typeof value === 'string' && value.length > 0);
	const distinct = (values: Array<string | undefined>) => new Set(known(values)).size;
	const turns = Array.from({ length: turnsAttempted }, (_, index) => {
		const assistantId = observedAssistantIds[index];
		const request = persists.find((event) => event.assistantId === assistantId);
		const ack = request && acks.find((event) => event.jobId === request.jobId
			&& event.requestId === request.requestId && event.state === 'TERMINAL');
		const preflight = preflights[index];
		return {
			turn: index + 1, assistant_visible: !!assistantId,
			chat_matches_first: !!observedChatIds[index] && observedChatIds[index] === observedChatIds[0],
			wallet_credits_before_request: preTurnWalletCredits[index] ?? null,
			standard_error_reply: standardErrorReplies[index] ?? null,
			fixture_answer_matches: fixtureAnswerMatches[index] ?? null,
			preflight_sent: !!preflight,
			preflight_chat_matches_visible_chat: !!preflight && preflight.chatId === observedChatIds[index],
			preflight_ack_matches_turn: !!preflight && preflightAcks.some((ack) => ack.turnId === preflight.turnId),
			persist_matches_assistant: !!request,
			persist_chat_matches_visible_chat: !!request && request.chatId === observedChatIds[index],
			terminal_ack_matches_request: !!ack,
			committed_messages_v: ack?.committedVersion ?? null,
		};
	});
	return {
		stage: currentStage, turns_attempted: turnsAttempted, successful_replies: successfulReplies,
		initial_wallet_credits: initialWalletCredits,
		turns,
		usage_http_status: usageStatus, usage_counts: usageCounts, billing_state: billingState,
		preflights_sent: preflights.length, preflight_acks_received: preflightAcks.length,
		persist_requests_sent: persists.length,
		persist_ack_received: acks.length, matching_terminal_acks: matchedAcks.length,
		ordered_successor_preflights: orderedSuccessors.length,
		distinct_chat_ids: distinct([...preflights.map((event) => event.chatId), ...persists.map((event) => event.chatId)]),
		distinct_user_message_ids: distinct(preflights.map((event) => event.messageId)),
		distinct_turn_ids: distinct(preflights.map((event) => event.turnId)),
		distinct_job_ids: distinct(persists.map((event) => event.jobId)),
		distinct_assistant_ids: distinct(persists.map((event) => event.assistantId)),
		distinct_persist_request_ids: distinct(persists.map((event) => event.requestId)),
		terminal_ack_versions: matchedAcks.map((request) => acks.find((ack) => ack.jobId === request.jobId
			&& ack.requestId === request.requestId)?.committedVersion ?? null),
	};
}

async function localChatVersion(page: any, chatId: string): Promise<number | null> {
	return page.evaluate((id: string) => new Promise<number | null>((resolve, reject) => {
		const open = indexedDB.open('chats_db');
		open.onerror = () => reject(open.error);
		open.onsuccess = () => {
			const db = open.result;
			const request = db.transaction('chats', 'readonly').objectStore('chats').get(id);
			request.onerror = () => { db.close(); reject(request.error); };
			request.onsuccess = () => {
				const version = request.result?.messages_v;
				db.close();
				resolve(Number.isSafeInteger(version) ? version : null);
			};
		};
	}), chatId);
}

async function localMessageCreatedAt(page: any, messageId: string): Promise<number | null> {
	return page.evaluate((id: string) => new Promise<number | null>((resolve, reject) => {
		const open = indexedDB.open('chats_db');
		open.onerror = () => reject(open.error);
		open.onsuccess = () => {
			const db = open.result;
			const request = db.transaction('messages', 'readonly').objectStore('messages').get(id);
			request.onerror = () => { db.close(); reject(request.error); };
			request.onsuccess = () => {
				const createdAt = request.result?.created_at;
				db.close();
				resolve(Number.isSafeInteger(createdAt) ? createdAt : null);
			};
		};
	}), messageId);
}

async function waitForCanonicalReply(
	page: any, events: PersistEvent[], assistantId: string, chatId: string,
	allowLaterCommittedTurn = false,
): Promise<void> {
	const matchingRequest = () => events.find((event) =>
		event.direction === 'sent' && event.type === 'recovery_job_persist' && event.assistantId === assistantId
		&& event.jobId && event.requestId);
	await expect.poll(() => matchingRequest()?.requestId ?? '', { timeout: 60_000 }).not.toBe('');
	const request = matchingRequest()!;
	const matchingAck = () => events.find((event) =>
		event.direction === 'received' && event.type === 'recovery_job_persisted'
		&& event.jobId === request.jobId && event.requestId === request.requestId);
	await expect.poll(() => matchingAck()?.state ?? '', { timeout: 60_000 }).toBe('TERMINAL');
	const committedVersion = matchingAck()?.committedVersion;
	expect(Number.isSafeInteger(committedVersion)).toBe(true);
	const localVersion = expect.poll(() => localChatVersion(page, chatId), { timeout: 30_000 });
	if (allowLaterCommittedTurn) await localVersion.toBeGreaterThanOrEqual(committedVersion!);
	else await localVersion.toBe(committedVersion);
}

// contract-test: direct surface=gui.web assertions=billing.usage.receipt-token-breakdown,ai-model-routing.composer.mention-to-exact-selection,chats.completion.lease-fenced
test('native cache keeps selected math tools and settled billing across five chat turns', async ({ page }: { page: any }) => {
	test.setTimeout(480_000);
	test.skip(process.env.GITHUB_ACTIONS !== 'true' || process.env.RUNNER_ENVIRONMENT !== 'github-hosted'
		|| process.env.CI_TEST_MODE !== 'e2e', 'Requires the disposable isolated product stack');
	if (!API_URL || !getTestAccount().email || process.env.E2E_USE_LIVE_MOCKS !== '1') {
		throw new Error('Fresh isolated account and signed zero-provider replay are required');
	}
	const frames: string[] = [];
	const persistEvents: PersistEvent[] = [];
	let currentStage = 'setup';
	let turnsAttempted = 0;
	let successfulReplies = 0;
	let usageStatus: number | null = null;
	let usageCounts: { all: number; asks: number; math: number } | null = null;
	let initialWalletCredits: number | null = null;
	const preTurnWalletCredits: number[] = [];
	const standardErrorReplies: boolean[] = [];
	const fixtureAnswerMatches: boolean[] = [];
	const billingState = { settledAsks: 0, unsettledAsks: 0, heldCredits: null as number | null };
	const observedAssistantIds: string[] = [];
	const observedChatIds: string[] = [];
	page.on('websocket', (socket: any) => {
		const capture = (direction: 'sent' | 'received') => (frame: any) => {
			const raw = String(frame.payload);
			frames.push(raw);
			try {
				const event = JSON.parse(raw);
				if (event.type === 'recovery_job_persist' || event.type === 'recovery_job_persisted'
					|| event.type === 'chat_turn_preflight' || event.type === 'chat_turn_preflight_ack'
					|| (event.type === 'ai_message_update' && event.payload?.is_final_chunk === true
						&& event.payload?.recovery_protocol_version === 1)) {
					persistEvents.push({ direction, type: event.type,
						jobId: event.payload?.job_id ?? event.payload?.recovery_job_id, requestId: event.payload?.request_id,
						assistantId: event.payload?.encrypted_assistant_message?.client_message_id ?? event.payload?.message_id,
						state: event.payload?.state, committedVersion: event.payload?.committed_messages_v,
						chatId: event.payload?.chat_id ?? event.payload?.encrypted_assistant_message?.chat_id,
						turnId: event.payload?.turn_id ?? event.payload?.recovery_turn_id,
							messageId: event.payload?.message_id,
							createdAt: event.type === 'chat_turn_preflight'
								? event.payload?.encrypted_user_message?.created_at
								: event.type === 'recovery_job_persist'
									? event.payload?.encrypted_assistant_message?.created_at
									: event.type === 'ai_message_update' ? event.payload?.created_at : undefined });
				}
			} catch { /* WebSocket control frame. */ }
		};
		socket.on('framesent', capture('sent'));
		socket.on('framereceived', capture('received'));
	});
	await installE2EServerContentOverrideGate(page, 'native-cache-selected-tools');
	await loginToTestAccount(page);
	await startNewChat(page);
	try {
		initialWalletCredits = await accountCredits(page);
		let firstAssistantId: string | null = null;
		let firstChatId: string | null = null;
		for (let index = 0; index < PROMPTS.length; index++) {
			turnsAttempted = index + 1;
			currentStage = `turn_${index + 1}_wallet_check`;
			const preTurnCredits = await accountCredits(page);
			preTurnWalletCredits.push(preTurnCredits);
			expect(preTurnCredits, `turn ${index + 1} requires a positive wallet before its request`).toBeGreaterThan(0);
			currentStage = `turn_${index + 1}_send`;
			await sendMessage(page, withLiveMockMarker(PROMPTS[index], GROUP));
			currentStage = `turn_${index + 1}_reply`;
			await expect(page.getByTestId('message-assistant')).toHaveCount(index + 1, { timeout: 60_000 });
			const assistant = page.getByTestId('message-assistant').last();
			await expect(assistant).toHaveAttribute('data-streaming', 'false', { timeout: 60_000 });
			const assistantId = await assistant.getAttribute('data-message-id');
			const currentChatId = page.url().match(/chat-id=([a-zA-Z0-9-]+)/)?.[1];
			expect(assistantId).toBeTruthy();
			expect(currentChatId).toBeTruthy();
			observedAssistantIds.push(assistantId!);
			observedChatIds.push(currentChatId!);
			const replyText = await assistant.innerText();
			const standardErrorReply = STANDARD_FAILURE_REPLY.test(replyText);
			const fixtureAnswerMatch = replyText.includes(EXPECTED_REPLIES[index]);
			standardErrorReplies.push(standardErrorReply);
			fixtureAnswerMatches.push(fixtureAnswerMatch);
			expect(standardErrorReply, `turn ${index + 1} returned a standard error reply`).toBe(false);
			expect(fixtureAnswerMatch, `turn ${index + 1} did not return its signed fixture answer`).toBe(true);
			successfulReplies = index + 1;
			if (index === 0) {
				// Send turn two as soon as the reply becomes visible. The unit
				// regression proves it queues when the canonical ACK is delayed.
				firstAssistantId = assistantId;
				firstChatId = currentChatId;
				continue;
			}
			currentStage = `turn_${index + 1}_canonical_ack`;
			if (index === 1) await waitForCanonicalReply(page, persistEvents, firstAssistantId!, firstChatId!, true);
			await waitForCanonicalReply(page, persistEvents, assistantId!, currentChatId!);
		}
		currentStage = 'protocol_identity_checks';
		const persisted = persistEvents.filter((event) => event.direction === 'sent' && event.type === 'recovery_job_persist');
		const preflights = persistEvents.filter((event) => event.direction === 'sent' && event.type === 'chat_turn_preflight');
		const preflightAcks = persistEvents.filter((event) => event.direction === 'received' && event.type === 'chat_turn_preflight_ack');
		expect(persisted).toHaveLength(5);
		expect(preflights).toHaveLength(5);
		expect(preflightAcks).toHaveLength(5);
		const chatId = page.url().match(/chat-id=([a-zA-Z0-9-]+)/)?.[1];
		expect(chatId).toBeTruthy();
		expect(preflights.every((event) => event.chatId === chatId)).toBe(true);
		expect(persisted.every((event) => event.chatId === chatId)).toBe(true);
		expect(new Set(preflights.map((event) => event.turnId)).size).toBe(5);
		expect(new Set(preflights.map((event) => event.messageId)).size).toBe(5);
		expect(new Set(persisted.map((event) => event.jobId)).size).toBe(5);
		expect(new Set(persisted.map((event) => event.assistantId)).size).toBe(5);
		expect(new Set(persisted.map((event) => event.requestId)).size).toBe(5);
		for (const event of [...preflights, ...persisted]) {
			expect(event.chatId).toBeTruthy();
		}
		for (const event of preflights) {
			expect(event.turnId).toBeTruthy();
			expect(event.messageId).toBeTruthy();
			expect(preflightAcks.filter((ack) => ack.turnId === event.turnId)).toHaveLength(1);
		}
		for (const event of persisted) {
			expect(event.jobId).toBeTruthy();
			expect(event.assistantId).toBeTruthy();
			expect(event.requestId).toBeTruthy();
		}
		for (const request of persisted) {
			const final = persistEvents.find((event) => event.direction === 'received'
				&& event.type === 'ai_message_update' && event.assistantId === request.assistantId
				&& event.jobId === request.jobId && preflights.some((preflight) => preflight.turnId === event.turnId));
			expect(final, 'persisted assistant must have its matched final stream marker').toBeTruthy();
			expect(Number.isSafeInteger(final?.createdAt)).toBe(true);
			expect(request.createdAt).toBe(final!.createdAt);
			expect(await localMessageCreatedAt(page, request.assistantId!)).toBe(final!.createdAt);
		}
		for (let index = 1; index < 5; index++) {
			const prior = persisted[index - 1];
			expect(Number.isSafeInteger(preflights[index].createdAt)).toBe(true);
			expect(preflights[index].createdAt).toBeGreaterThan(prior.createdAt!);
			const ackIndex = persistEvents.findIndex((event) => event.direction === 'received'
				&& event.type === 'recovery_job_persisted' && event.jobId === prior.jobId && event.requestId === prior.requestId);
			const preflightIndex = persistEvents.indexOf(preflights[index]);
			expect(ackIndex).toBeGreaterThanOrEqual(0);
			expect(preflightIndex).toBeGreaterThan(ackIndex);
		}
		currentStage = 'usage_details';
		const month = new Date().toISOString().slice(0, 7);
		const detail = await page.request.get(`${API_URL}/v1/settings/usage/details`, {
			params: { type: 'chat', identifier: chatId, year_month: month }
		});
		usageStatus = detail.status();
		expect(detail.status()).toBe(200);
		const entries = (await detail.json()).entries;
		const asks = entries.filter((row: any) => row.app_id === 'ai' && row.skill_id === 'ask');
		const math = entries.filter((row: any) => row.app_id === 'math' && row.skill_id === 'calculate');
		usageCounts = { all: entries.length, asks: asks.length, math: math.length };
		billingState.settledAsks = asks.filter((row: any) => row.llm_usage_breakdown?.settlement_state === 'settled').length;
		billingState.unsettledAsks = asks.length - billingState.settledAsks;
		expect(asks).toHaveLength(5);
		const asksByTurn = preflights.map((preflight, index) => {
			const matches = asks.filter((row: any) => row.message_id === preflight.messageId);
			expect(matches, `turn ${index + 1} must have exactly one AI usage row`).toHaveLength(1);
			return matches[0];
		});
		expect(math.length).toBeGreaterThanOrEqual(2);
		expect(new Set(math.map((row: any) => row.id)).size).toBe(math.length);
		for (const row of math) {
			expect(row.chat_id).toBe(chatId);
			expect(Number.isInteger(row.credits)).toBe(true);
			expect(row.credits).toBeGreaterThan(0);
		}
		for (const row of asks) {
			const receipt = row.llm_usage_breakdown;
			expect(receipt.settlement_state).toBe('settled');
			expect(receipt.credits_charged).toBe(row.credits);
			expect(receipt.usage_source).toBe('provider_reported');
			expect(receipt.entries.length).toBeGreaterThan(0);
			for (const attempt of receipt.entries) {
				expect(attempt.model_id).toBe('openai/gpt-6.1-sol');
				expect(attempt.inference_host).toBe('openai');
				expect(attempt.billing_mode).toBe('cache_aware');
			}
		}
		const expectedReads = [0, 80, 160, 80, 80];
		const expectedInputs = [480, 240, 480, 240, 240];
		const expectedOutputs = [52, 28, 52, 28, 28];
		const expectedAttempts = [2, 1, 2, 1, 1];
		for (const [index, row] of asksByTurn.entries()) {
			const receipt = row.llm_usage_breakdown;
			expect(receipt.cache_read_input_tokens).toBe(expectedReads[index]);
			expect(receipt.input_tokens).toBe(expectedInputs[index]);
			expect(receipt.output_tokens).toBe(expectedOutputs[index]);
			expect(receipt.cache_creation_input_tokens).toBe(0);
			expect(receipt.entries).toHaveLength(expectedAttempts[index]);
		}
		const settledChatCredits = entries.reduce((sum: number, row: any) => sum + Number(row.credits), 0);
		expect(math.reduce((sum: number, row: any) => sum + row.credits, 0)).toBeGreaterThan(0);
		currentStage = 'chat_total';
		await expect.poll(async () => {
			const response = await page.request.get(`${API_URL}/v1/settings/usage/chat-total`, {
				params: { chat_id: chatId }
			});
			expect(response.status()).toBe(200);
			return (await response.json()).total_credits;
		}, { timeout: 30_000 }).toBe(settledChatCredits);
		currentStage = 'wallet_reconcile';
		await expect.poll(async () => initialWalletCredits! - await accountCredits(page), {
			message: 'fresh-account wallet debit should equal settled AI and paid math charges',
			timeout: 30_000
		}).toBe(settledChatCredits);
		currentStage = 'billing_holds';
		const overview = await page.request.get(`${API_URL}/v1/settings/billing`);
		expect(overview.status()).toBe(200);
		billingState.heldCredits = (await overview.json()).held_credits;
		expect(billingState.heldCredits).toBe(0);
		expect(frames.join('\n')).not.toContain('PRIVATE_NATIVE_CACHE_FRAME');
		expect(frames.join('\n')).not.toContain('native_cache_context');
	} finally {
		await test.info().attach('native-cache-turn-protocol-summary', {
			body: JSON.stringify(safeProtocolSummary(persistEvents, currentStage, turnsAttempted,
				successfulReplies, usageStatus, usageCounts, observedAssistantIds, observedChatIds,
				initialWalletCredits, preTurnWalletCredits, standardErrorReplies, fixtureAnswerMatches, billingState), null, 2),
			contentType: 'application/json'
		});
		await deleteActiveChat(page);
	}
});
