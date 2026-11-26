import { expect, it, vi } from 'vitest';
import headerFixture from '../../../../../../../packages/openmates-rust/tests/fixtures/browser-metadata-only-header.json';
import { browserMessageCacheTransactionProtocol, executeBrowserMessageCachePlan } from '../browserMessageCacheIO';

const CHAT = '22222222-2222-4222-8222-222222222222';
const OWNER = '11111111-1111-4111-8111-111111111111';
const OPERATION = '33333333-3333-4333-8333-333333333333';
const MESSAGE = '44444444-4444-4444-8444-444444444444';

// Ordered Rust PREDICATES from browser_cache_metadata.rs. The host and native
// executor both must admit the actual plan before an IndexedDB effect runs.
const metadataFields = [
	'id', 'chat_id', 'user_id', 'team_id', 'hashed_team_id', 'chat_visibility', 'encrypted_chat_key',
	'key_version', 'key_fingerprint', 'title_v', 'metadata_v', 'messages_v', 'created_at', 'updated_at',
	'last_edited_overall_timestamp', 'pinned', 'encrypted_title', 'encrypted_chat_summary',
	'encrypted_share_cta_text', 'encrypted_chat_tags', 'encrypted_follow_up_request_suggestions',
	'encrypted_suggested_followup_message', 'encrypted_icon', 'encrypted_category', 'encrypted_active_focus_id',
	'encrypted_focus_phase_state', 'encrypted_wellbeing_scores', 'encrypted_auto_speak_response'
];

function existingChatDatabase(metadata: Record<string, unknown>) {
	const messages = new Map<string, unknown>();
	const additions = vi.fn((message: { message_id: string }) => messages.set(message.message_id, message));
	const database = {
		version: 1,
		close: vi.fn(),
		objectStoreNames: { contains: (store: string) => store === 'chats' || store === 'messages' },
		transaction() {
			let pending = 0;
			const request = (result: unknown) => {
				const operation: { result: unknown; onsuccess?: () => void } = { result };
				pending++;
				queueMicrotask(() => {
					operation.onsuccess?.();
					if (--pending === 0) transaction.oncomplete?.();
				});
				return operation;
			};
			const transaction = {
				oncomplete: undefined as (() => void) | undefined,
				onabort: undefined as (() => void) | undefined,
				abort: () => transaction.onabort?.(),
				objectStore: (store: string) => store === 'chats'
					? { keyPath: 'chat_id', get: () => request(metadata) }
					: {
						keyPath: 'message_id',
						get: (id: string) => request(messages.get(id)),
						add: (message: { message_id: string }) => { additions(message); return request(message.message_id); }
					}
			};
			return transaction;
		}
	};
	return {
		factory: {
			databases: async () => [{ name: 'chats_db', version: database.version }],
			open: () => {
				const request: { result: typeof database; onsuccess?: () => void } = { result: database };
				queueMicrotask(() => request.onsuccess?.());
				return request;
			}
		} as unknown as IDBFactory,
		additions
	};
}

// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted,sync.phase2.metadata-only
it('retains an encrypted cold page against a Phase 2 header with undefined placeholders', async () => {
	const metadataInsert = { ...headerFixture.cases[0].expected, encrypted_chat_key: 'wrapped-key' };
	const metadata = {
		...metadataInsert, metadata_v: undefined, user_id: OWNER,
		ideabucket: undefined, encrypted_wellbeing_scores: 'sealed-wellbeing'
	};
	const { factory, additions } = existingChatDatabase(metadata);
	const plan = {
		version: 1, kind: 'capture_cold_incoming_insert', operationId: OPERATION,
		scope: { lifecycleGeneration: 1, workspaceEpoch: 0 },
		owner: OWNER, chatId: CHAT, database: 'chats_db', stores: ['chats', 'messages'],
		databaseVersion: null, messageIds: [MESSAGE], metadataFields,
		messageFields: browserMessageCacheTransactionProtocol.FIELDS,
		expectedMetadata: null, expectedRows: null, patches: null, assistantDuplicateAbsence: [], metadataInsert
	};
	const signal = new AbortController().signal;
	const execute = async (input: object) => JSON.parse(
		await executeBrowserMessageCachePlan(factory, JSON.stringify(input), signal, () => {})
	);
	const capture = await execute(plan);
	expect(capture.rows).toEqual([null]);
	expect(capture.metadata).toHaveProperty('encrypted_wellbeing_scores', 'sealed-wellbeing');
	expect(capture.metadata).not.toHaveProperty('metadata_v');
	expect(metadata).toHaveProperty('metadata_v', undefined);
	const expectedMetadata = Object.fromEntries(
		metadataFields.filter(field => Object.hasOwn(capture.metadata, field)).map(field => [field, capture.metadata[field]])
	);
	const encryptedMessage = {
		message_id: MESSAGE, chat_id: CHAT, role: 'user', created_at: 111,
		status: 'delivered', encrypted_content: 'sealed-message'
	};
	const committed = await execute({
		...plan, kind: 'compare_and_patch_cold_incoming_insert', databaseVersion: 1, expectedMetadata,
		expectedRows: [null], patches: [{ messageId: MESSAGE, insert: encryptedMessage }]
	});
	expect(committed.rows).toEqual([encryptedMessage]);
	expect(additions).toHaveBeenCalledExactlyOnceWith(encryptedMessage);
});
