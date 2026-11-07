// `transfer` unit of the shared Rust core Worker: the real router and installer
// over a scripted binding (the Rust parsing itself is proven by
// web_transfer_tests.rs over the TS-generated vectors), and the flag-on page
// adapter (rustChatImport.ts) following the unit's answers with no TS fallback.
import JSZip from 'jszip';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { createSharedCoreClient, registerSharedRustCore, type SharedWorkerEndpoint } from '../host/sharedCoreRegistry';
import { createSharedWorkerRouter } from '../host/sharedWorkerProtocol';
import { installTransferUnit } from '../transfer/transferUnit';
import { rustTransferStats } from '../transfer/transferUnitClient';
import { rustBuildMessageBatches, rustEstimateImportCost, rustParseImportFile } from '../transfer/rustChatImport';
import { rustConvertChatToYaml, rustGenerateChatFilename, type ChatExportPageIO } from '../transfer/rustChatExport';
import { exportJsonReplacer, wellFormed } from '../transfer/transferUnit';
import type { TransferBinding } from '../transfer/transferProtocol';
import type { ParsedImportChat } from '../../chatImportService';
import type { Chat, Message } from '../../../types/chat';

const calls: string[] = [];
const chat = (fingerprint: string, count: number) => ({
	provider: 'claude', source_chat_id: fingerprint, source_fingerprint: fingerprint, messages: Array.from({ length: count }, (_, i) => ({ role: 'user', content: `m${i}`, provider_metadata: {} })),
	embeds: [], uploads: [], provider_labels: ['claude'], source_metadata: {},
}) as unknown as ParsedImportChat;

const binding: TransferBinding = {
	transfer_import_route: (input) => {
		const name = JSON.parse(input).fileName as string;
		return JSON.stringify(name.endsWith('.json') ? { kind: 'json' } : name.endsWith('.zip') ? { kind: 'zip' } : { kind: 'error', message: 'Unsupported import file.' });
	},
	transfer_parse_json_import: (input, text) => {
		const meta = JSON.parse(input);
		calls.push(`parseJson ${meta.container} ${meta.selectedSource} ${text.length}`);
		if (text.startsWith('{"a"')) return JSON.stringify({ kind: 'syntax' });
		if (text === '{}') return JSON.stringify({ kind: 'error', message: 'Claude export conversations must be an array.' });
		return JSON.stringify({ kind: 'ok', parsed: { source: 'claude', parserFormat: 'claude', fileType: `claude-${meta.container}`, chats: [chat('fp-a', 1), chat('fp-b', 3)], skippedDomains: [] }, estimates: [[2, 1], [9, 3]] });
	},
	transfer_zip_plan: (input) => {
		const names = (JSON.parse(input).entries as Array<{ name: string }>).map((e) => e.name);
		calls.push(`zipPlan ${names.join(',')}`);
		return JSON.stringify(names.includes('manifest.yml')
			? { kind: 'openmates', embeds: ['embeds/e.yml'], uploads: [], chats: ['chats/a.yml'] }
			: { kind: 'conversations', name: 'x/conversations.json' });
	},
	transfer_openmates_manifest: (input) => (calls.push(`manifest ${JSON.parse(input).manifest.format}`), JSON.stringify({ kind: 'ok' })),
	transfer_parse_openmates_archive: (input) => {
		const p = JSON.parse(input);
		calls.push(`archive ${p.chats[0].name} ${p.chats[0].value.id} ${p.embeds[0].id}`);
		return JSON.stringify({ kind: 'ok', parsed: { source: 'openmates', parserFormat: 'openmates', fileType: 'openmates-zip', chats: [chat('fp-o', 2)], skippedDomains: [] }, estimates: [[4, 2]] });
	},
	transfer_batch_plan: (input) => {
		const p = JSON.parse(input);
		if (p.maxMessages <= 0) return JSON.stringify({ kind: 'error', message: 'Import message batch size must be positive.' });
		return JSON.stringify({ kind: 'ok', batches: [[0, 0, 0, 1, 'scan-fp-a-0'], [1, 0, 0, 2, 'scan-fp-b-0'], [1, 1, 2, 3, 'scan-fp-b-1']] });
	},
	transfer_export_filename: (input) => {
		calls.push(`exportFilename ${input}`);
		return JSON.stringify(typeof JSON.parse(input).createdAt !== 'number'
			? { kind: 'error', message: 'Invalid time value' }
			: { kind: 'ok', filename: '2026-07-22_06-00-00_Title.yaml' });
	},
	transfer_export_draft_kind: (input) => (calls.push(`draftKind ${input}`), JSON.stringify({ kind: 'ok', cleartext: JSON.parse(input).draft.startsWith('plain') })),
	transfer_export_yaml: (input) => (calls.push(`exportYaml ${input}`), JSON.stringify({ kind: 'ok', yaml: 'chat:\n  title: T' })),
};

