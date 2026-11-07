// TS-generated vectors for the Rust ZIP export planning (`transfer` unit,
// web_transfer_zip.rs and web_transfer_account_export.rs). The committed JSON
// (packages/openmates-rust/src/web_transfer_zip_ts_vectors.json) holds, per case, the exact
// request the page adapter builds plus what the existing TypeScript exporters produce
// (the oracle). This test fails if either drifts; the Rust unit tests replay the same file.
// Regenerate: OPENMATES_REGEN_VECTORS=1 vitest run transferZipVectors.
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
	accountCases, zipApplicationCases, zipChatCases, zipCodeFilesCases,
	type AccountCase, type ZipApplicationCase, type ZipChatCase, type ZipCodeFilesCase,
} from './helpers/transferZipCases';

const state = vi.hoisted(() => ({
	/** Every `file(path, data)` written by the mocked JSZip, in call order. */
	written: [] as Array<{ path: string; data: unknown }>,
	downloads: [] as string[],
	embeds: {} as Record<string, { content: string; decoded: unknown }>,
}));

vi.mock('jszip', () => {
	class FakeZip {
		file(path: string, data: unknown) { state.written.push({ path, data }); return this; }
		folder() { return this; }
		async generateAsync() { return new Blob([]); }
	}
	return { default: FakeZip };
});
vi.mock('../../db', () => ({ chatDB: { getMessagesForChat: vi.fn(), getChatCompressionCheckpoints: vi.fn() } }));
vi.mock('../../chatMetadataCache', () => ({ chatMetadataCache: { getDecryptedMetadata: async () => null } }));
vi.mock('../../encryption/ChatKeyManager', () => ({ chatKeyManager: { getKey: async () => null } }));
vi.mock('../../cryptoService', () => ({ decryptWithChatKey: async () => null, decryptWithMasterKey: async () => null }));
vi.mock('../../../message_parsing/serializers', () => ({
	tipTapToCanonicalMarkdown: (doc: { __markdown?: string }) => doc.__markdown ?? '',
	tipTapToReadableMarkdown: async (content: unknown) => {
		if (typeof content === 'string') return content;
		const doc = content as { __markdown?: string; __throw?: boolean };
		if (doc.__throw) throw new Error('serialization failed');
		return doc.__markdown ?? '';
	},
}));
vi.mock('../../embedResolver', () => ({
	extractEmbedReferences: () => [],
	loadEmbeds: async (ids: string[]) => ids.filter((id) => id in state.embeds).map((id) => ({ embed_id: id, content: state.embeds[id].content })),
	decodeToonContent: async (content: string) => Object.values(state.embeds).find((e) => e.content === content)?.decoded,
}));
vi.mock('../../../components/embeds/images/imageEmbedCrypto', () => ({ fetchAndDecryptImage: vi.fn() }));
vi.mock('../../encryption/mediaEncryption', () => ({ hasMediaEncryptionMetadata: () => false }));
vi.mock('../../../components/embeds/images/imageDownloadUtils', () => ({ generateImageFilename: vi.fn(), embedPngMetadata: vi.fn() }));
vi.mock('../../generatedAudioExport', () => ({ getStaticGeneratedAudioDownload: vi.fn() }));
vi.mock('../../../demo_chats/exampleChatFiles', () => ({ getEmbedFileReferences: () => [], extractEmbedIdsFromContent: () => [] }));
vi.mock('../transfer/transferUnitClient', () => ({ transferCall: async () => { throw new Error('vector generation never calls the unit'); } }));

import { buildAccountExportV1EntriesTs } from '../../accountExportService';
import {
	chatZipBase, downloadApplicationProjectZip, downloadChatsAsZip, downloadCodeFilesAsZip, writeChatZipTs,
	type ChatZipFiles,
} from '../../zipExportService';
import { buildAccountExportRequest, buildChatZipRequest, resolveZipSource, type ChatZipInput } from '../transfer/rustChatZip';
import { exportJsonReplacer, wellFormed } from '../transfer/transferUnit';
import type { Chat, Message } from '../../../types/chat';

const VECTORS = resolve(__dirname, '../../../../../../../packages/openmates-rust/src/web_transfer_zip_ts_vectors.json');
const NOW = '2026-11-06T12:34:56.789Z';
const EXPORTED_AT = '2026-11-06T12:00:00.000Z';

/** What the Rust request looks like on the wire (the unit handler's JSON envelope). */
const onWire = (value: unknown) => JSON.parse(JSON.stringify(value, exportJsonReplacer));
const readable = async (content: unknown) => {
	const { tipTapToReadableMarkdown } = await import('../../../message_parsing/serializers');
	return tipTapToReadableMarkdown(content as never);
};

