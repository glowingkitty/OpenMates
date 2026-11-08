// contract-test-file: tooling
// Crypto unit of the shared Rust core Worker: page client batching/coalescing,
// Worker-side installer dispatch (fake binding, no WASM) and the shared-core
// endpoint (buffering, refusal, crash -> fresh unit).
import { webcrypto } from 'node:crypto';
import { describe, expect, it, vi } from 'vitest';
import {
	WEB_CRYPTO_BULK_CHUNK,
	WebCryptoClient,
	type WebCryptoBatch,
	type WebCryptoEndpoint,
	type WebCryptoReplies
} from '../crypto/webCryptoClient';
import { createCryptoUnit, installCryptoUnit } from '../crypto/cryptoUnitInstaller';
import { createSharedCryptoEndpoint } from '../crypto/sharedCryptoEndpoint';
import { SharedCoreError, type SharedRustCore } from '../host/sharedCoreRegistry';

const KEY = new Uint8Array(32).fill(7);
const OTHER_KEY = new Uint8Array(32).fill(9);

const enc = new TextEncoder();

/** Rust export stand-ins: 'bad' fails authentication, 'mm' carries a foreign fingerprint. */
function readChat(text: string) {
	if (text === 'bad') return null;
	if (text === 'mm') return { fingerprintMismatch: 'deadbeef' };
	return `plain:${text}`;
}

function fakeBinding() {
	const calls: string[] = [];
	const record = (name: string, impl: (...args: unknown[]) => unknown) => (...args: unknown[]) => {
		calls.push(name);
		return impl(...args);
	};
	let cached = 0;
	const binding: Record<string, unknown> = {
		webCryptoDecryptChatContent: record('decryptOne', async (_key, text) => { cached = 1; return readChat(text as string); }),
		webCryptoEncryptChatContent: record('encryptOne', async (_key, text) => `sealed:${text}`),
		webCryptoBulkDecryptChat: record('bulkDecrypt', async (_key, items) => { cached = 1; return (items as string[]).map(readChat); }),
		webCryptoBulkEncryptChat: record('bulkEncrypt', async (_key, items) => (items as string[]).map((text) => `sealed:${text}`)),
		webCryptoBulkMasterDecrypt: record('bulkMaster', async (_key, items) => {
			const texts = items as string[];
			return {
				values: texts.map((text) => (text === 'bad' ? null : enc.encode(`plain:${text}`))),
				errors: texts.flatMap((text, index) => (text === 'bad' ? [[index, 'crypto']] : []))
			};
		}),
		webCryptoClearChatKeys: record('clearKeys', () => { cached = 0; }),
		webCryptoChatKeyCacheSize: () => cached
	};
	for (const name of ['webCryptoMasterDecrypt', 'webCryptoMasterEncrypt', 'webCryptoGenerateShareKeyBlob', 'webCryptoDecryptShareKeyBlob',
		'webCryptoEncryptShareUrl', 'webCryptoDecryptShareUrl', 'webCryptoDecryptMedia', 'webCryptoChatKeyGuardBegin',
		'webCryptoChatKeyGuardAfterAnonymous', 'webCryptoChatKeyGuardAfterPersisted',
		'keysFingerprint', 'keysEqual', 'keysInjectDecision',
			'keysStateOffer', 'keysStateHandle', 'keysStateState', 'keysStateSetState', 'keysStateEnqueue', 'keysStateCancel', 'keysStatePending', 'keysStateMarkPersisted', 'keysStateReset', 'keysStateRemove', 'keysStateClear', 'keysStateStats', 'keysStateDecrypt', 'keysStateEncrypt', 'keysBulkBatches', 'keysBulkRetryStep', 'guestPromotionPlan', 'shareStateDecide', 'workDecide']) {
		binding[name] = record(name, async (...args: unknown[]) => {
			if (args[1] === 'reject') throw 'crypto';
			return new Uint8Array([args.length]);
		});
	}
	return { binding, calls };
}

