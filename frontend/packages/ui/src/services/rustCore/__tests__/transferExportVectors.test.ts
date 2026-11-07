// TS-generated vectors for the Rust chat export (`transfer` unit, web_transfer_export.rs).
// The committed JSON (packages/openmates-rust/src/web_transfer_export_ts_vectors.json) holds,
// per case, the exact Rust request the page adapter builds plus the output of the existing
// TypeScript exporter (the oracle). This test fails if either drifts; the Rust unit tests replay
// the same file. Regenerate: OPENMATES_REGEN_VECTORS=1 vitest run transferExportVectors.
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { EmbedFixture, YamlCase } from './helpers/transferExportCases';

const state = vi.hoisted(() => ({
	metadata: null as { title?: string; summary?: string } | null,
	chatKey: false,
	embeds: {} as Record<string, unknown>,
}));

vi.mock('../../db', () => ({ chatDB: { getMessagesForChat: vi.fn(), getChatCompressionCheckpoints: vi.fn() } }));
vi.mock('../../chatMetadataCache', () => ({ chatMetadataCache: { getDecryptedMetadata: async () => state.metadata } }));
vi.mock('../../encryption/ChatKeyManager', () => ({ chatKeyManager: { getKey: async () => (state.chatKey ? 'chat-key' : null) } }));
vi.mock('../../cryptoService', () => {
	const decrypt = async (encrypted: string) => {
		if (encrypted.includes('throw')) throw new Error('decrypt failed');
		return encrypted.includes('bad') ? null : `dec:${encrypted}`;
	};
	return { decryptWithChatKey: decrypt, decryptWithMasterKey: decrypt };
});
vi.mock('../../../message_parsing/serializers', () => ({
	tipTapToCanonicalMarkdown: (doc: { __markdown?: string }) => doc.__markdown ?? '',
}));
vi.mock('../../embedResolver', () => ({
	extractEmbedReferences: (markdown: string) => [...markdown.matchAll(/\[embed:([A-Za-z0-9_-]+)\]/g)].map((m) => ({ type: 'embed', embed_id: m[1] })),
	loadEmbeds: async (ids: string[]) => ids.filter((id) => id in state.embeds).map((id) => {
		const fixture = state.embeds[id] as EmbedFixture;
		return { embed_id: id, type: fixture.type, status: fixture.status, content: fixture.content, createdAt: fixture.createdAt, updatedAt: fixture.updatedAt, text_preview: fixture.text_preview, embed_ids: fixture.embed_ids };
	}),
	decodeToonContent: async (content: string) => {
		const fixture = Object.values(state.embeds).find((candidate) => (candidate as EmbedFixture).content === content) as EmbedFixture;
		if (fixture.decodeFails) throw new Error('toon decode failed');
		return fixture.decoded;
	},
}));
// Draft kind is Rust policy; the oracle here is the original TypeScript expression.
vi.mock('../transfer/transferUnitClient', () => ({
	transferCall: async (op: string, payload: { draft: string }) => {
		if (op !== 'exportDraftKind') throw new Error(`unexpected transfer op ${op}`);
		return { kind: 'ok', cleartext: originalIsCleartextDraft(payload.draft) };
	},
}));

import { restorePIIInText } from '../../../components/enter_message/services/piiDetectionService';
import { chatExportPageIO, convertChatToYaml, generateChatFilename } from '../../chatExportService';
import { buildChatYamlRequest } from '../transfer/rustChatExport';
import { exportJsonReplacer, wellFormed } from '../transfer/transferUnit';
import { draftCases, filenameCases, piiCases, yamlCases } from './helpers/transferExportCases';
import type { Chat, Message } from '../../../types/chat';

const VECTORS = resolve(__dirname, '../../../../../../../packages/openmates-rust/src/web_transfer_export_ts_vectors.json');
const NOW = '2026-11-06T12:00:00.000Z';

function originalIsCleartextDraft(draft: string): boolean {
	return !draft.includes('encrypted:') && !draft.startsWith('v1:') && draft.length < 1000;
}

/** What the Rust request looks like on the wire (the unit handler's JSON envelope). */
const onWire = (value: unknown) => JSON.parse(JSON.stringify(value, exportJsonReplacer));

async function yamlVector(testCase: YamlCase) {
	state.metadata = testCase.metadata ?? null;
	state.chatKey = testCase.chatKey ?? false;
	state.embeds = testCase.embeds ?? {};
	const chat = testCase.chat as Chat;
	const messages = testCase.messages as unknown as Message[];
	const ts = await convertChatToYaml(chat, messages, testCase.includeLink ?? false, testCase.pii, testCase.hydration);
	const request = await buildChatYamlRequest(
		{ chat, messages, includeLink: testCase.includeLink ?? false, piiOptions: testCase.pii, hydration: testCase.hydration },
		chatExportPageIO, NOW,
	);
	return { name: testCase.name, request: onWire(request), out: wellFormed(ts) };
}

async function filenameVector(testCase: (typeof filenameCases)[number]) {
	state.metadata = testCase.metadataTitle === undefined ? null : { title: testCase.metadataTitle };
	const request = onWire({
		createdAt: testCase.createdAt, titleDecrypted: testCase.metadataTitle ?? null, titlePlain: testCase.plainTitle ?? null, extension: testCase.extension,
	});
	try {
		const chat = { chat_id: 'chat-1', created_at: testCase.createdAt, title: testCase.plainTitle } as Chat;
		return { name: testCase.name, request, out: { ok: true, filename: wellFormed(await generateChatFilename(chat, testCase.extension)) } };
	} catch (error) {
		return { name: testCase.name, request, out: { ok: false, message: (error as Error).message } };
	}
}

async function generate() {
	vi.useFakeTimers();
	vi.setSystemTime(new Date(NOW));
	try {
		const yaml = [];
		for (const testCase of yamlCases) yaml.push(await yamlVector(testCase));
		const filename = [];
		for (const testCase of filenameCases) filename.push(await filenameVector(testCase));
		return {
			now: NOW,
			yaml,
			filename,
			pii: piiCases.map((c) => ({
				name: c.name, text: c.text, mappings: c.mappings.map((m) => ({ placeholder: m.placeholder, original: m.original })),
				out: wellFormed(restorePIIInText(c.text, c.mappings)),
			})),
			draftKind: draftCases.map((draft) => ({ draft, cleartext: originalIsCleartextDraft(draft) })),
		};
	} finally {
		vi.useRealTimers();
	}
}

describe('chat export parity vectors (TypeScript side)', () => {
	beforeEach(() => vi.clearAllMocks());
	afterEach(() => vi.useRealTimers());

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('TypeScript exporter and request builder match the committed vectors', async () => {
		const generated = await generate();
		if (process.env.OPENMATES_REGEN_VECTORS === '1') {
			writeFileSync(VECTORS, `${JSON.stringify(generated, null, 1)}\n`);
		}
		expect(generated).toEqual(JSON.parse(readFileSync(VECTORS, 'utf8')));
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('covers the odd inputs the Rust port must reproduce', async () => {
		const generated = await generate();
		const yaml = (name: string) => generated.yaml.find((v) => v.name === name)!.out;
		expect(yaml('timestamps-invalid-and-extreme')).toContain('completed_at: "2026-11-06T12:00:00.000Z"');
		expect(yaml('embeds-nested-and-numbers')).toContain('NaN');
		expect(yaml('embeds-nested-and-numbers')).toContain('1e+21');
		expect(generated.filename.filter((v) => !v.out.ok).map((v) => v.name)).toEqual([
			'nan-created-at', 'undefined-created-at', 'infinite-created-at', 'out-of-range',
		]);
	});
});