function fullFiles(partial: ZipChatCase['files']): ChatZipFiles {
	return { code: [], transcripts: [], images: [], generatedAudio: [], staticFiles: [], audio: [], pdfs: [], ...partial } as ChatZipFiles;
}

/** Maps a written entry back to the page data it came from, or `null` for Rust-built text. */
function sourceOf(data: unknown, input: ChatZipInput): [string, number, number?] | null {
	const { files } = input;
	const find = <T,>(list: T[], match: (item: T) => boolean) => list.findIndex(match);
	const checks: Array<[string, () => number | [number, number]]> = [
		['code', () => find(files.code, (f) => f.content === data)],
		['transcript', () => find(files.transcripts, (f) => f.content === data)],
		['image', () => find(files.images, (f) => f.blob === data)],
		['generatedAudio', () => find(files.generatedAudio, (f) => f.blob === data)],
		['staticFile', () => find(files.staticFiles, (f) => f.blob === data)],
		['audio', () => find(files.audio, (f) => f.blob === data)],
		['audioTranscript', () => find(files.audio, (f) => f.transcript === data)],
		['pdf', () => {
			for (let i = 0; i < files.pdfs.length; i++) {
				const page = files.pdfs[i].pages.findIndex((p) => p.blob === data);
				if (page >= 0) return [i, page];
			}
			return -1;
		}],
	];
	for (const [group, locate] of checks) {
		const found = locate();
		if (Array.isArray(found)) return [group, found[0], found[1]];
		if (found >= 0) return [group, found];
	}
	return null;
}

async function chatVector(testCase: ZipChatCase) {
	const chat = testCase.chat as unknown as Chat;
	const messages = testCase.messages as unknown as Message[];
	const input: ChatZipInput = {
		filename: testCase.filename, completenessJson: testCase.completenessJson, chat, messages,
		piiOptions: testCase.pii, files: fullFiles(testCase.files), yaml: 'YAML-BODY',
	};
	state.written.length = 0;
	const zipName = await writeChatZipTs({ file: (path, data) => state.written.push({ path, data }) }, input);
	// Position tells yaml/markdown/metadata apart; page data is matched by identity.
	const hasMetadata = testCase.completenessJson !== null;
	const base = chatZipBase(testCase.filename);
	const out = state.written.map(({ path, data }, index) => {
		if (index === (hasMetadata ? 1 : 0)) return { path, src: ['yaml'] };
		if (index === (hasMetadata ? 0 : -1) || index === (hasMetadata ? 2 : 1)) return { path, text: wellFormed(String(data)) };
		const src = sourceOf(data, input);
		if (!src) throw new Error(`${testCase.name}: ${path} has no page source`);
		return { path, src };
	});
	const request = await buildChatZipRequest(input, readable);
	return { name: testCase.name, request: onWire(request), out: { base, zipName, entries: out } };
}

async function codeFilesVector(testCase: ZipCodeFilesCase) {
	const { parseCodeEmbedContent } = await import('../../../components/embeds/code/codeEmbedContent');
	const request = {
		nowIso: NOW,
		files: testCase.files.map((file) => {
			const parsed = parseCodeEmbedContent(file.code, { language: file.language, filename: file.filename });
			return { filename: file.filename ?? null, headerFilename: parsed.filename ?? null, language: parsed.language || file.language };
		}),
	};
	state.written.length = 0;
	await downloadCodeFilesAsZip(testCase.files);
	// A single file is downloaded directly (no zip): its name is the only download.
	const names = testCase.files.length === 1 ? [state.downloads[state.downloads.length - 1]] : state.written.map((entry) => entry.path);
	return {
		name: testCase.name, request: onWire(request),
		out: { zipName: testCase.files.length === 1 ? null : state.downloads[state.downloads.length - 1], names },
	};
}

async function applicationVector(testCase: ZipApplicationCase) {
	state.embeds = Object.fromEntries(testCase.paths.map((_, i) => [`app-${i}`, { content: `toon-${i}`, decoded: { code: `code ${i}`, language: 'text' } }]));
	state.written.length = 0;
	const fileRefs = testCase.paths.map((path, i) => ({ path, embed_id: `app-${i}` })).filter((ref) => ref.path);
	await downloadApplicationProjectZip({ appName: testCase.appName, fileRefs });
	return {
		name: testCase.name,
		request: { appName: testCase.appName || null, paths: fileRefs.map((ref) => ref.path) },
		out: { zipName: state.downloads[state.downloads.length - 1], paths: state.written.map((entry) => entry.path) },
	};
}

