import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { webcrypto } from 'node:crypto';
import { describe, expect, it, vi } from 'vitest';

import { runShareStatePolicy, type ShareStateOpName } from '../../shareState/policy';
import { shareStateCall } from '../crypto/shareStateOps';
import { createCryptoUnit } from '../crypto/cryptoUnitInstaller';
import { decryptShareKeyBlob } from '../../shareEncryption';
import { decryptShareUrl } from '../../shortUrlEncryption';

const FIXTURES = resolve(__dirname, '../../../../../../../packages/openmates-rust');
const vectors = JSON.parse(readFileSync(resolve(FIXTURES, 'src/web_share_state_ts_vectors.json'), 'utf8'));
const formats = JSON.parse(readFileSync(resolve(FIXTURES, 'tests/crypto_fixtures/ts_web_formats.json'), 'utf8'));

interface VectorCase { name: string; input: unknown; expected: unknown }

describe('share state parity vectors', () => {
	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('TypeScript rules reproduce every recorded vector outcome', () => {
		const ops = Object.entries(vectors.ops) as [ShareStateOpName, VectorCase[]][];
		expect(ops.length).toBeGreaterThanOrEqual(30);
		for (const [op, cases] of ops) {
			for (const c of cases) {
				expect(runShareStatePolicy(op, c.input), `${op}: ${c.name}`).toEqual(c.expected);
			}
		}
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('TypeScript share-link and short-URL decryption accept the TS-produced fixtures', async () => {
		// The vitest environment's crypto object lacks deriveKey; the real Node WebCrypto is what browsers run.
		vi.stubGlobal('crypto', webcrypto);
		try {
			const share = formats.share;
			for (const c of share.chat) {
				const opened = await decryptShareKeyBlob(share.chat_id, c.blob, share.generated_at + 10, c.password ?? undefined);
				expect(opened, c.label).toEqual({ success: true, chatEncryptionKey: formats.keys.chat_key_b64 });
			}
			const short = share.short_url;
			expect(await decryptShareUrl(short.encrypted, short.token, short.short_key)).toBe(short.url);
		} finally {
			vi.unstubAllGlobals();
		}
	});
});

describe('crypto unit share state op', () => {
	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('routes shareState to the Rust export and rethrows an error answer', async () => {
		const calls: unknown[][] = [];
		const own: Record<string, unknown> = {
			shareStateDecide: (name: string, input: string) => {
				calls.push([name, input]);
				return name === 'boom' ? JSON.stringify({ error: 'bad share' }) : JSON.stringify({ ok: true });
			}
		};
		const binding = new Proxy(own, { get: (target, name) => target[name as string] ?? (() => null) });
		const unit = createCryptoUnit(binding);
		const client = {
			call: async <T>(op: string, ...args: unknown[]) => {
				const replies = await unit.handle({ version: 1, requests: [{ id: 1, op: op as never, args }] });
				const response = replies!.responses[0];
				if (!('value' in response)) throw new Error('crypto unit refused the request');
				return response.value as T;
			}
		};
		expect(await shareStateCall(client as never, 'queueRetryDecision', { retry_count: 1 })).toEqual({ ok: true });
		expect(calls[0]).toEqual(['queueRetryDecision', '{"retry_count":1}']);
		await expect(shareStateCall(client as never, 'boom', {})).rejects.toThrow('bad share');
	});
});
