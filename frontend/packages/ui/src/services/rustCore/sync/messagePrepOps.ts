/**
 * Flag-on (VITE_OPENMATES_RUST_CORE) storage preparation of synced messages:
 * the page adapter over the shared Rust core Worker `sync` unit
 * (web_sync/message_prep.rs). Loaded only through the guarded branches of the
 * sync handlers (chatSyncMessagePrep.ts `messagePrepOps`), so default builds
 * never bundle it.
 *
 * Each function has the signature and result of its chatSyncMessagePrep.ts
 * twin. The page parses the JSON strings, sends only the decision fields (ids,
 * chat id, role, status, queue receipt; never ciphertext), and applies the Rust
 * plan in message order. The in-memory processing fence is read live while the
 * plan is applied, after the single Worker answer, exactly where the TypeScript
 * loop reads it, and fence clears happen in the same order. A row that makes the
 * TypeScript loop throw (a `null` message) throws here too, after the rows
 * before it were applied. There is no TypeScript fallback.
 */
import type { Message, MessageStatus } from '../../../types/chat';
import { batchMessageRecord } from '../../chatSyncMessagePrep';
import { clearQueuedProcessingForMessage, hasQueuedProcessing } from '../../queuedMessageLifecycle';
import type { MessagePrepEntry, MessagePrepPlan } from './inboundProtocol';
import { syncCall } from './syncUnitClient';

// eslint-disable-next-line @typescript-eslint/no-explicit-any -- server rows are untyped JSON until normalized
type Row = any;
interface Collected { rows: Row[]; entries: (MessagePrepEntry | null)[]; failure: { error: unknown } | null }

/** Decision fields of one row; a `null`/`undefined` row throws like the TypeScript property read. */
function entryOf(row: Row): MessagePrepEntry {
	const id = row.message_id;
	if (typeof row !== 'object') return {};
	return {
		message_id: id, client_message_id: row.client_message_id, id: row.id, chat_id: row.chat_id, role: row.role,
		status: row.status, queue_dispatch_status: row.queue_dispatch_status, queue_dispatch_mode: row.queue_dispatch_mode,
	};
}

/**
 * Parses and slims the rows. `parse` returns the parsed row, or `null` when the
 * mode skips a failed parse (it logs like the TypeScript loop).
 */
function collect(raw: unknown[], parse: (text: string) => { row: Row } | null): Collected {
	const out: Collected = { rows: [], entries: [], failure: null };
	for (const data of raw) {
		let row: Row = data;
		if (typeof data === 'string') {
			const parsed = parse(data);
			if (!parsed) {
				out.rows.push(null);
				out.entries.push(null);
				continue;
			}
			row = parsed.row;
		}
		try {
			out.entries.push(entryOf(row));
		} catch (error) {
			out.failure = { error };
			break;
		}
		out.rows.push(row);
	}
	return out;
}

async function plan(mode: 'phased' | 'batch', collected: Collected): Promise<MessagePrepPlan[]> {
	if (collected.entries.length === 0) return [];
	return (await syncCall('messagePrep', { mode, messages: collected.entries })).plans;
}

const silentParse = (text: string): { row: Row } | null => {
	try {
		return { row: JSON.parse(text) };
	} catch {
		return null;
	}
};

/** `prepareMessagesForStorage` (Phase 2/3) on the Rust plan. */
export async function prepareMessagesForStorage(messages: Message[], chatId: string, phaseName: string): Promise<Message[]> {
	const prepared: Message[] = [];
	if (!messages || !Array.isArray(messages)) return prepared;
	const collected = collect(messages, (text) => {
		try {
			const row = JSON.parse(text);
			const messageId = row.message_id || row.id;
			console.debug(`[ChatSyncService] ${phaseName} - Parsed message JSON string for message: ${messageId}`);
			return { row };
		} catch (e) {
			console.error(`[ChatSyncService] ${phaseName} - Failed to parse message JSON for chat ${chatId}:`, e);
			return null;
		}
	});
	const plans = await plan('phased', collected);
	plans.forEach((step, index) => {
		if (step.skip === 'parse') return;
		const message = collected.rows[index];
		if (step.skip === 'id') {
			console.error(`[ChatSyncService] ${phaseName} - Message missing message_id after parsing, skipping:`, message);
			return;
		}
		if (step.idKey === 'id') message.message_id = message.id;
		if (!step.chatOwn) message.chat_id = chatId;
		if (step.queue === 'paused') {
			clearQueuedProcessingForMessage(message.chat_id, message.message_id);
			message.status = 'delivered';
			message.queue_mode = undefined;
		} else if (hasQueuedProcessing(message.chat_id, message.message_id) || step.queue === 'processing') {
			message.status = 'delivered';
			message.queue_mode = undefined;
			message.queue_dispatch_status = 'processing';
		} else if (step.queue === 'queued') {
			message.status = 'queued';
			message.queue_mode = message.queue_dispatch_mode;
		} else if (!step.statusOwn) {
			message.status = 'delivered';
		}
		prepared.push(message);
	});
	if (collected.failure) throw collected.failure.error;
	return prepared;
}

