// Request-side parity vectors for the Rust ZIP export planning (`transfer` unit,
// web_transfer_zip.rs and web_transfer_account_export.rs). The committed JSON
// (packages/openmates-rust/src/web_transfer_zip_ts_vectors.json) holds, per case, the exact
// request the page adapter builds plus the archive layout the Rust unit must produce. The
// TypeScript exporters that once generated the `out` side are deleted; `out` is now a frozen
// golden owned by the Rust unit tests. This test pins the `request` side the adapter builds.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it, vi } from 'vitest';
import {
	accountCases, zipApplicationCases, zipChatCases, zipCodeFilesCases,
	type ZipChatCase,
} from './helpers/transferZipCases';

vi.mock('../../../message_parsing/serializers', () => ({
	tipTapToCanonicalMarkdown: (doc: { __markdown?: string }) => doc.__markdown ?? '',
	tipTapToReadableMarkdown: async (content: unknown) => {
		if (typeof content === 'string') return content;
		const doc = content as { __markdown?: string; __throw?: boolean };
		if (doc.__throw) throw new Error('serialization failed');
		return doc.__markdown ?? '';
	},
}));
vi.mock('../transfer/transferUnitClient', () => ({ transferCall: async () => { throw new Error('vector replay never calls the unit'); } }));

import type { ChatZipFiles } from '../../zipExportService';
import { buildAccountExportRequest, buildChatZipRequest, resolveZipSource, type ChatZipInput } from '../transfer/rustChatZip';
import { exportJsonReplacer } from '../transfer/transferUnit';
import type { Chat, Message } from '../../../types/chat';

const VECTORS = resolve(__dirname, '../../../../../../../packages/openmates-rust/src/web_transfer_zip_ts_vectors.json');
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

async function chatRequest(testCase: ZipChatCase) {
	const input: ChatZipInput = {
		filename: testCase.filename, completenessJson: testCase.completenessJson,
		chat: testCase.chat as unknown as Chat, messages: testCase.messages as unknown as Message[],
		piiOptions: testCase.pii, files: fullFiles(testCase.files), yaml: 'YAML-BODY',
	};
	return onWire(await buildChatZipRequest(input, readable));
}

async function codeFilesRequest(files: Array<{ code: string; language: string; filename?: string }>, nowIso: string) {
	const { parseCodeEmbedContent } = await import('../../../components/embeds/code/codeEmbedContent');
	return {
		nowIso,
		files: files.map((file) => {
			const parsed = parseCodeEmbedContent(file.code, { language: file.language, filename: file.filename });
			return { filename: file.filename ?? null, headerFilename: parsed.filename ?? null, language: parsed.language || file.language };
		}),
	};
}

describe('ZIP export request vectors (page adapter side)', () => {
	const committed = JSON.parse(readFileSync(VECTORS, 'utf8'));

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('chat zip requests match the committed vectors', async () => {
		expect(zipChatCases.map((c) => c.name)).toEqual(committed.chat.map((v: { name: string }) => v.name));
		for (const [index, testCase] of zipChatCases.entries()) {
			expect(await chatRequest(testCase), testCase.name).toEqual(committed.chat[index].request);
		}
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('code-file, application, bulk and account requests match the committed vectors', async () => {
		for (const [index, testCase] of zipCodeFilesCases.entries()) {
			expect(onWire(await codeFilesRequest(testCase.files, committed.now)), testCase.name).toEqual(committed.codeFiles[index].request);
		}
		for (const [index, testCase] of zipApplicationCases.entries()) {
			const paths = testCase.paths.filter(Boolean);
			expect({ appName: testCase.appName || null, paths }, testCase.name).toEqual(committed.application[index].request);
		}
		for (const [index, testCase] of accountCases.entries()) {
			const bundle = testCase.bundle as unknown as Parameters<typeof buildAccountExportRequest>[0];
			expect(onWire(buildAccountExportRequest(bundle, EXPORTED_AT)), testCase.name).toEqual(committed.account[index].request);
		}
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('keeps the odd inputs the Rust port must reproduce in the golden', () => {
		const markdown = (name: string) => committed.chat.find((v: { name: string }) => v.name === name).out.entries.find((e: { path: string }) => e.path.endsWith('.md'));
		expect(markdown('invalid-chat-created-at-empties-markdown')).toMatchObject({ text: '' });
		expect(committed.chat.find((v: { name: string }) => v.name === 'every-file-group').out.entries.map((e: { path: string }) => e.path)).toContain('uploads/audio/trailing._transcript.txt');
		expect(committed.account.filter((v: { out: { kind: string } }) => v.out.kind === 'error').length).toBeGreaterThanOrEqual(5);
		expect(committed.application.find((v: { name: string }) => v.name === 'symbols-only-name').out.zipName).toBe('application.zip');
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