function fakeWorker() {
	const listeners: Record<string, ((event: Event) => void)[]> = { message: [], error: [], messageerror: [] };
	const router = createSharedWorkerRouter({
		installers: { transfer: installTransferUnit },
		loadBinding: async () => binding,
		reply: (reply) => queueMicrotask(() => { for (const l of listeners.message) l({ data: reply } as MessageEvent); }),
	});
	const endpoint: SharedWorkerEndpoint = {
		postMessage(message, transfer) { void router.handle(message, transfer as MessagePort[]); },
		addEventListener(type, listener) { listeners[type].push(listener); },
		terminate() {},
	};
	return endpoint;
}

let unregister: (() => void) | null = null;
beforeEach(() => {
	calls.length = 0;
	unregister = registerSharedRustCore(createSharedCoreClient(fakeWorker));
});
afterEach(() => unregister?.());

describe('shared transfer unit', () => {
	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('refuses a binding without the transfer exports', () => {
		const channel = new MessageChannel();
		expect(() => installTransferUnit({ binding: {}, ports: [channel.port2], generation: null, principal: null, signal: new AbortController().signal }))
			.toThrow('unavailable');
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('parses a JSON export in Rust and estimates selected chats from the Rust per-chat inputs', async () => {
		const before = rustTransferStats.calls;
		const parsed = await rustParseImportFile(new File(['[1]'], 'conversations.json'), 'chatgpt', undefined);
		expect(parsed.fileType).toBe('claude-json');
		expect(calls).toEqual(['parseJson json chatgpt 3']);
		expect(rustTransferStats.calls - before).toBe(2);
		expect(rustEstimateImportCost(parsed.chats)).toEqual({ totalInputTokens: 11, estimatedCredits: 2, chatCount: 2, messageCount: 4 });
		expect(rustEstimateImportCost([{ ...parsed.chats[1] }])).toEqual({ totalInputTokens: 9, estimatedCredits: 1, chatCount: 1, messageCount: 3 });
		expect(() => rustEstimateImportCost([chat('never-parsed', 1)])).toThrow('rust_transfer_unparsed_chat');
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('surfaces Rust errors verbatim and rethrows the browser JSON syntax error', async () => {
		await expect(rustParseImportFile(new File(['{}'], 'c.json'), undefined, undefined)).rejects.toThrow('Claude export conversations must be an array.');
		let syntax: unknown;
		try { JSON.parse('{"a": '); } catch (error) { syntax = error; }
		await expect(rustParseImportFile(new File(['{"a": '], 'c.json'), undefined, undefined)).rejects.toThrow((syntax as Error).message);
		await expect(rustParseImportFile(new File(['x'], 'notes.txt'), undefined, undefined)).rejects.toThrow('Unsupported import file.');
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('reads the ZIP entries Rust plans and passes page-parsed YAML for OpenMates archives', async () => {
		const zip = new JSZip();
		zip.file('manifest.yml', 'format: openmates-account-export\nversion: 1\n');
		zip.file('chats/a.yml', 'id: chat-a\n');
		zip.file('embeds/e.yml', 'id: e1\n');
		const parsed = await rustParseImportFile(new File([await zip.generateAsync({ type: 'arraybuffer' })], 'export.zip'), undefined, undefined);
		expect(parsed.chats.map((c) => c.source_fingerprint)).toEqual(['fp-o']);
		expect(calls.slice(1)).toEqual(['manifest openmates-account-export', 'archive chats/a.yml chat-a e1']);

		const nested = new JSZip();
		nested.file('x/conversations.json', '[1, 2]');
		await rustParseImportFile(new File([await nested.generateAsync({ type: 'arraybuffer' })], 'gpt.zip'), undefined, undefined);
		expect(calls[calls.length - 1]).toBe('parseJson zip null 6');
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('slices scan batches at the Rust boundaries and refuses invalid sizes', async () => {
		const chats = [chat('fp-a', 1), chat('fp-b', 3)];
		const batches = await rustBuildMessageBatches(chats, 2);
		expect(batches.map((b) => [b.chatIndex, b.chunkIndex, b.batchId, b.chat.messages.map((m) => m.content)])).toEqual([
			[0, 0, 'scan-fp-a-0', ['m0']], [1, 0, 'scan-fp-b-0', ['m0', 'm1']], [1, 1, 'scan-fp-b-1', ['m2']],
		]);
		await expect(rustBuildMessageBatches(chats, 0)).rejects.toThrow('Import message batch size must be positive.');
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('builds export filenames in Rust and throws the RangeError for an invalid creation time', async () => {
		await expect(rustGenerateChatFilename(1784700000, 'Title', undefined, 'yaml')).resolves.toBe('2026-07-22_06-00-00_Title.yaml');
		expect(calls[calls.length - 1]).toBe('exportFilename {"createdAt":1784700000,"titleDecrypted":"Title","titlePlain":null,"extension":"yaml"}');
		await expect(rustGenerateChatFilename(Number.NaN, 'Title', undefined, 'yaml')).rejects.toThrow(new RangeError('Invalid time value'));
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('sends page-resolved chat values to Rust and returns its YAML unchanged', async () => {
		const io: ChatExportPageIO = {
			decryptedMetadata: async () => ({ title: 'Decrypted', summary: 'Sum' }),
			decryptDraft: async () => 'decrypted draft',
			thinkingText: async (message) => (message.message_id === 'a1' ? 'thought' : undefined),
			messageMarkdown: async (message) => `md:${message.content as string}`,
			collectEmbeds: async () => [{ kind: 'ok', embed_id: 'e1', type: 'code', status: undefined, content: { n: Number.NaN, list: [1, undefined] }, createdAt: 5, updatedAt: undefined, text_preview: undefined }],
			chatLink: (id) => `https://app.test/#chat-id=${id}`,
		};
		const chat = { chat_id: 'c1', created_at: 1, title: 'Plain', encrypted_draft_md: 'v1:cipher' } as Chat;
		const messages = [
			{ message_id: 'u1', role: 'user', content: 'hi', created_at: 10 },
			{ message_id: 'a1', role: 'assistant', content: 'yo', created_at: 11, has_thinking: true, thinking_token_count: 4 },
		] as unknown as Message[];
		const yaml = await rustConvertChatToYaml({
			chat, messages, includeLink: true, hydration: undefined,
			piiOptions: { piiHidden: false, piiMappings: [{ placeholder: '[E]', original: 'e@x.y', type: 'EMAIL' }] },
		}, io);
		expect(yaml).toBe('chat:\n  title: T');
		expect(calls.some((call) => call.startsWith('draftKind {"draft":"v1:cipher"}'))).toBe(true);
		const sent = JSON.parse((calls[calls.length - 1] as string).replace('exportYaml ', ''));
		expect(sent).toMatchObject({
			link: 'https://app.test/#chat-id=c1', draft: 'decrypted draft', completeness: null,
			titles: { decrypted: 'Decrypted', plain: 'Plain' }, summaries: { decrypted: 'Sum', plain: null },
			pii: { hidden: false, mappings: [{ placeholder: '[E]', original: 'e@x.y' }] },
		});
		expect(sent.messages.map((m: { thinking: string | null; hasThinking: boolean; content: string }) => [m.content, m.thinking, m.hasThinking]))
			.toEqual([['md:hi', null, false], ['md:yo', 'thought', true]]);
		expect(sent.embeds[0]).toMatchObject({ status: null, content: { n: { $om_raw: 'NaN' }, list: [1, { $om_raw: 'undefined' }] }, createdAt: 5, updatedAt: null });
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('serializes export payloads with well-formed strings and raw non-finite markers', () => {
		expect(wellFormed('a\ud83db\ude00c\ud83d\ude00')).toBe('a\ufffdb\ufffdc\ud83d\ude00');
		expect(JSON.stringify({ a: undefined, b: [undefined, Number.POSITIVE_INFINITY], c: 'x\ud83d' }, exportJsonReplacer))
			.toBe('{"a":null,"b":[{"$om_raw":"undefined"},{"$om_raw":"Infinity"}],"c":"x\ufffd"}');
	});
});
