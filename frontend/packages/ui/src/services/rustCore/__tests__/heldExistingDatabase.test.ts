// Platform-held existing IndexedDB connection (existingSavedChatIO.holdExistingDatabase):
// repeated readonly checks reuse one databases() + open; a versionchange, forced
// close or holder close invalidates every later read (never reopens, fail closed).
import { describe, expect, it, vi } from 'vitest';
import { holdExistingProfileDatabase, readHeldProfileOwner } from '../existingSavedChatIO';

const OWNER = '11111111-2222-3333-4444-555555555555';

function fakeFactory(version = 3) {
	const databases: Array<{ onversionchange: (() => void) | null; onclose: (() => void) | null; closed: boolean }> = [];
	const factory = {
		databases: vi.fn(async () => [{ name: 'user_db', version }]),
		open: vi.fn((_name: string) => {
			const request: Record<string, unknown> = {};
			const database = {
				version, closed: false, onversionchange: null as (() => void) | null, onclose: null as (() => void) | null,
				objectStoreNames: { contains: (store: string) => store === 'user_data' },
				close() { database.closed = true; },
				transaction() {
					const transaction: Record<string, unknown> = {
						abort() { queueMicrotask(() => (transaction.onabort as () => void)?.()); },
						objectStore() {
							return { get() {
								const get: Record<string, unknown> = {};
								setTimeout(() => {
									get.result = OWNER; (get.onsuccess as () => void)?.();
									setTimeout(() => (transaction.oncomplete as () => void)?.(), 0);
								}, 0);
								return get;
							} };
						}
					};
					return transaction;
				}
			};
			databases.push(database);
			setTimeout(() => { request.result = database; (request.onsuccess as () => void)?.(); }, 0);
			return request;
		})
	};
	return { factory: factory as unknown as IDBFactory, spy: factory, databases };
}

describe('holdExistingDatabase', () => {
	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('reuses one databases() lookup and one open for repeated reads', async () => {
		const { factory, spy, databases } = fakeFactory();
		const held = holdExistingProfileDatabase(factory);
		const signal = new AbortController().signal;
		const reads = await Promise.all([readHeldProfileOwner(held, signal, () => {}), readHeldProfileOwner(held, signal, () => {})]);
		expect(reads).toEqual([OWNER, OWNER]);
		expect(await readHeldProfileOwner(held, signal, () => {})).toBe(OWNER);
		expect(spy.databases).toHaveBeenCalledTimes(1);
		expect(spy.open).toHaveBeenCalledTimes(1);
		expect(databases[0].closed).toBe(false);
		held.close();
		expect(databases[0].closed).toBe(true);
		await expect(readHeldProfileOwner(held, signal, () => {})).rejects.toThrow('invalidated_snapshot');
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('a versionchange closes the connection and invalidates later reads without reopening', async () => {
		const { factory, spy, databases } = fakeFactory();
		const held = holdExistingProfileDatabase(factory);
		const signal = new AbortController().signal;
		expect(await readHeldProfileOwner(held, signal, () => {})).toBe(OWNER);
		databases[0].onversionchange?.();
		expect(databases[0].closed).toBe(true);
		await expect(readHeldProfileOwner(held, signal, () => {})).rejects.toThrow('invalidated_snapshot');
		expect(spy.open).toHaveBeenCalledTimes(1);
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('a forced close invalidates later reads', async () => {
		const { factory, databases } = fakeFactory();
		const held = holdExistingProfileDatabase(factory);
		const signal = new AbortController().signal;
		await readHeldProfileOwner(held, signal, () => {});
		databases[0].onclose?.();
		await expect(readHeldProfileOwner(held, signal, () => {})).rejects.toThrow('invalidated_snapshot');
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it("the caller's guard still runs on every read", async () => {
		const { factory } = fakeFactory();
		const held = holdExistingProfileDatabase(factory);
		const signal = new AbortController().signal;
		await readHeldProfileOwner(held, signal, () => {});
		await expect(readHeldProfileOwner(held, signal, () => { throw new Error('invalidated_snapshot'); })).rejects.toThrow('invalidated_snapshot');
		// A failed caller guard does not poison the holder.
		expect(await readHeldProfileOwner(held, signal, () => {})).toBe(OWNER);
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('refuses a database that does not exist yet (no create)', async () => {
		const { factory, spy } = fakeFactory();
		spy.databases.mockResolvedValueOnce([]);
		const held = holdExistingProfileDatabase(factory);
		await expect(readHeldProfileOwner(held, new AbortController().signal, () => {})).rejects.toThrow('unavailable');
		expect(spy.open).not.toHaveBeenCalled();
		await expect(readHeldProfileOwner(held, new AbortController().signal, () => {})).rejects.toThrow('invalidated_snapshot');
	});
});
