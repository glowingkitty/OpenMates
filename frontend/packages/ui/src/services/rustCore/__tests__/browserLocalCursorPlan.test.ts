// Rust-issued `messages` read plan over a platform-held chats_db connection
// (browserLocalCursorIO.executeBrowserLocalReadPlan): row reads are pipelined
// behind the key cursor, yet the packet keeps the exact cursor order, the row
// limit with its next key, and the byte budget refusal.
import { describe, expect, it } from 'vitest';
import { executeBrowserLocalReadPlan } from '../browserLocalCursorIO';
import type { HeldExistingDatabase } from '../existingSavedChatIO';

const OWNER = '11111111-2222-3333-4444-555555555555';
const CHAT = '66666666-7777-8888-9999-aaaaaaaaaaaa';
const OPERATION = 'bbbbbbbb-cccc-dddd-eeee-ffffffffffff';

type Row = { message_id: string; chat_id: string; created_at: number; encrypted_content: string };

/** Readonly transaction fake: requests run one at a time in placement order, like IndexedDB. */
function heldChats(rows: Row[], log: string[]): HeldExistingDatabase {
	return {
		read(_stores, _signal, guard, issue) {
			return new Promise((resolve, reject) => {
				const queue: Array<() => void> = [];
				let running = false, aborted = false;
				const transaction: Record<string, unknown> = { db: { version: 7 } };
				const pump = () => {
					if (running) return;
					running = true;
					setTimeout(() => {
						running = false;
						if (aborted) return;
						const next = queue.shift();
						if (next) { next(); pump(); return; }
						(transaction.oncomplete as () => void)();
					}, 0);
				};
				const enqueue = (run: () => void) => { queue.push(run); pump(); };
				const sorted = [...rows].sort((a, b) => a.created_at - b.created_at);
				transaction.abort = () => { aborted = true; setTimeout(() => (transaction.onabort as () => void)(), 0); };
				transaction.objectStore = () => ({
					get(key: string) {
						const request: Record<string, unknown> = {};
						log.push(`get:${key}`);
						enqueue(() => { request.result = rows.find((row) => row.message_id === key); (request.onsuccess as () => void)?.(); });
						return request;
					},
					index() {
						return { openKeyCursor(_range: unknown, direction: string) {
							const ordered = direction === 'prev' ? [...sorted].reverse() : sorted;
							const request: Record<string, unknown> = {};
							let position = -1;
							const advance = () => enqueue(() => {
								position++;
								const row = ordered[position];
								log.push(row ? `cursor:${row.message_id}` : 'cursor:end');
								request.result = row ? { key: [CHAT, row.created_at], primaryKey: row.message_id, continue: advance } : null;
								(request.onsuccess as () => void)?.();
							});
							advance();
							return request;
						} };
					}
				});
				const read = issue(transaction as unknown as IDBTransaction, (error) => { (transaction.abort as () => void)(); reject(error); });
				const complete = () => { try { guard(); resolve(read()); } catch (error) { reject(error); } };
				transaction.oncomplete = complete;
				transaction.onabort = () => undefined;
			});
		},
		close() {}
	};
}

function plan(maxPayloadRows: number, direction: 'next' | 'prev', maxPacketBytes = 262144): string {
	return JSON.stringify({ version: 1, kind: 'messages', operationId: OPERATION, owner: OWNER, chatId: CHAT, maxPacketBytes,
		maxCheckpointRows: 0, maxPayloadRows, lower: null, upper: null, direction });
}

const rows: Row[] = [1, 2, 3, 4].map((n) => ({ message_id: `m${n}`, chat_id: CHAT, created_at: 100 + n, encrypted_content: `c${n}` }));
const keyRange = { bound: (...args: unknown[]) => args } as unknown as Pick<typeof IDBKeyRange, 'bound'>;

describe('executeBrowserLocalReadPlan (held chats_db)', () => {
	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('pipelines row reads and keeps cursor order, limit and next key', async () => {
		const log: string[] = [];
		const packet = JSON.parse(await executeBrowserLocalReadPlan({} as IDBFactory, plan(3, 'prev'), new AbortController().signal,
			() => {}, keyRange, undefined, heldChats(rows, log)));
		expect(packet.messages.map((row: Row) => row.message_id)).toEqual(['m4', 'm3', 'm2']);
		expect(packet.nextKey).toEqual({ createdAt: 101, messageId: 'm1' });
		expect(packet.rangeExhausted).toBe(false);
		expect(packet.databaseVersion).toBe(7);
		// The next cursor step is requested before the previous row read completed.
		expect(log.indexOf('cursor:m3')).toBeLessThan(log.indexOf('get:m3'));
		expect(log.indexOf('get:m4')).toBeLessThan(log.indexOf('cursor:m3'));
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('reports an exhausted range when every row fits', async () => {
		const packet = JSON.parse(await executeBrowserLocalReadPlan({} as IDBFactory, plan(20, 'next'), new AbortController().signal,
			() => {}, keyRange, undefined, heldChats(rows, [])));
		expect(packet.messages.map((row: Row) => row.message_id)).toEqual(['m1', 'm2', 'm3', 'm4']);
		expect(packet.nextKey).toBeNull();
		expect(packet.rangeExhausted).toBe(true);
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('refuses a packet over its byte budget instead of truncating', async () => {
		const large = rows.map((row) => ({ ...row, encrypted_content: 'x'.repeat(2000) }));
		await expect(executeBrowserLocalReadPlan({} as IDBFactory, plan(20, 'next', 4096), new AbortController().signal,
			() => {}, keyRange, undefined, heldChats(large, []))).rejects.toThrow('unavailable_packet_budget');
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('refuses a held connection combined with routed cursor IO', async () => {
		await expect(executeBrowserLocalReadPlan({} as IDBFactory, plan(20, 'next'), new AbortController().signal,
			() => {}, keyRange, {} as never, heldChats(rows, []))).rejects.toThrow('unavailable');
	});
});