/** `prepareBackgroundMessages` on the Rust plan. */
export async function prepareBackgroundMessages(messages: (Message | string)[], chatId: string): Promise<Message[]> {
	const collected = collect(messages, silentParse);
	const plans = await plan('phased', collected);
	const prepared: Message[] = [];
	plans.forEach((step, index) => {
		if (step.skip !== null) return;
		const message = collected.rows[index];
		if (step.idKey === 'id') message.message_id = message.id;
		if (!step.chatOwn) message.chat_id = chatId;
		if (!step.statusOwn) message.status = 'delivered';
		prepared.push(message);
	});
	if (collected.failure) throw collected.failure.error;
	return prepared;
}

/** `preparePhase1bMessages` on the Rust plan. */
export async function preparePhase1bMessages(messages: (Message | string)[], chatId: string): Promise<Message[]> {
	const collected = collect(messages, silentParse);
	const plans = await plan('phased', collected);
	const prepared: Message[] = [];
	plans.forEach((step, index) => {
		if (step.skip !== null) return;
		const message = collected.rows[index];
		if (step.idKey === 'id') message.message_id = message.id;
		if (!step.chatOwn) message.chat_id = chatId;
		if (step.queue === 'paused') {
			clearQueuedProcessingForMessage(chatId, message.message_id);
			message.status = 'delivered';
			message.queue_mode = undefined;
		} else if (hasQueuedProcessing(chatId, message.message_id) || step.queue === 'processing') {
			message.status = 'delivered';
			message.queue_mode = undefined;
			message.queue_dispatch_status = 'processing';
		} else if (step.queue === 'queued') {
			message.status = 'queued';
			message.queue_mode = message.queue_dispatch_mode;
		} else if (!step.statusOwn) message.status = 'delivered';
		prepared.push(message);
	});
	if (collected.failure) throw collected.failure.error;
	return prepared;
}

/** `prepareBatchMessagesForStorage` (on-demand content batch) on the Rust plan. */
export async function prepareBatchMessagesForStorage(rawMessages: unknown[], chatId: string): Promise<Message[]> {
	const collected = collect(rawMessages, (text) => {
		try {
			return { row: JSON.parse(text) };
		} catch (e) {
			console.error(`[ChatSyncService:CoreSync] Failed to parse message JSON for chat ${chatId}:`, e);
			return null;
		}
	});
	const plans = await plan('batch', collected);
	const prepared: Message[] = [];
	plans.forEach((step, index) => {
		if (step.skip === 'parse') return;
		const message = collected.rows[index] as Record<string, unknown>;
		if (step.skip === 'id') {
			console.error(`[ChatSyncService:CoreSync] Message missing message_id after parsing, skipping:`, message);
			return;
		}
		const messageId = message[step.idKey] as string;
		if (step.queue === 'paused') clearQueuedProcessingForMessage(chatId, messageId);
		const fenced = step.queue !== 'paused' && hasQueuedProcessing(chatId, messageId);
		prepared.push(batchMessageRecord(message, {
			message_id: messageId,
			chat_id: step.chatOwn ? message.chat_id as string : chatId,
			role: step.roleOwn ? message.role as Message['role'] : 'user',
			status: fenced || step.queue === 'processing' || step.queue === 'paused'
				? 'delivered'
				: step.queue === 'queued' ? 'queued' : step.statusOwn ? message.status as MessageStatus : 'delivered',
			queue_mode: !fenced && step.queue === 'queued' ? message.queue_dispatch_mode as Message['queue_mode'] : undefined,
			queue_dispatch_status: fenced
				? 'processing' : message.queue_dispatch_status as 'queued' | 'processing' | 'paused' | null | undefined,
		}));
	});
	if (collected.failure) throw collected.failure.error;
	return prepared;
}
