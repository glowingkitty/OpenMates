/**
 * TEST-04: Encryption Performance Benchmark
 *
 * Validates that 100-message encrypt/decrypt completes within 2 seconds
 * using real Web Crypto API (not jsdom stubs). This guards against
 * performance regressions that could cause sync timeouts on 100-message
 * chats — the threshold chosen because typical active chats contain
 * 50-150 messages and must sync within a single WebSocket frame window.
 *
 * Crypto environment is overridden BEFORE importing encryption modules
 * (Pitfall 2 from research: module-level globals bind at import time).
 */

import { describe, it, expect, beforeAll } from 'vitest';
import { webcrypto } from 'node:crypto';

// ---------------------------------------------------------------------------
// Crypto environment setup — MUST come before importing encryption modules
// ---------------------------------------------------------------------------

const realCrypto = webcrypto as unknown as Crypto;
Object.defineProperty(globalThis, 'crypto', {
	value: realCrypto,
	writable: true,
	configurable: true
});

// Polyfill btoa/atob — jsdom may or may not provide globalThis.window
const btoaFn = (str: string) => Buffer.from(str, 'binary').toString('base64');
const atobFn = (str: string) => Buffer.from(str, 'base64').toString('binary');

if (typeof globalThis.window !== 'undefined') {
	Object.defineProperty(globalThis.window, 'btoa', {
		value: btoaFn,
		writable: true,
		configurable: true
	});
	Object.defineProperty(globalThis.window, 'atob', {
		value: atobFn,
		writable: true,
		configurable: true
	});
}
// Also set on globalThis for environments without window
Object.defineProperty(globalThis, 'btoa', {
	value: btoaFn,
	writable: true,
	configurable: true
});
Object.defineProperty(globalThis, 'atob', {
	value: atobFn,
	writable: true,
	configurable: true
});

// ---------------------------------------------------------------------------
// Import encryption functions AFTER crypto environment is ready
// ---------------------------------------------------------------------------

import { encryptWithChatKey, decryptWithChatKey } from '../../cryptoService';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Number of messages to encrypt and decrypt in the benchmark */
const MESSAGE_COUNT = 100;

/** Maximum allowed duration in milliseconds (2 seconds per D-03) */
const MAX_DURATION_MS = 2000;

/** Number of warm-up operations before the timed benchmark */
const WARMUP_OPS = 5;

/** AES-256 key size in bytes */
const AES_KEY_BYTES = 32;

describe('TEST-04: encryption performance benchmark', () => {
	let chatKey: Uint8Array;

	beforeAll(() => {
		// Random 32-byte AES-256 key
		chatKey = new Uint8Array(AES_KEY_BYTES);
		crypto.getRandomValues(chatKey);
	});

	it('encrypts and decrypts 100 messages within 2 seconds', async () => {
		// Generate 100 messages of realistic size (100-500 chars each)
		const messages = Array.from({ length: MESSAGE_COUNT }, (_, i) => {
			const padding = 'x'.repeat(100 + i * 4); // Variable length 100-496 chars
			return `Message ${i}: Test content for performance benchmark. ${padding}`;
		});

		// Warm-up: 5 operations to JIT-warm the crypto path
		const warmupKey = new Uint8Array(AES_KEY_BYTES);
		crypto.getRandomValues(warmupKey);
		for (let i = 0; i < WARMUP_OPS; i++) {
			const ct = await encryptWithChatKey('warmup', warmupKey);
			await decryptWithChatKey(ct, warmupKey);
		}

		// Timed benchmark: encrypt all 100, then decrypt all 100
		const start = performance.now();

		const ciphertexts: string[] = [];
		for (const msg of messages) {
			ciphertexts.push(await encryptWithChatKey(msg, chatKey));
		}

		const plaintexts: (string | null)[] = [];
		for (const ct of ciphertexts) {
			plaintexts.push(await decryptWithChatKey(ct, chatKey));
		}

		const elapsed = performance.now() - start;

		// Verify correctness — every message must round-trip exactly
		for (let i = 0; i < MESSAGE_COUNT; i++) {
			expect(plaintexts[i]).toBe(messages[i]);
		}

		// Assert performance: under 2 seconds per D-03
		expect(elapsed).toBeLessThan(MAX_DURATION_MS);

		// Log timing for CI visibility
		console.log(
			`[Performance] ${MESSAGE_COUNT} encrypt + ${MESSAGE_COUNT} decrypt: ${elapsed.toFixed(1)}ms`
		);
	});
});
