// @vitest-environment node
// (Node WebCrypto: jsdom typed arrays are cross-realm for crypto.subtle, and
// test-setup.ts stubs globalThis.crypto, so the real one is installed below.)
// TS parity vectors for the shared Rust connected-account write plans. The
// committed JSON (packages/openmates-rust/src/web_connected_accounts_write_ts_vectors.json)
// holds OAuth handoffs, stored rows and the outcomes of the flag-off TypeScript
// services (connectedAccountOAuthService.ts, connectedAccountCliTransfer.ts).
// This test fails if the TypeScript behaviour drifts from the vectors; the Rust
// unit tests (web_connected_accounts_write_tests.rs) replay the same file.
import { webcrypto } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../config/api', () => ({
	getApiEndpoint: (path: string) => `https://api.test${path}`,
	getApiUrl: () => 'https://api.test'
}));

vi.mock('../../../message_parsing/utils', () => ({
	computeSHA256: vi.fn(async (value: string) => `sha:${value}`)
}));

vi.mock('../../cryptoService', () => ({
	// Vector conventions: `enc:<plaintext>` (null for FAILENC); `enc:<plaintext>` decrypts.
	encryptWithMasterKey: vi.fn(async (value: string) => (String(value).includes('FAILENC') ? null : `enc:${value}`)),
	decryptWithMasterKey: vi.fn(async (value: string) => (value.startsWith('enc:') ? value.slice(4) : null))
}));

import { encryptWithMasterKey } from '../../cryptoService';
import {
	buildEncryptedConnectedAccountRow,
	type OAuthHandoffClaimResponse
} from '../../connectedAccountOAuthService';
import { buildConnectedAccountCliImportCommand } from '../../connectedAccountCliTransfer';
import type { EncryptedConnectedAccountRow } from '../../connectedAccountStorageService';

const VECTORS = resolve(__dirname, '../../../../../../../packages/openmates-rust/src/web_connected_accounts_write_ts_vectors.json');
const vectors = JSON.parse(readFileSync(VECTORS, 'utf8'));
const COMMAND_PREFIX = 'openmates connected-accounts import --payload "';

function failure(error: unknown) {
	if (error instanceof TypeError) return { kind: 'error', code: 'malformed' };
	const message = (error as Error).message;
	if (message.startsWith('Failed to decrypt connected account field')) return { kind: 'error', code: 'decrypt' };
	if (message.startsWith('Failed to encrypt connected account OAuth field')) return { kind: 'error', code: 'encrypt', message };
	if (message === 'Connected account refresh token bundle is missing a refresh token') return { kind: 'error', code: 'missing_token', message };
	if (message === 'A passcode is required to export a connected account') return { kind: 'error', code: 'passcode' };
	return { kind: 'error', code: 'forbidden', message };
}

function fromBase64Url(text: string): ArrayBuffer {
	const padded = text.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (text.length % 4)) % 4);
	const bytes = Uint8Array.from(atob(padded), (char) => char.charCodeAt(0));
	const buffer = new ArrayBuffer(bytes.byteLength);
	new Uint8Array(buffer).set(bytes);
	return buffer;
}

/** Opens an `OMCA1.` payload the way the CLI importer does and returns its JSON text. */
async function openTransfer(encoded: string, passcode: string): Promise<string> {
	const envelope = JSON.parse(new TextDecoder().decode(fromBase64Url(encoded.slice('OMCA1.'.length))));
	const material = await crypto.subtle.importKey('raw', new TextEncoder().encode(passcode), 'PBKDF2', false, ['deriveKey']);
	const key = await crypto.subtle.deriveKey(
		{ name: 'PBKDF2', salt: fromBase64Url(envelope.kdf.salt), iterations: envelope.kdf.iterations, hash: 'SHA-256' },
		material,
		{ name: 'AES-GCM', length: 256 },
		false,
		['decrypt']
	);
	const plain = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: fromBase64Url(envelope.cipher.iv) }, key, fromBase64Url(envelope.cipher.text));
	return new TextDecoder().decode(plain);
}

describe('connected-account write vectors', () => {
	let stubCrypto: unknown;
	beforeEach(() => {
		stubCrypto = globalThis.crypto;
		Object.defineProperty(globalThis, 'crypto', { value: webcrypto, writable: true, configurable: true });
		vi.useFakeTimers({ toFake: ['Date'] });
		vi.setSystemTime(new Date('2026-01-02T03:04:05.000Z'));
	});
	afterEach(() => {
		vi.useRealTimers();
		Object.defineProperty(globalThis, 'crypto', { value: stubCrypto, writable: true, configurable: true });
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('keeps the OAuth handoff row, its await order and the storage guard', async () => {
		for (const c of vectors.oauthRows) {
			vi.mocked(encryptWithMasterKey).mockClear();
			let actual: unknown;
			try {
				const row = await buildEncryptedConnectedAccountRow({
					...c.params,
					handoff: c.params.handoff as OAuthHandoffClaimResponse
				});
				actual = { kind: 'ok', keys: Object.keys(row), row: JSON.parse(JSON.stringify(row)) };
			} catch (error) {
				actual = failure(error);
			}
			expect(actual, c.name).toEqual(c.out);
			if (c.encrypted) {
				expect(vi.mocked(encryptWithMasterKey).mock.calls.map(([value]) => value), c.name).toEqual(c.encrypted);
			}
		}
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('keeps the CLI transfer payload, its key order and the command shape', async () => {
		for (const c of vectors.transfers) {
			let command: string;
			try {
				command = await buildConnectedAccountCliImportCommand({
					row: c.row as EncryptedConnectedAccountRow,
					passcode: c.passcode
				});
			} catch (error) {
				expect(failure(error), c.name).toEqual(c.out);
				continue;
			}
			expect(command.startsWith(`${COMMAND_PREFIX}OMCA1.`), c.name).toBe(true);
			expect(command.endsWith('"'), c.name).toBe(true);
			const text = await openTransfer(command.slice(COMMAND_PREFIX.length, -1), c.passcode);
			// Byte-exact: JSON.parse keeps the vector's key order.
			expect(text, c.name).toBe(JSON.stringify(c.out.payload));
			expect({ kind: 'ok', payload: JSON.parse(text) }, c.name).toEqual(c.out);
		}
	});
});
