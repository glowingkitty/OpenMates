/**
 * Flag-on (VITE_OPENMATES_RUST_CORE) fork conversation: the page adapter over the
 * shared Rust core Worker `chatState` fork operations. Loaded only by the guarded
 * branch of forkChatService.ts, so default builds never bundle it. Rust selects
 * the messages, re-encrypts them with the new chat key (fresh ids), copies
 * category/icon and builds the chat record and `encrypted_chat_metadata` payload.
 * The page keeps ChatKeyManager, IndexedDB, progress UI and the socket send. No
 * TypeScript fallback: a refused call rejects.
 */
import type { Chat, Message } from '../../../types/chat';
import { forkSourceFromMessage } from './chatStateAdapter';
import { chatStateCall } from './chatListUnitClient';
import { UnitPortError } from '../host/unitPort';

const BATCH_SIZE = 10;

/** Web error text the legacy code threw when the fork point is missing. */
export const FORK_POINT_NOT_FOUND = 'Fork point message not found';

/** `normalizeExplainSelection`: collapse whitespace, trim, cap at 500 UTF-16 units (Rust). */
export async function rustNormalizeExplainSelection(selectedText: string): Promise<string> {
	return (await chatStateCall('forkNormalizeSelection', { selectedText })).value;
}

/** Messages to copy, in fork order (stable `created_at` sort, up to and including the fork point). */
export async function rustForkSelect(messages: Message[], upToMessageId: string): Promise<Message[]> {
	const sources = messages.map(forkSourceFromMessage);
	try {
		const { ids } = await chatStateCall('forkSelect', { messagesJson: JSON.stringify(sources), upToMessageId });
		const byId = new Map(messages.map((message) => [message.message_id, message]));
		return ids.map((id) => byId.get(id) as Message);
	} catch (error) {
		if (error instanceof UnitPortError && error.code === 'fork_refused') throw new Error(FORK_POINT_NOT_FOUND);
		throw error;
	}
}

export interface RustForkBuildInput {
	sourceChat: Chat | null | undefined;
	sourceChatKey: Uint8Array | null | undefined;
	newChatId: string;
	newChatKey: Uint8Array;
	encryptedNewChatKey: string;
	forkTitle: string;
	messages: Message[];
	nowSeconds: number;
	onProgress(processed: number): void;
	yieldToEventLoop(): Promise<void>;
}

export interface RustForkBuild {
	record: Chat;
	rows: Message[];
	payload: Record<string, unknown>;
}

/** Title, category/icon copy, batched message re-encryption and the finalize record and payload. */
export async function rustForkBuild(input: RustForkBuildInput): Promise<RustForkBuild> {
	const { newChatKey, newChatId } = input;
	const { value: encryptedTitle } = await chatStateCall('forkEncryptTitle', { title: input.forkTitle, chatKey: newChatKey });
	let encryptedCategory: string | null = null;
	let encryptedIcon: string | null = null;
	if (input.sourceChatKey) {
		const copy = async (ciphertext: string | null | undefined) =>
			(await chatStateCall('forkCopyField', { sourceCiphertext: ciphertext ?? null, sourceKey: input.sourceChatKey as Uint8Array, newKey: newChatKey })).value;
		encryptedCategory = await copy(input.sourceChat?.encrypted_category);
		encryptedIcon = await copy(input.sourceChat?.encrypted_icon);
	}
	const sources = input.messages.map(forkSourceFromMessage);
	const rows: Record<string, unknown>[] = [];
	for (let index = 0; index < sources.length; index += BATCH_SIZE) {
		const batch = await chatStateCall('forkReencryptBatch', {
			messagesJson: JSON.stringify(sources.slice(index, index + BATCH_SIZE)), newChatId, chatKey: newChatKey,
		});
		rows.push(...batch.rows);
		input.onProgress(rows.length);
		await input.yieldToEventLoop();
	}
	const finalized = await chatStateCall('forkFinalize', {
		chatJson: JSON.stringify({
			chat_id: newChatId, encrypted_chat_key: input.encryptedNewChatKey, encrypted_title: encryptedTitle,
			encrypted_category: encryptedCategory ?? undefined, encrypted_icon: encryptedIcon ?? undefined,
			user_id: input.sourceChat?.user_id, message_count: input.messages.length, now_seconds: input.nowSeconds,
		}),
		rowsJson: JSON.stringify(rows),
	});
	return { record: finalized.record as unknown as Chat, rows: rows as unknown as Message[], payload: finalized.payload };
}
