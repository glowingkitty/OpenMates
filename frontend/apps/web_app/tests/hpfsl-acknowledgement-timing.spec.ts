/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Focused regression for HPFSL signed-in chat acknowledgement timing.
 * It records only protocol routing metadata and DOM status timestamps so message
 * acknowledgement cannot be confused with encrypted new-chat metadata persistence.
 * Live-mock mode exercises the full pipeline while replaying external providers.
 */
// proof-video: not_required reason=incident_ack_timing
export {};

const { test, expect } = require('./console-monitor');
const {
	archiveExistingScreenshots,
	createSignupLogger,
	getTestAccount,
	withLiveMockMarker
} = require('./signup-flow-helpers');
const {
	fillMessageEditor,
	loginToTestAccount,
	startNewChat,
	deleteActiveChat,
	waitForAssistantMessage
} = require('./helpers/chat-test-helpers');

const PROMPT = 'Calculate the square root of 144';
const LIVE_MOCK_GROUP = 'math_calculate_web';
const ACK_TO_STATUS_MAX_MS = 3000;

type ProtocolEvent = {
	direction: 'sent' | 'received';
	type: string;
	at: number;
	chatId?: string;
	messageId?: string;
	turnId?: string;
	state?: string;
	taskId?: string;
	userMessageId?: string;
	hasEncryptedChatMetadata?: boolean;
	hasEncryptedContent?: boolean;
	hasEncryptedTitle?: boolean;
	hasEncryptedChatKey?: boolean;
};

type StatusSample = {
	at: number;
	label: string;
	chatId: string | null;
	messageId: string | null;
	status: string | null;
	processing: string | null;
};

function captureProtocolEvents(page: any, events: ProtocolEvent[]): void {
	page.on('websocket', (websocket: any) => {
		const capture = (direction: 'sent' | 'received') => (frame: { payload?: string | Buffer }) => {
			try {
				const message = JSON.parse(String(frame.payload));
				if (typeof message.type !== 'string') return;
				const payload = message.payload && typeof message.payload === 'object' ? message.payload : {};
				events.push({
					direction,
					type: message.type,
					at: Date.now(),
					chatId: typeof payload.chat_id === 'string' ? payload.chat_id : undefined,
					messageId: typeof payload.message_id === 'string' ? payload.message_id : undefined,
					turnId: typeof payload.turn_id === 'string' ? payload.turn_id : undefined,
					state: typeof payload.state === 'string' ? payload.state : undefined,
					taskId: typeof payload.task_id === 'string' ? payload.task_id : undefined,
					userMessageId: typeof payload.user_message_id === 'string' ? payload.user_message_id : undefined,
					hasEncryptedChatMetadata: !!payload.encrypted_chat_metadata,
					hasEncryptedContent: !!payload.encrypted_content,
					hasEncryptedTitle: !!payload.encrypted_title,
					hasEncryptedChatKey: !!payload.encrypted_chat_key
				});
			} catch {
				// Non-JSON websocket control frames are not OpenMates protocol events.
			}
		};
		websocket.on('framesent', capture('sent'));
		websocket.on('framereceived', capture('received'));
	});
}

async function installStatusSampler(page: any): Promise<void> {
	await page.evaluate(() => {
		const testWindow = window as Window & {
			__hpfslAckStatusSamples?: StatusSample[];
			__hpfslAckStatusObserver?: MutationObserver;
		};
		testWindow.__hpfslAckStatusSamples = [];
		testWindow.__hpfslAckStatusObserver?.disconnect();
		const record = (label: string) => {
			const activeChat = document.querySelector<HTMLElement>('[data-testid="active-chat-container"]');
			const lastUser = Array.from(document.querySelectorAll<HTMLElement>('[data-testid="message-user"]')).at(-1);
			testWindow.__hpfslAckStatusSamples?.push({
				at: Date.now(),
				label,
				chatId: activeChat?.getAttribute('data-current-chat-id') ?? null,
				messageId: lastUser?.getAttribute('data-message-id') ?? null,
				status: lastUser?.getAttribute('data-status') ?? null,
				processing: activeChat?.getAttribute('data-processing') ?? null
			});
		};
		const observer = new MutationObserver(() => record('mutation'));
		observer.observe(document.body, {
			subtree: true,
			childList: true,
			attributes: true,
			attributeFilter: ['data-status', 'data-current-chat-id', 'data-processing']
		});
		testWindow.__hpfslAckStatusObserver = observer;
		record('installed');
	});
}

