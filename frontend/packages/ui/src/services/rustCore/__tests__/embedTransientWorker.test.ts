// contract-test-file: tooling
// Transient Rust Worker failures must not become permanent embed errors, and the
// Worker IndexedDB open must not hang forever. Local, provider-free.
import { describe, expect, it, vi } from 'vitest';
import { createWorkerChatsDb } from '../embeds/embedWorkerIdb';

vi.mock('../../cryptoService', () => ({ getKeyFromStorage: vi.fn() }));
vi.mock('../host/sharedCoreRegistry', () => ({ requireSharedRustCore: vi.fn() }));

describe('isTransientRustWorkerError', () => {
	it('treats timeouts, retire and unavailability as transient, other errors as final', async () => {
		const { isTransientRustWorkerError } = await import('../embeds/embedWriteSession');
		const { UnitPortError } = await import('../host/unitPort');
		expect(isTransientRustWorkerError(new UnitPortError('unit_timeout'))).toBe(true);
		expect(isTransientRustWorkerError(new UnitPortError('unit_retired'))).toBe(true);
		expect(isTransientRustWorkerError(new Error('embed_store_unavailable'))).toBe(true);
		expect(isTransientRustWorkerError(new Error('shared_core_crashed'))).toBe(true);
		expect(isTransientRustWorkerError(new UnitPortError('unit_failed'))).toBe(false);
		expect(isTransientRustWorkerError(new Error('OperationError'))).toBe(false);
	});
});

describe('createWorkerChatsDb', () => {
	it('rejects a hanging open after the timeout and reopens next call', async () => {
		vi.useFakeTimers();
		try {
			const factory = { open: vi.fn(() => ({}) as IDBOpenDBRequest) } as unknown as IDBFactory;
			const db = createWorkerChatsDb(factory, 1_000);
			const first = db.open();
			const assertion = expect(first).rejects.toThrow('embed_store_unavailable');
			await vi.advanceTimersByTimeAsync(1_000);
			await assertion;
			db.open().catch(() => undefined);
			expect(factory.open).toHaveBeenCalledTimes(2);
		} finally {
			vi.useRealTimers();
		}
	});
});
