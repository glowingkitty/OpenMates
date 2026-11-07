// contract-test-file: tooling
// spec: specifications/features/auth#auth.keys.client-wrapped
// spec: specifications/features/auth#auth.keys.independent-unlock
// Keys lane K2: ChatKeyManager mirrors its key lifecycle into the Worker key store
// (flag on), the handle API decrypts through the Worker, and logout/removal terminate
// Worker key state. Uses a fake Worker client (the Rust store itself is covered by
// web_key_state_tests.rs).
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

type Call = { op: string; args: unknown[] };
const calls: Call[] = [];
const replies: Record<string, unknown> = {};
const fakeClient = {
	call: (async (op: string, ...args: unknown[]) => {
		calls.push({ op, args });
		const reply = replies[op];
		return typeof reply === 'function' ? (reply as (...a: unknown[]) => unknown)(...args) : reply;
	}) as KeyOpsClient['call'],
	recordFailure: () => undefined,
	stats: { fingerprintMismatches: 0 }
};
let client: typeof fakeClient | null = fakeClient;

vi.mock('../crypto/webCryptoClient', () => ({
	rustWebCrypto: () => client,
	clearRustChatKeyCaches: () => undefined
}));
vi.mock('../../cryptoService', () => ({
	_generateChatKeyInternal: () => new Uint8Array(32),
	encryptChatKeyWithMasterKey: async () => null,
	decryptChatKeyWithMasterKey: async () => null,
	clearCryptoKeyCache: () => undefined,
	computeKeyFingerprint4Bytes: () => new Uint8Array(4),
	uint8ArrayToBase64: () => '',
	base64ToUint8Array: () => new Uint8Array()
}));
vi.mock('../../anonymousChatKeyWrapping', () => ({ unwrapAnonymousChatKey: async () => null }));
vi.mock('../../db/decryptionFailureCache', () => ({ clearDecryptionFailureCache: () => undefined }));
vi.mock('../../recentChatWindowCache', () => ({ invalidateRecentChatWindow: () => undefined }));

import { ChatKeyManager } from '../../encryption/ChatKeyManager';
import { keyStateClear, keyStateOffer, keyStateRemove, type KeyOpsClient } from '../crypto/keyOps';

const KEY = Uint8Array.from({ length: 32 }, (_, i) => i);
const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
const ops = () => calls.map((c) => c.op);

beforeEach(() => {
	calls.length = 0;
	for (const k of Object.keys(replies)) delete replies[k];
	client = fakeClient;
	vi.stubEnv('VITE_OPENMATES_RUST_CORE', '1');
});
afterEach(() => vi.unstubAllEnvs());

describe('key state ops', () => {
	it('send chat ids, copies of key bytes and the source to the Worker', async () => {
		const key = new Uint8Array([1, 2]);
		await keyStateOffer(fakeClient, 'chat', key, 'master_key', true);
		const sent = calls[0].args[1] as Uint8Array;
		expect(calls[0].op).toBe('keysStateOffer');
		expect(calls[0].args).toEqual(['chat', key, 'master_key', true]);
		expect(sent).not.toBe(key);
		await keyStateRemove(fakeClient, 'chat');
		await keyStateClear(fakeClient);
		expect(ops()).toEqual(['keysStateOffer', 'keysStateRemove', 'keysStateClear']);
	});
});

describe('ChatKeyManager mirror (flag on)', () => {
	it('offers accepted keys, forwards removal and terminates Worker state on clearAll', async () => {
		const manager = new ChatKeyManager();
		manager.injectKey('chat', KEY, 'master_key');
		await flush();
		expect(calls.find((c) => c.op === 'keysStateOffer')?.args.slice(0, 1)).toEqual(['chat']);
		manager.removeKey('chat');
		manager.clearAll({ broadcast: false });
		await flush();
		expect(ops()).toEqual(['keysStateOffer', 'keysStateRemove', 'keysStateClear']);
	});

	it('does nothing without a registered crypto client', async () => {
		client = null;
		const manager = new ChatKeyManager();
		manager.injectKey('chat', KEY, 'master_key');
		manager.clearAll({ broadcast: false });
		await flush();
		expect(calls).toEqual([]);
	});

	it('stays silent towards the Worker when the flag is off', async () => {
		vi.stubEnv('VITE_OPENMATES_RUST_CORE', '');
		const manager = new ChatKeyManager();
		manager.injectKey('chat', KEY, 'master_key');
		manager.clearAll({ broadcast: false });
		await flush();
		expect(calls).toEqual([]);
	});
});

describe('getKeyHandle (flag on)', () => {
	it('decrypts in the Worker for a known key and loads+offers on a miss', async () => {
		vi.doMock('../../encryption/MessageEncryptor', () => ({ decryptWithChatKey: vi.fn(), encryptWithChatKey: vi.fn() }));
		vi.resetModules();
		const { getKeyHandle } = await import('../../encryption/chatKeyHandles');
		const { chatKeyManager } = await import('../../encryption/ChatKeyManager');
		replies.keysStateHandle = { fingerprint: 'f'.repeat(16), source: 'master_key', timestamp: 1, persisted: true, state: 'ready' };
		replies.keysStateDecrypt = 'hello';
		const handle = await getKeyHandle('chat');
		expect(handle?.fingerprint).toBe('f'.repeat(16));
		expect(await handle?.decrypt('cipher')).toBe('hello');
		expect(ops()).toEqual(['keysStateHandle', 'keysStateDecrypt']);

		calls.length = 0;
		let first = true;
		replies.keysStateHandle = () => (first ? ((first = false), null) : { fingerprint: 'a'.repeat(16), source: 'injected', timestamp: 1, persisted: true, state: 'ready' });
		chatKeyManager.injectKey('other', KEY, 'bulk_init');
		calls.length = 0;
		await getKeyHandle('other');
		expect(ops()).toEqual(['keysStateHandle', 'keysStateOffer', 'keysStateHandle']);
	});

	it('returns null when no key can be loaded', async () => {
		vi.doMock('../../encryption/MessageEncryptor', () => ({ decryptWithChatKey: vi.fn(), encryptWithChatKey: vi.fn() }));
		vi.resetModules();
		const { getKeyHandle } = await import('../../encryption/chatKeyHandles');
		replies.keysStateHandle = null;
		expect(await getKeyHandle('missing')).toBeNull();
		expect(ops()).toEqual(['keysStateHandle']);
	});
});