/** In-process endpoint: answers through a real crypto unit over the fake binding. */
function loopback(unit = createCryptoUnit(fakeBinding().binding)) {
	const sent: WebCryptoBatch[] = [];
	let replies: ((value: WebCryptoReplies) => void) | null = null;
	let failure: ((error: Error) => void) | null = null;
	const endpoint: WebCryptoEndpoint = {
		send(batch) {
			sent.push(structuredClone(batch));
			void unit.handle(batch).then((answer) => answer && replies?.(answer));
		},
		onReplies(listener) { replies = listener; },
		onFailure(listener) { failure = listener; },
		close: vi.fn()
	};
	return { endpoint, sent, fail: (error: Error) => failure?.(error) };
}

describe('crypto unit installer', () => {
	it('refuses a binding without the crypto exports', () => {
		expect(() => createCryptoUnit({})).toThrow(/rust_web_crypto_export_missing/);
	});

	it('answers a bulk decrypt with exactly one Rust call', async () => {
		const { binding, calls } = fakeBinding();
		const unit = createCryptoUnit(binding);
		const replies = await unit.handle({ version: 1, requests: [{ id: 1, op: 'bulk', args: ['decryptChatContent', KEY, ['a', 'bad', 'mm', 'c']] }] });
		expect(calls).toEqual(['bulkDecrypt']);
		expect(replies?.responses[0]).toEqual({
			id: 1, ok: true,
			value: { values: ['plain:a', null, { fingerprintMismatch: 'deadbeef' }, 'plain:c'], errors: [] }
		});
	});

	it('seals a bulk encrypt in one Rust call and reports failed master unwraps per item', async () => {
		const { binding, calls } = fakeBinding();
		const unit = createCryptoUnit(binding);
		const sealed = await unit.handle({ version: 1, requests: [{ id: 1, op: 'bulk', args: ['encryptChatContent', KEY, ['ab', 'cde']] }] });
		expect(sealed?.responses[0]).toEqual({ id: 1, ok: true, value: { values: ['sealed:ab', 'sealed:cde'], errors: [] } });
		expect(calls).toEqual(['bulkEncrypt']);
		const masterKey = await webcrypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, false, ['decrypt']);
		vi.stubGlobal('CryptoKey', masterKey.constructor);
		const unwrapped = await unit.handle({ version: 1, requests: [{ id: 2, op: 'bulk', args: ['masterDecrypt', masterKey, ['k', 'bad']] }] });
		const value = (unwrapped?.responses[0] as { value: { values: unknown[]; errors: unknown } }).value;
		expect(value.errors).toEqual([[1, 'crypto']]);
		expect(value.values[1]).toBeNull();
		expect(Array.from(value.values[0] as Uint8Array)).toEqual(Array.from(enc.encode('plain:k')));
		expect(calls).toEqual(['bulkEncrypt', 'bulkMaster']);
		vi.unstubAllGlobals();
	});

	it('refuses a bulk list with non-string items, a bad chat key or a non-CryptoKey master key', async () => {
		const { binding, calls } = fakeBinding();
		const unit = createCryptoUnit(binding);
		const replies = await unit.handle({ version: 1, requests: [
			{ id: 1, op: 'bulk', args: ['decryptChatContent', KEY, ['a', 3]] },
			{ id: 2, op: 'bulk', args: ['encryptChatContent', 'not-bytes', ['a']] },
			{ id: 3, op: 'bulk', args: ['masterDecrypt', KEY, ['a']] }
		] });
		expect(replies?.responses).toEqual([
			{ id: 1, ok: false, error: 'rust_web_crypto_bad_request' },
			{ id: 2, ok: false, error: 'crypto' },
			{ id: 3, ok: false, error: 'crypto' }
		]);
		expect(calls).toEqual([]);
	});

	it('answers errors as fixed codes per request, never failing the batch', async () => {
		const unit = createCryptoUnit(fakeBinding().binding);
		const replies = await unit.handle({ version: 1, requests: [
			{ id: 1, op: 'masterDecrypt', args: [{}, 'reject'] },
			{ id: 2, op: 'nope' as never, args: [] },
			{ id: 3, op: 'encryptChatContent', args: [KEY, 'x'] }
		] });
		expect(replies?.responses).toEqual([
			{ id: 1, ok: false, error: 'crypto' },
			{ id: 2, ok: false, error: 'rust_web_crypto_unknown_op' },
			{ id: 3, ok: true, value: 'sealed:x' }
		]);
	});

	it('ignores malformed batches and clears the Rust key cache', async () => {
		const { binding, calls } = fakeBinding();
		const unit = createCryptoUnit(binding);
		expect(await unit.handle({ version: 2, requests: [] })).toBeNull();
		await unit.handle({ version: 1, requests: [{ id: 1, op: 'decryptChatContent', args: [KEY, 'a'] }] });
		const size = await unit.handle({ version: 1, requests: [{ id: 2, op: 'chatKeyCacheSize', args: [] }] });
		expect(size?.responses[0]).toEqual({ id: 2, ok: true, value: 1 });
		await unit.handle({ version: 1, requests: [{ id: 3, op: 'clearChatKeys', args: [] }] });
		expect(calls).toContain('clearKeys');
		const after = await unit.handle({ version: 1, requests: [{ id: 4, op: 'chatKeyCacheSize', args: [] }] });
		expect(after?.responses[0]).toEqual({ id: 4, ok: true, value: 0 });
	});

	it('serves the port and clears caches on dispose', async () => {
		const { binding, calls } = fakeBinding();
		const channel = new MessageChannel();
		const dispose = installCryptoUnit({ binding, ports: [channel.port2], generation: null, principal: null, signal: new AbortController().signal });
		const reply = new Promise<WebCryptoReplies>((resolve) => { channel.port1.onmessage = (event) => resolve(event.data); });
		channel.port1.postMessage({ version: 1, requests: [{ id: 5, op: 'decryptChatContent', args: [KEY, 'z'] }] });
		expect((await reply).responses).toEqual([{ id: 5, ok: true, value: 'plain:z' }]);
		(dispose as () => void)();
		expect(calls).toContain('clearKeys');
		channel.port1.close();
	});
});

