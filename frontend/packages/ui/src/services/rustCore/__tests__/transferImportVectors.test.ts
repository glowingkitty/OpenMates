// TS-generated parity vectors for the shared Rust chat import parsers.
// The committed JSON (packages/openmates-rust/src/web_transfer_ts_vectors.json)
// holds inputs plus the outcomes of the existing TypeScript service
// (chatImportService.ts, flag off). This test fails if the TypeScript behaviour
// drifts from the vectors; the Rust unit tests (web_transfer_tests.rs) replay
// the same file against web_transfer*.rs.
import { webcrypto } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import JSZip from 'jszip';
import { describe, expect, it, vi } from 'vitest';

// test-setup.ts replaces crypto with stubs; source fingerprints need real SHA-256.
vi.stubGlobal('crypto', webcrypto);
vi.mock('../../db', () => ({ chatDB: {} }));
vi.mock('../../encryption/ChatKeyManager', () => ({ chatKeyManager: {} }));
vi.mock('../../encryption/MessageEncryptor', () => ({ encryptWithChatKey: vi.fn() }));

import { buildMessageBatches, estimateImportCost, parseImportFile, type ParsedImportChat } from '../../chatImportService';

const VECTORS = resolve(__dirname, '../../../../../../../packages/openmates-rust/src/web_transfer_ts_vectors.json');
const vectors = JSON.parse(readFileSync(VECTORS, 'utf8'));

async function run(file: File, selected?: string) {
	try {
		const parsed = await parseImportFile(file, selected as never);
		return {
			ok: true, parsed: JSON.parse(JSON.stringify(parsed)),
			estimates: parsed.chats.map((chat) => { const e = estimateImportCost([chat]); return [e.totalInputTokens, e.messageCount]; }),
		};
	} catch (error) {
		return { ok: false, message: (error as Error).message, syntax: error instanceof SyntaxError };
	}
}

describe('chat import parity vectors (TypeScript side)', () => {
	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('JSON exports parse to the committed vectors', async () => {
		for (const c of vectors.json) {
			expect(await run(new File([c.text], c.fileName), c.selectedSource), c.name).toEqual(c.out);
		}
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('ZIP exports parse to the committed vectors with the recorded entry order', async () => {
		for (const c of vectors.zip) {
			const zip = new JSZip();
			for (const [name, text] of Object.entries(c.entries as Record<string, string>)) zip.file(name, text);
			const bytes = await zip.generateAsync({ type: 'arraybuffer' });
			const loaded = await JSZip.loadAsync(bytes);
			expect(Object.values(loaded.files).map((e) => ({ name: e.name, dir: e.dir })), c.name).toEqual(c.zipEntries);
			expect(await run(new File([bytes], c.fileName), c.selectedSource), c.name).toEqual(c.out);
		}
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('scan batch boundaries match the committed vectors', () => {
		for (const c of vectors.batches) {
			const chats = c.counts.map((n: number, i: number) => ({ source_fingerprint: c.fingerprints[i], messages: Array.from({ length: n }, () => ({})) }));
			let out;
			try {
				out = { ok: true, batches: buildMessageBatches(chats as unknown as ParsedImportChat[], c.maxMessages)
					.map((b) => [b.chatIndex, b.chunkIndex, b.chunkIndex * c.maxMessages, b.chunkIndex * c.maxMessages + b.chat.messages.length, b.batchId]) };
			} catch (error) {
				out = { ok: false, message: (error as Error).message };
			}
			expect(out).toEqual(c.out);
		}
	});
});
