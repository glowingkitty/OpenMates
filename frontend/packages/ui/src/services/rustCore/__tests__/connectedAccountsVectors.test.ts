// TS parity vectors for the shared Rust connected-account decisions. The
// committed JSON (packages/openmates-rust/src/web_connected_accounts_ts_vectors.json)
// holds rows, broker responses and the outcomes of the TypeScript services
// (connectedAccountStorageService.ts, connectedAccountTokenBrokerService.ts).
// This test fails if the TypeScript behaviour drifts from the vectors; the
// Rust unit tests (web_connected_accounts_tests.rs) replay the same file.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../../../config/api', () => ({
	getApiEndpoint: (path: string) => `https://api.test${path}`,
	getApiUrl: () => 'https://api.test'
}));

vi.mock('../../cryptoService', () => ({
	// Vector ciphertext convention: `enc:<plaintext>` decrypts, anything else fails.
	decryptWithMasterKey: vi.fn(async (value: string) => (value.startsWith('enc:') ? value.slice(4) : null))
}));

import {
	buildConnectedAccountSendContext,
	summarizeConnectedAccountRows,
	type EncryptedConnectedAccountRow
} from '../../connectedAccountStorageService';
import { createConnectedAccountTurnTokenRefs } from '../../connectedAccountTokenBrokerService';

const VECTORS = resolve(__dirname, '../../../../../../../packages/openmates-rust/src/web_connected_accounts_ts_vectors.json');
const vectors = JSON.parse(readFileSync(VECTORS, 'utf8'));
const json = (value: unknown) => (value === undefined ? null : JSON.parse(JSON.stringify(value)));

function failure(error: unknown) {
	if (error instanceof TypeError) return { kind: 'error', code: 'malformed' };
	const message = (error as Error).message;
	if (message.startsWith('Failed to decrypt connected account field')) return { kind: 'error', code: 'decrypt' };
	if (message === 'Token broker response did not include refs') return { kind: 'error', code: 'missing_refs' };
	return { kind: 'error', code: 'forbidden', message };
}

async function outcome(run: () => Promise<unknown>) {
	try {
		return { kind: 'ok', value: json(await run()) };
	} catch (error) {
		return failure(error);
	}
}

describe('connected-account service vectors', () => {
	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('keeps send-context selection, directory and token-ref inputs', async () => {
		for (const c of vectors.sendContext) {
			const actual = await outcome(() =>
				buildConnectedAccountSendContext({ ...c.params, rows: c.rows as EncryptedConnectedAccountRow[] })
			);
			expect(actual, c.name).toEqual(c.out);
		}
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('keeps account summaries and local-connector fallbacks', async () => {
		const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
		for (const c of vectors.summaries) {
			const actual = await outcome(() => summarizeConnectedAccountRows(c.rows as EncryptedConnectedAccountRow[]));
			expect(actual, c.name).toEqual(c.out);
		}
		warn.mockRestore();
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('keeps the broker turn-token ref merge', async () => {
		for (const c of vectors.tokenRefs) {
			const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
				new Response(JSON.stringify(c.payload), { status: 200, headers: { 'Content-Type': 'application/json' } })
			);
			const actual = await outcome(() =>
				createConnectedAccountTurnTokenRefs({ chatId: 'chat-1', messageId: 'message-1', refs: c.inputs })
			);
			fetchSpy.mockRestore();
			expect(actual, c.name).toEqual(c.out);
		}
	});
});
