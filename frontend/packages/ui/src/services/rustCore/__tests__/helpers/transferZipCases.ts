// Fixtures of the ZIP export parity vectors (transferZipVectors.test.ts). Odd inputs
// are deliberate: they are the behaviour the Rust port must reproduce byte for byte.
import type { ChatZipFiles } from '../../../zipExportService';

export interface ZipChatCase {
	name: string;
	filename: string;
	completenessJson: string | null;
	chat: Record<string, unknown>;
	messages: Array<Record<string, unknown>>;
	pii?: { piiHidden: boolean; piiMappings: Array<{ placeholder: string; original: string }> };
	files: Partial<Record<keyof ChatZipFiles, unknown[]>>;
}

const blob = (label: string) => new Blob([label]);
const msg = (role: string, created_at: unknown, content: unknown) => ({ message_id: `m-${String(created_at)}-${role}`, chat_id: 'c1', role, created_at, content });

export const zipChatCases: ZipChatCase[] = [
	{
		name: 'basic-seconds', filename: '2026-11-06_12-00-00_Plan a trip.', completenessJson: '{\n  "status": "complete"\n}',
		chat: { chat_id: 'c1', title: 'Plan a trip', created_at: 1_793_000_000 },
		messages: [msg('user', 1_793_000_001, 'Where to?'), msg('assistant', 1_793_000_002, 'Lisbon.\n\nSee [embed:abc]')],
		files: {},
	},
	{
		name: 'milliseconds-and-pii-revealed', filename: '2026-11-06_12-00-00_Mail.', completenessJson: '{}',
		chat: { chat_id: 'c1', title: 'Mail [EMAIL_1]', created_at: 1_793_000_000_000 },
		messages: [msg('user', 1_793_000_001_000, 'Write to [EMAIL_1] and EMAIL_2'), msg('assistant', 1_793_000_002_000, 'Sure: EMAIL_1')],
		pii: { piiHidden: false, piiMappings: [{ placeholder: '[EMAIL_1]', original: 'a@example.com' }, { placeholder: 'EMAIL_2', original: 'b@example.com' }] },
		files: {},
	},
	{
		name: 'pii-hidden-keeps-placeholders', filename: 'x.', completenessJson: null,
		chat: { chat_id: 'c1', title: 'Hidden', created_at: 1_793_000_000 },
		messages: [msg('user', 1_793_000_001, 'Mail [EMAIL_1]')],
		pii: { piiHidden: true, piiMappings: [{ placeholder: '[EMAIL_1]', original: 'a@example.com' }] },
		files: {},
	},
	{
		name: 'code-embed-path-rules', filename: '2026-11-06_12-00-00_Code.', completenessJson: '{}',
		chat: { chat_id: 'c1', title: 'Code', created_at: 1_793_000_000 },
		messages: [msg('user', 1_793_000_001, 'code')],
		files: {
			code: [
				{ embed_id: 'e1', language: 'python', filename: 'main.py', content: 'code-1', file_path: 'src/app/main.py' },
				{ embed_id: 'e2', language: 'rust', filename: 'lib.rs', content: 'code-2' },
				{ embed_id: 'e3', language: 'JavaScript', content: 'code-3' },
				{ embed_id: 'e4', language: 'Dockerfile', content: 'code-4' },
				{ embed_id: 'e5', language: 'Weird-Lang', content: 'code-5', filename: '' },
				{ embed_id: 'e6', language: 'BASH', content: 'code-6' },
				{ embed_id: 'e7', language: 'c', content: 'code-7', file_path: '' },
			],
		},
	},
	{
		name: 'every-file-group', filename: '2026-11-06_12-00-00_Files v1.2.', completenessJson: '{}',
		chat: { chat_id: 'c1', title: 'Files v1.2', created_at: 1_793_000_000 },
		messages: [msg('user', 1_793_000_001, 'files')],
		files: {
			transcripts: [{ embed_id: 't1', filename: 'talk.txt', content: 'transcript-1' }, { embed_id: 't2', filename: 'talk_2.txt', content: 'transcript-2' }],
			images: [{ filename: 'img.png', blob: blob('img-1') }, { filename: 'img_2.jpg', blob: blob('img-2') }],
			generatedAudio: [{ filename: 'voice.mp3', blob: blob('gen-1') }],
			staticFiles: [{ filename: 'doc.pdf', blob: blob('static-1') }],
			audio: [
				{ filename: 'recording_01.webm', blob: blob('audio-1'), transcript: 'hello transcript' },
				{ filename: 'noext', blob: blob('audio-2'), transcript: 'second transcript' },
				{ filename: 'a.b.c', blob: blob('audio-3'), transcript: 'third transcript' },
				{ filename: 'trailing.', blob: blob('audio-4'), transcript: 'fourth transcript' },
			],
			pdfs: [
				{ folderName: 'report', pdfFilename: 'report.pdf', pages: [{ filename: 'page_1.png', blob: blob('pdf-1-1') }, { filename: 'page_2.png', blob: blob('pdf-1-2') }] },
				{ folderName: 'empty', pdfFilename: 'empty.pdf', pages: [] },
			],
		},
	},
	{
		name: 'audio-with-empty-transcript', filename: 'a.', completenessJson: null,
		chat: { chat_id: 'c1', title: 'Audio', created_at: 1_793_000_000 },
		messages: [],
		files: { audio: [{ filename: 'rec.webm', blob: blob('audio-only'), transcript: '' }] },
	},
	{
		name: 'untitled-and-odd-messages', filename: '2026-11-06_12-00-00_Untitled Chat.', completenessJson: '[]',
		chat: { chat_id: 'c1', created_at: 1_793_000_000 },
		messages: [
			msg('user', 1_793_000_001, { __markdown: 'from tiptap' }),
			msg('assistant', 1_793_000_002, undefined),
			msg('assistant', 1_793_000_003, { __throw: true }),
			msg('user', Number.NaN, 'invalid time'),
			msg('user', undefined, 'missing time'),
			msg('system', 1_793_000_004, ''),
			msg('user', 1e15, 'far future ms'),
			msg('user', 9e18, 'out of range'),
		],
		files: {},
	},
	{
		name: 'invalid-chat-created-at-empties-markdown', filename: 'bad.', completenessJson: '{}',
		chat: { chat_id: 'c1', title: 'Bad', created_at: Number.POSITIVE_INFINITY },
		messages: [msg('user', 1_793_000_001, 'kept out')],
		files: {},
	},
	{
		name: 'unicode-and-newlines', filename: '2026-11-06_12-00-00_Ünï.', completenessJson: '{"a":"ß"}',
		chat: { chat_id: 'c1', title: 'Ünïcödé 日本語 🎉', created_at: 1_793_000_000 },
		messages: [msg('user', 1_793_000_001, 'line1\nline2\r\n$x \\ "q"'), msg('assistant', 1_793_000_002, '🎉 ')],
		files: {},
	},
];