function accountVector(testCase: AccountCase) {
	const bundle = testCase.bundle as unknown as Parameters<typeof buildAccountExportV1EntriesTs>[0];
	const request = onWire(buildAccountExportRequest(bundle, EXPORTED_AT));
	try {
		const entries = buildAccountExportV1EntriesTs(bundle, EXPORTED_AT).map((e) => ({ path: e.path, content: wellFormed(e.content) }));
		return { name: testCase.name, request, out: { kind: 'ok', entries } };
	} catch (error) {
		return { name: testCase.name, request, out: { kind: 'error', message: (error as Error).message } };
	}
}

async function bulkVector() {
	state.written.length = 0;
	const chat = { chat_id: 'c1', title: 'Bulk', created_at: 1_793_000_000 } as unknown as Chat;
	await downloadChatsAsZip([chat], new Map());
	return { request: { nowIso: NOW }, out: { zipName: state.downloads[state.downloads.length - 1] } };
}

async function generate() {
	vi.useFakeTimers();
	vi.setSystemTime(new Date(NOW));
	try {
		const chat = [];
		for (const testCase of zipChatCases) chat.push(await chatVector(testCase));
		const codeFiles = [];
		for (const testCase of zipCodeFilesCases) codeFiles.push(await codeFilesVector(testCase));
		const application = [];
		for (const testCase of zipApplicationCases) application.push(await applicationVector(testCase));
		return {
			now: NOW,
			exportedAt: EXPORTED_AT,
			chat,
			codeFiles,
			application,
			bulk: await bulkVector(),
			account: accountCases.map(accountVector),
		};
	} finally {
		vi.useRealTimers();
	}
}

describe('ZIP export parity vectors (TypeScript side)', () => {
	let realUrlStatics: { create: typeof URL.createObjectURL; revoke: typeof URL.revokeObjectURL };
	beforeEach(() => {
		state.downloads.length = 0;
		// Patch the statics instead of replacing URL: test-setup relies on `instanceof URL`.
		realUrlStatics = { create: URL.createObjectURL, revoke: URL.revokeObjectURL };
		URL.createObjectURL = () => 'blob:x';
		URL.revokeObjectURL = () => undefined;
		vi.stubGlobal('document', {
			createElement: () => {
				const link = { href: '', set download(value: string) { state.downloads.push(value); }, click: () => undefined };
				return link;
			},
			body: { appendChild: () => undefined, removeChild: () => undefined },
		});
	});
	afterEach(() => {
		vi.useRealTimers();
		vi.unstubAllGlobals();
		URL.createObjectURL = realUrlStatics.create;
		URL.revokeObjectURL = realUrlStatics.revoke;
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('TypeScript exporters and request builders match the committed vectors', async () => {
		const generated = await generate();
		if (process.env.OPENMATES_REGEN_VECTORS === '1') {
			writeFileSync(VECTORS, `${JSON.stringify(generated, null, 1)}\n`);
		}
		const committed = JSON.parse(readFileSync(VECTORS, 'utf8'));
		if (JSON.stringify(committed) !== JSON.stringify(generated) && process.env.CI) {
			// Hosts without a writable checkout (isolated CI) expose the regenerated file in the log.
			const text = Buffer.from(`${JSON.stringify(generated, null, 1)}\n`).toString('base64');
			for (let at = 0; at < text.length; at += 2000) process.stdout.write(`VECTORS_B64 ${at / 2000} ${text.slice(at, at + 2000)}\n`);
		}
		expect(generated).toEqual(committed);
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('covers the odd inputs the Rust port must reproduce', async () => {
		const generated = await generate();
		const markdown = (name: string) => generated.chat.find((v) => v.name === name)!.out.entries.find((e) => e.path.endsWith('.md'))!;
		expect(markdown('invalid-chat-created-at-empties-markdown')).toMatchObject({ text: '' });
		expect(generated.chat.find((v) => v.name === 'every-file-group')!.out.entries.map((e) => e.path)).toContain('uploads/audio/trailing._transcript.txt');
		expect(generated.account.filter((v) => v.out.kind === 'error').length).toBeGreaterThanOrEqual(5);
		expect(generated.application.find((v) => v.name === 'symbols-only-name')!.out.zipName).toBe('application.zip');
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('resolves every plan source to the page data it names', () => {
		const input = { files: fullFiles({ code: [{ content: 'c0' }], audio: [{ blob: 'b', transcript: 't' }] }), yaml: 'y' } as unknown as ChatZipInput;
		expect(resolveZipSource(['yaml', 0], input)).toBe('y');
		expect(resolveZipSource(['code', 0], input)).toBe('c0');
		expect(resolveZipSource(['audioTranscript', 0], input)).toBe('t');
		expect(() => resolveZipSource(['nope', 0], input)).toThrow('Unknown zip source group nope');
	});
});