async function recordStatusSample(page: any, label: string): Promise<void> {
	await page.evaluate((sampleLabel: string) => {
		const testWindow = window as Window & { __hpfslAckStatusSamples?: StatusSample[] };
		const activeChat = document.querySelector<HTMLElement>('[data-testid="active-chat-container"]');
		const lastUser = Array.from(document.querySelectorAll<HTMLElement>('[data-testid="message-user"]')).at(-1);
		testWindow.__hpfslAckStatusSamples?.push({
			at: Date.now(),
			label: sampleLabel,
			chatId: activeChat?.getAttribute('data-current-chat-id') ?? null,
			messageId: lastUser?.getAttribute('data-message-id') ?? null,
			status: lastUser?.getAttribute('data-status') ?? null,
			processing: activeChat?.getAttribute('data-processing') ?? null
		});
	}, label);
}

async function getStatusSamples(page: any): Promise<StatusSample[]> {
	return page.evaluate(() => {
		const testWindow = window as Window & { __hpfslAckStatusSamples?: StatusSample[] };
		return testWindow.__hpfslAckStatusSamples ?? [];
	});
}

function firstEvent(
	events: ProtocolEvent[],
	direction: 'sent' | 'received',
	type: string,
	predicate: (event: ProtocolEvent) => boolean = () => true
): ProtocolEvent | undefined {
	return events.find((event) => event.direction === direction && event.type === type && predicate(event));
}

function diagnostic(events: ProtocolEvent[], samples: StatusSample[]): string {
	return JSON.stringify({
		events: events.filter((event) => [
			'chat_turn_preflight',
			'chat_turn_preflight_ack',
			'chat_message_added',
			'chat_message_confirmed',
			'ai_typing_started',
			'encrypted_chat_metadata'
		].includes(event.type)),
		samples
	}, null, 2);
}

// contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,chats.message.identity-idempotent
test('signed-in new chat acknowledges the user message before AI typing and metadata persistence', async ({ page }) => {
	test.slow();
	test.setTimeout(180_000);
	test.skip(!getTestAccount().email, 'Test account credentials required.');

	const log = createSignupLogger('hpfsl-acknowledgement-timing');
	await archiveExistingScreenshots(log);
	const events: ProtocolEvent[] = [];
	captureProtocolEvents(page, events);

	await loginToTestAccount(page, log);
	await startNewChat(page, log);
	await installStatusSampler(page);

	const messageField = page.getByTestId('message-field').last();
	const messageEditor = messageField.getByTestId('message-editor');
	const markedMessage = withLiveMockMarker(PROMPT, LIVE_MOCK_GROUP);
	const marker = markedMessage.match(/<<<TEST_LIVE_MOCK:[^>]+>>>$/)?.[0] ?? null;
	if (!marker) {
		throw new Error('HPFSL acknowledgement timing must run with E2E_USE_LIVE_MOCKS; do not spend real provider budget.');
	}
	await fillMessageEditor(page, messageEditor, PROMPT);
	await recordStatusSample(page, 'typed');

	const dispatchAt = Date.now();
	await messageEditor.evaluate((editor: HTMLElement, markerValue: string) => {
		editor.dispatchEvent(new CustomEvent('custom-send-message', {
			bubbles: true,
			cancelable: true,
			detail: { testMockMarker: markerValue }
		}));
	}, marker);
	await recordStatusSample(page, 'dispatched');

	await expect.poll(() => firstEvent(events, 'received', 'chat_message_confirmed')?.messageId ?? '', {
		timeout: 30_000,
		intervals: [100, 250, 500, 1000]
	}).not.toBe('');
	await recordStatusSample(page, 'chat_message_confirmed_seen');

	const confirmed = firstEvent(events, 'received', 'chat_message_confirmed')!;
	await expect.poll(() => firstEvent(events, 'received', 'ai_typing_started', (event) => event.userMessageId === confirmed.messageId)?.userMessageId ?? '', {
		timeout: 90_000,
		intervals: [250, 500, 1000, 2000]
	}).toBe(confirmed.messageId);
	await recordStatusSample(page, 'ai_typing_started_seen');

	await waitForAssistantMessage(page, { timeout: 120_000, logCheckpoint: log });
	await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-processing', 'false', { timeout: 120_000 });
	await recordStatusSample(page, 'assistant_complete');

	const samples = await getStatusSamples(page);
	const preflight = firstEvent(events, 'sent', 'chat_turn_preflight', (event) => event.messageId === confirmed.messageId);
	const preflightAck = firstEvent(events, 'received', 'chat_turn_preflight_ack', (event) => event.turnId === preflight?.turnId);
	const messageSent = firstEvent(events, 'sent', 'chat_message_added', (event) => event.messageId === confirmed.messageId);
	const typing = firstEvent(events, 'received', 'ai_typing_started', (event) => event.userMessageId === confirmed.messageId);
	const metadataSent = firstEvent(events, 'sent', 'encrypted_chat_metadata', (event) => event.messageId === confirmed.messageId);
	const syncedStatus = samples.find((sample) => sample.messageId === confirmed.messageId && sample.status === 'synced');
	const diagnostics = diagnostic(events, samples);

	expect(preflight, diagnostics).toBeTruthy();
	expect(preflight?.hasEncryptedChatMetadata, diagnostics).toBe(true);
	expect(preflightAck, diagnostics).toBeTruthy();
	expect(messageSent, diagnostics).toBeTruthy();
	expect(typing, diagnostics).toBeTruthy();
	expect(metadataSent, diagnostics).toBeTruthy();
	expect(metadataSent?.hasEncryptedContent, diagnostics).toBe(true);
	expect(metadataSent?.hasEncryptedChatKey, diagnostics).toBe(true);
	expect(preflight!.at, diagnostics).toBeLessThan(preflightAck!.at);
	expect(preflightAck!.at, diagnostics).toBeLessThanOrEqual(messageSent!.at);
	expect(messageSent!.at, diagnostics).toBeLessThanOrEqual(confirmed.at);
	expect(confirmed.at, diagnostics).toBeLessThan(typing!.at);
	expect(syncedStatus, diagnostics).toBeTruthy();
	expect(syncedStatus!.at - confirmed.at, diagnostics).toBeLessThanOrEqual(ACK_TO_STATUS_MAX_MS);
	expect(metadataSent!.at, diagnostics).toBeGreaterThanOrEqual(typing!.at);

	log('HPFSL acknowledgement timing measured.', {
		dispatchToPreflightAckMs: preflightAck!.at - dispatchAt,
		dispatchToMessageConfirmedMs: confirmed.at - dispatchAt,
		messageConfirmedToStatusSyncedMs: syncedStatus!.at - confirmed.at,
		messageConfirmedToAiTypingStartedMs: typing!.at - confirmed.at,
		aiTypingStartedToEncryptedMetadataSentMs: metadataSent!.at - typing!.at,
		preflightIncludedEncryptedMetadata: preflight?.hasEncryptedChatMetadata,
		metadataSentIncludedEncryptedChatKey: metadataSent?.hasEncryptedChatKey
	});

	await deleteActiveChat(page, log, async () => undefined, 'hpfsl-ack');
});