export interface ZipCodeFilesCase {
	name: string;
	files: Array<{ code: string; language: string; filename?: string }>;
}

export const zipCodeFilesCases: ZipCodeFilesCase[] = [
	{
		name: 'mixed-names-and-duplicates',
		files: [
			{ code: 'one', language: 'python', filename: 'src/app/main.py' },
			{ code: 'two', language: 'python', filename: 'other\\MAIN.py' },
			{ code: 'dockerfile:app/Dockerfile\nFROM x', language: 'dockerfile' },
			{ code: 'three', language: 'javascript' },
			{ code: 'four', language: 'javascript' },
			{ code: 'five', language: 'bash', filename: 'Makefile' },
			{ code: 'six', language: 'bash', filename: 'makefile' },
			{ code: 'seven', language: 'text', filename: '.env' },
			{ code: 'eight', language: 'text', filename: '.env' },
		],
	},
	{ name: 'two-snippets', files: [{ code: 'a', language: 'Kotlin' }, { code: 'b', language: 'unknownlang' }] },
	{ name: 'single-file', files: [{ code: 'solo', language: 'typescript', filename: 'deep/path/solo.ts' }] },
	{ name: 'single-snippet', files: [{ code: 'solo', language: 'sql' }] },
];

export interface ZipApplicationCase {
	name: string;
	appName: string;
	paths: string[];
}

export const zipApplicationCases: ZipApplicationCase[] = [
	{ name: 'plain', appName: 'My App', paths: ['src/main.py', 'README.md'] },
	{ name: 'traversal-and-separators', appName: '  Ünï Çode!!App_v1.2  ', paths: ['../etc/passwd', 'a\\b\\c.txt', ' ./x / y ', '///', '', '..', 'dir//file'] },
	{ name: 'empty-name', appName: '', paths: ['a.txt'] },
	{ name: 'symbols-only-name', appName: '***', paths: ['a.txt'] },
];

export interface AccountCase {
	name: string;
	bundle: {
		export: Record<string, unknown>;
		manifest: Record<string, unknown>;
		chunks: Array<Record<string, unknown>>;
	};
}

const manifest = (extra: Record<string, unknown> = {}) => ({
	schema_version: 'account-export-v1', selected_domains: ['chats', 'usage'], filters: {},
	report: { status: 'complete', failures: [], redactions: ['x'], partial_requires_acceptance: false }, ...extra,
});