describe('web crypto client batching', () => {
	it('sends concurrent calls across several awaits as one batch with one bulk per key', async () => {
		const { endpoint, sent } = loopback();
		const client = new WebCryptoClient(() => endpoint);
		const deep = async (text: string, key: Uint8Array) => {
			await Promise.resolve();
			await Promise.resolve();
			return client.call<string>('decryptChatContent', new Uint8Array(key), text);
		};
		const results = await Promise.all([
			client.call<string>('decryptChatContent', new Uint8Array(KEY), 'a'),
			deep('b', KEY),
			deep('c', OTHER_KEY),
			client.call<string>('decryptChatContent', new Uint8Array(OTHER_KEY), 'd'),
			client.call<string>('encryptChatContent', new Uint8Array(KEY), 'e')
		]);
		expect(results).toEqual(['plain:a', 'plain:b', 'plain:c', 'plain:d', 'sealed:e']);
		expect(sent).toHaveLength(1);
		expect(sent[0].requests.map((request) => request.op)).toEqual(['bulk', 'bulk', 'encryptChatContent']);
		expect(client.stats.bulkItems).toBe(4);
	});

	it('splits a large same-key group into chunked bulk requests and keeps item order', async () => {
		const { endpoint, sent } = loopback();
		const client = new WebCryptoClient(() => endpoint);
		const texts = Array.from({ length: WEB_CRYPTO_BULK_CHUNK + 44 }, (_, index) => `m${index}`);
		const results = await Promise.all(texts.map((text) => client.call<string>('decryptChatContent', new Uint8Array(KEY), text)));
		expect(results).toEqual(texts.map((text) => `plain:${text}`));
		expect(sent).toHaveLength(1);
		expect(sent[0].requests.map((request) => (request.args[2] as string[]).length)).toEqual([WEB_CRYPTO_BULK_CHUNK, 44]);
	});

	it('rejects pending calls when the unit fails and opens a fresh unit next time', async () => {
		const first = loopback();
		const second = loopback();
		const factory = vi.fn<() => WebCryptoEndpoint>().mockReturnValueOnce({ ...first.endpoint, send: () => undefined }).mockReturnValueOnce(second.endpoint);
		const client = new WebCryptoClient(factory);
		const errors = vi.spyOn(console, 'error').mockImplementation(() => undefined);
		const pending = client.call('decryptChatContent', new Uint8Array(KEY), 'a');
		await new Promise((resolve) => setTimeout(resolve, 0));
		first.fail(new Error('shared_core_crashed'));
		await expect(pending).rejects.toThrow('shared_core_crashed');
		expect(client.stats.failures.decryptChatContent).toBe(1);
		await expect(client.call('decryptChatContent', new Uint8Array(KEY), 'b')).resolves.toBe('plain:b');
		expect(factory).toHaveBeenCalledTimes(2);
		errors.mockRestore();
	});

	it('does not start a unit just to clear caches', async () => {
		const factory = vi.fn(() => loopback().endpoint);
		const client = new WebCryptoClient(factory);
		await client.clearChatKeys();
		expect(await client.chatKeyCacheSize()).toBe(0);
		expect(factory).not.toHaveBeenCalled();
		expect(client.stats.chatKeyClears).toBe(1);
	});
});

