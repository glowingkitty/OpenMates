// contract-test-file: tooling
// Page-side decrypt memo of the Rust web crypto client (cryptoResultMemo.ts):
// repeated successful decrypts skip the Worker round trip, failures always go
// to the Worker again, byte results are private copies, clears drop everything.
import { webcrypto } from 'node:crypto';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { WebCryptoClient, type WebCryptoBatch, type WebCryptoEndpoint, type WebCryptoReplies } from '../crypto/webCryptoClient';

const KEY = new Uint8Array(32).fill(7);
const OTHER_KEY = new Uint8Array(32).fill(9);
const enc = new TextEncoder();

/** Worker stand-in: 'bad' fails, 'mm' carries a foreign fingerprint, master decrypts echo the text as bytes. */
function answer(op: string, args: unknown[]): unknown {
	if (op === 'bulk') {
		const [inner, , items] = args as [string, unknown, string[]];
		const values = items.map((text) => answer(inner, [null, text]));
		return inner === 'masterDecrypt' ? { values, errors: [] } : values;
	}
	const text = args[1] as string;
	if (op === 'masterDecrypt') return enc.encode(`plain:${text}`);
	if (text === 'bad') return null;
	if (text === 'mm') return { fingerprintMismatch: 'deadbeef' };
	return `plain:${text}`;
}

function loopback() {
	const sent: WebCryptoBatch[] = [];
	let replies: ((value: WebCryptoReplies) => void) | null = null;
	const endpoint: WebCryptoEndpoint = {
		send(batch) {
			sent.push(structuredClone(batch));
			queueMicrotask(() => replies?.({ version: 1, responses: batch.requests.map((request) => ({ id: request.id, ok: true, value: answer(request.op, request.args) })) }));
		},
		onReplies(listener) { replies = listener; },
		onFailure() {},
		close: vi.fn()
	};
	const requests = () => sent.flatMap((batch) => batch.requests);
	return { endpoint, sent, requests };
}

describe('web crypto client decrypt memo', () => {
	let masterKey: CryptoKey;
	beforeEach(async () => {
		masterKey = await webcrypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, false, ['decrypt']) as CryptoKey;
		vi.stubGlobal('CryptoKey', masterKey.constructor);
	});
	afterEach(() => vi.unstubAllGlobals());

	it('answers a repeated chat decrypt with equal key bytes without a Worker request', async () => {
		const { endpoint, requests } = loopback();
		const client = new WebCryptoClient(() => endpoint);
		expect(await client.call('decryptChatContent', new Uint8Array(KEY), 'a')).toBe('plain:a');
		expect(await client.call('decryptChatContent', new Uint8Array(KEY), 'a')).toBe('plain:a');
		expect(requests()).toHaveLength(1);
		expect(client.stats.memoHits).toBe(1);
		expect(client.stats.calls.decryptChatContent).toBe(2);
		// Other key bytes or another ciphertext are new requests.
		expect(await client.call('decryptChatContent', new Uint8Array(OTHER_KEY), 'a')).toBe('plain:a');
		expect(await client.call('decryptChatContent', new Uint8Array(KEY), 'b')).toBe('plain:b');
		expect(requests()).toHaveLength(3);
	});

	it('never memoizes a failed decrypt or a fingerprint mismatch', async () => {
		const { endpoint, requests } = loopback();
		const client = new WebCryptoClient(() => endpoint);
		for (let round = 0; round < 2; round += 1) {
			expect(await client.call('decryptChatContent', new Uint8Array(KEY), 'bad')).toBeNull();
			expect(await client.call('decryptChatContent', new Uint8Array(KEY), 'mm')).toEqual({ fingerprintMismatch: 'deadbeef' });
		}
		expect(requests()).toHaveLength(4);
		expect(client.stats.memoHits).toBe(0);
	});

	it('keys master decrypts by CryptoKey identity and hands out private byte copies', async () => {
		const { endpoint, requests } = loopback();
		const client = new WebCryptoClient(() => endpoint);
		const first = await client.call<Uint8Array>('masterDecrypt', masterKey, 'k');
		first.fill(0);
		const second = await client.call<Uint8Array>('masterDecrypt', masterKey, 'k');
		expect(Array.from(second)).toEqual(Array.from(enc.encode('plain:k')));
		second.fill(0);
		expect(Array.from(await client.call<Uint8Array>('masterDecrypt', masterKey, 'k'))).toEqual(Array.from(enc.encode('plain:k')));
		expect(requests()).toHaveLength(1);
		const otherMaster = await webcrypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, false, ['decrypt']) as CryptoKey;
		await client.call('masterDecrypt', otherMaster, 'k');
		expect(requests()).toHaveLength(2);
	});

	it('shares one request between identical calls in flight, each with its own bytes', async () => {
		const { endpoint, requests } = loopback();
		const client = new WebCryptoClient(() => endpoint);
		const [a, b] = await Promise.all([
			client.call<Uint8Array>('masterDecrypt', masterKey, 'k'),
			client.call<Uint8Array>('masterDecrypt', masterKey, 'k')
		]);
		expect(requests()).toHaveLength(1);
		expect(requests()[0].op).toBe('masterDecrypt');
		expect(client.stats.memoShared).toBe(1);
		expect(a).not.toBe(b);
		a.fill(0);
		expect(Array.from(b)).toEqual(Array.from(enc.encode('plain:k')));
	});

	it('drops every memoized result on clearChatKeys', async () => {
		const { endpoint, requests } = loopback();
		const client = new WebCryptoClient(() => endpoint);
		await client.call('decryptChatContent', new Uint8Array(KEY), 'a');
		await client.call('masterDecrypt', masterKey, 'k');
		await client.clearChatKeys();
		const before = requests().length;
		await client.call('decryptChatContent', new Uint8Array(KEY), 'a');
		await client.call('masterDecrypt', masterKey, 'k');
		expect(requests().length).toBe(before + 2);
		expect(client.stats.memoHits).toBe(0);
	});

	it('never memoizes encryption (fresh IV per call)', async () => {
		const { endpoint, requests } = loopback();
		const client = new WebCryptoClient(() => endpoint);
		await client.call('encryptChatContent', new Uint8Array(KEY), 'a');
		await client.call('encryptChatContent', new Uint8Array(KEY), 'a');
		expect(requests()).toHaveLength(2);
	});
});