export const accountCases: AccountCase[] = [
	{
		name: 'typical-multi-domain',
		bundle: {
			export: { export_id: 'exp-1', status: 'complete' },
			manifest: manifest(),
			chunks: [
				{ chunk_id: 'c1', domain: 'chats', sequence: 1, status: 'ready', payload: { items: [
					{ id: 'chat-1', title: 'First: chat', summary: '  A summary  ', messages: [{ role: 'user', content: 'Hello' }, { sender: 'bot', text: 'Hi\nthere' }, 'skipped', null, ['x']] },
					{ chat_id: 'chat/2', name: 'Named', messages: [] },
					{ title: 'No id', messages: 'not an array' },
					'not a chat',
				] } },
				{ chunk_id: 'c2', domain: 'chats', sequence: 2, status: 'ready', payload: { items: [{ id: ' weird id! ', messages: [{ content: 7 }] }] } },
				{ chunk_id: 'u1', domain: 'usage', sequence: 1, status: 'ready', payload: { rows: [1, 2.5, 1e21, -0, null, true, 'a: b'] } },
				{ chunk_id: 'p1', domain: 'profile_account_settings', sequence: 1, status: 'ready', payload: 'plain string' },
				{ chunk_id: 'p2', domain: 'referenced_uploads', sequence: 1, status: 'ready', payload: null },
				{ chunk_id: 'n1', domain: 'Ünï/dom ain', sequence: 3, status: 'ready', payload: 0 },
				{ chunk_id: 'n2', domain: '5', sequence: 4, status: 'ready', payload: { '2': 'b', '1': 'a', z: 'z', chunk_id: 'override' } },
				{ chunk_id: 'n3', domain: null, sequence: 5, status: 'ready', payload: [1, 2] },
			],
		},
	},
	{
		name: 'yaml-quirks-in-manifest',
		bundle: {
			export: { export_id: 7, status: undefined },
			manifest: manifest({
				schema_version: 3, selected_domains: ['a', 1, null, ['x', 'y'], { k: 'v' }],
				text: 'multi\nline: text', empty: '', flag: 'true', braces: '{a}', hash: 'a#b', brackets: '[a]', quote: 'say "hi" \\ now',
				nested: { list: [{ a: 1, b: { c: [1, [2, 3], 'q: r', ''] } }, 'x'], none: null, 'k:ey': false },
				numbers: { big: 12345678901234567000, small: 1.5e-9, neg: -3, '10': 'ten', '2': 'two' },
				report: { status: 'partial', failures: [{ domain: 'chats', reason: 'x' }], redactions: ['whatever'], partial_requires_acceptance: 1 },
			}),
			chunks: [],
		},
	},
	{
		name: 'report-defaults',
		bundle: { export: { export_id: null, status: null }, manifest: { selected_domains: 'not-array', report: ['array'] }, chunks: [{}, { domain: 'chats', payload: { items: 'no' } }] },
	},
	{ name: 'secret-field-in-manifest', bundle: { export: { export_id: 'e', status: 'complete' }, manifest: manifest({ nested: [{ API_KEY: 'x' }] }), chunks: [] } },
	{ name: 'secret-value-in-manifest', bundle: { export: { export_id: 'e', status: 'complete' }, manifest: manifest({ note: 'use sk-proj-abcdef123 now' }), chunks: [] } },
	{
		name: 'secret-field-in-chat-text',
		bundle: { export: { export_id: 'e', status: 'complete' }, manifest: manifest(), chunks: [{ chunk_id: 'c', domain: 'chats', sequence: 1, status: 'ready', payload: { items: [{ id: 'x', messages: [{ role: 'user', content: 'my password_hash : abc' }] }] } }] },
	},
	{
		name: 'secret-patterns-edge',
		bundle: {
			export: { export_id: 'e', status: 'complete' }, manifest: manifest(),
			chunks: [
				{ chunk_id: 'a', domain: 'safe', sequence: 1, status: 'ready', payload: { a: 'task-api-secretvalue', b: 'sk-api-short', c: 'x#key=short', d: 'no_api_key_here', e: 'myapi_key: ', f: '-----BEGIN PUBLIC KEY-----', g: 'masterkey:' } },
			],
		},
	},
	{
		name: 'private-key-block-in-chunk',
		bundle: { export: { export_id: 'e', status: 'complete' }, manifest: manifest(), chunks: [{ chunk_id: 'a', domain: 'x', sequence: 1, status: 'ready', payload: { pem: '-----BEGIN RSA PRIVATE KEY-----\nabc' } }] },
	},
	{
		name: 'share-fragment-and-quoted-field',
		bundle: { export: { export_id: 'e', status: 'complete' }, manifest: manifest(), chunks: [{ chunk_id: 'a', domain: 'x', sequence: 1, status: 'ready', payload: { link: 'https://x/#key=ABCDEFGH12' } }] },
	},
	{
		name: 'quoted-field-spacing',
		bundle: { export: { export_id: 'e', status: 'complete' }, manifest: manifest(), chunks: [{ chunk_id: 'a', domain: 'x', sequence: 1, status: 'ready', payload: { text: "see 'Token_Hash'  : value" } }] },
	},
];