function fakeCore(open: () => Promise<MessagePort>, hold: () => () => void = () => () => undefined) {
	const crash = new Set<() => void>();
	const core = {
		openUnit: vi.fn(open),
		hold,
		onCrash: (listener: () => void) => { crash.add(listener); return () => crash.delete(listener); }
	} as unknown as SharedRustCore;
	return { core, crash: () => { for (const listener of crash) listener(); } };
}

describe('shared crypto endpoint', () => {
	it('holds the realm from send until the reply arrives', async () => {
		const channel = new MessageChannel();
		const release = vi.fn();
		const hold = vi.fn(() => release);
		const { core } = fakeCore(async () => channel.port1, hold);
		channel.port2.onmessage = () => channel.port2.postMessage({ version: 1, responses: [{ id: 1, ok: true, value: 1 }] });
		const endpoint = createSharedCryptoEndpoint(core);
		const replied = new Promise<void>((resolve) => endpoint.onReplies(() => resolve()));
		endpoint.send({ version: 1, requests: [{ id: 1, op: 'echo', args: [1] }] });
		expect(hold).toHaveBeenCalledTimes(1);
		expect(release).not.toHaveBeenCalled();
		await replied;
		expect(release).toHaveBeenCalledTimes(1);
		endpoint.close();
	});

	it('buffers batches until the crypto port opens', async () => {
		const channel = new MessageChannel();
		const { core } = fakeCore(async () => channel.port1);
		const received = new Promise<unknown>((resolve) => { channel.port2.onmessage = (event) => resolve(event.data); });
		const endpoint = createSharedCryptoEndpoint(core);
		endpoint.send({ version: 1, requests: [{ id: 1, op: 'echo', args: [1] }] });
		expect(await received).toEqual({ version: 1, requests: [{ id: 1, op: 'echo', args: [1] }] });
		expect(core.openUnit).toHaveBeenCalledWith('crypto');
		endpoint.close();
		channel.port2.close();
	});

	it('reports a refused open and a shared-core crash once', async () => {
		const refused = fakeCore(async () => { throw new SharedCoreError('unit_unavailable'); });
		const onRefused = vi.fn();
		createSharedCryptoEndpoint(refused.core).onFailure(onRefused);
		await vi.waitFor(() => expect(onRefused).toHaveBeenCalledTimes(1));
		expect(onRefused.mock.calls[0][0].message).toBe('unit_unavailable');

		const channel = new MessageChannel();
		const crashing = fakeCore(async () => channel.port1);
		const onCrash = vi.fn();
		createSharedCryptoEndpoint(crashing.core).onFailure(onCrash);
		crashing.crash();
		crashing.crash();
		expect(onCrash).toHaveBeenCalledTimes(1);
		channel.port2.close();
	});
});
