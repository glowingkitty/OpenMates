/**
 * Inputs for the chat export parity vectors (transferExportVectors.test.ts).
 * Each case is run through the TypeScript exporter (the oracle) and through the
 * page adapter that builds the Rust request; Rust replays the request and must
 * return the same bytes. Cases deliberately include odd inputs: YAML quoting
 * edges, block scalars, invalid and extreme timestamps, non-finite numbers,
 * lone surrogates, regex-special PII placeholders and nested embeds.
 */
import type { Chat, Message, PIIMapping } from '../../../../types/chat';
import type { ChatExportHydrationResult, PIIExportOptions } from '../../../chatExportService';

export interface EmbedFixture {
	type: string;
	status?: string;
	/** Key into `decoded`; omitted content exercises the missing-content error. */
	content?: string;
	decoded?: unknown;
	/** `decodeToonContent` rejects, exercising the decode error record. */
	decodeFails?: boolean;
	createdAt?: number;
	updatedAt?: number;
	text_preview?: string;
	embed_ids?: string[];
}

export interface YamlCase {
	name: string;
	chat: Partial<Chat>;
	messages: Array<Partial<Message> & Record<string, unknown>>;
	includeLink?: boolean;
	pii?: PIIExportOptions;
	hydration?: ChatExportHydrationResult;
	metadata?: { title?: string; summary?: string } | null;
	chatKey?: boolean;
	embeds?: Record<string, EmbedFixture>;
}

const chat = (overrides: Partial<Chat> = {}): Partial<Chat> => ({ chat_id: 'chat-1', created_at: 1784700000, ...overrides });
const user = (content: unknown, created_at = 1784700001, extra: Record<string, unknown> = {}) =>
	({ message_id: `m-${created_at}`, chat_id: 'chat-1', role: 'user', content, created_at, ...extra }) as Partial<Message> & Record<string, unknown>;
const assistant = (content: unknown, created_at = 1784700002, extra: Record<string, unknown> = {}) =>
	({ message_id: `m-${created_at}`, chat_id: 'chat-1', role: 'assistant', content, created_at, ...extra }) as Partial<Message> & Record<string, unknown>;
const mapping = (placeholder: string, original: string): PIIMapping => ({ placeholder, original, type: 'TEST' });

export const quotingStrings = [
	'plain text', 'yes', 'No', 'on', 'off', 'null', 'true', 'false', '123', '0', '007', '+5', '-5', '.5', '0.5', '1.50', '1e3', '1e+21',
	'100000000000000000000', '1e21', '1e999', '0x1F', '12 ', '12\u000b', '3 apples', 'a: b', 'a #b', 'say "hi"', "it's", 'tab\there',
	'carriage\rreturn', 'back\\slash', 'http://x.example/a?b=c', '&amp;', 'a,b', '{x}', '[x]', '100%', '@mention', 'a|b', 'a>b', '`code`',
	'', ' ', ' leading', 'trailing ', '\u0001ctl', '\u007fdel', 'café \u{1F600}', 'lone\ud83dsurrogate', ' nbsp',
];

export const yamlCases: YamlCase[] = [
	{
		name: 'basic-chat-decrypted-metadata',
		chat: chat({ title: 'ignored plain title' }),
		metadata: { title: 'Trip: Rome & "Paris"', summary: 'Planning a trip' },
		messages: [user('Hello there'), assistant('Hi! How can I help?')],
	},
	{
		name: 'demo-chat-plain-title-link-ms-timestamps',
		chat: chat({ chat_id: 'demo-intro', created_at: 1784700000123, title: 'Welcome', chat_summary: 'Intro to OpenMates' }),
		metadata: null,
		includeLink: true,
		messages: [user('Hello', 1784700000500), assistant('Welcome!', 1784700001500)],
	},
	{
		name: 'no-title-no-summary-empty-chat',
		chat: chat(),
		metadata: {},
		messages: [],
	},
	{
		name: 'empty-string-title-falls-back-to-plain',
		chat: chat({ title: 'plain fallback', chat_summary: 'plain summary' }),
		metadata: { title: '', summary: '' },
		messages: [user('x')],
	},
	{
		name: 'multiline-block-scalars',
		chat: chat({ title: 'Block' }),
		metadata: null,
		messages: [
			user('line one\nline two with \\ backslash and $dollar\n\n  indented\ntrailing newline\n'),
			assistant('```python\nprint("hi")\n```\n\n$HOME \\n literal'),
			user('\n'),
			user('a\r\nb\r\n'),
		],
	},
	{
		name: 'single-line-quoting-edges',
		chat: chat({ title: 'Quoting' }),
		metadata: null,
		messages: quotingStrings.map((text, index) => user(text, 1784700100 + index)),
	},
	{
		name: 'assistant-fields-thinking-category',
		chat: chat({ title: 'Thinking' }),
		metadata: null,
		chatKey: true,
		messages: [
			assistant('plain', 1784700010, { category: 'coding', assistant_category: 'ignored' }),
			assistant('fallback category', 1784700011, { assistant_category: 'research' }),
			assistant('decrypted thinking', 1784700012, { thinking_content: 'Let me think: step 1\nstep 2', has_thinking: true, thinking_token_count: 42 }),
			assistant('encrypted thinking', 1784700013, { encrypted_thinking_content: 'cipher-a', has_thinking: true }),
			assistant('undecryptable thinking', 1784700014, { encrypted_thinking_content: 'bad-cipher', has_thinking: true, thinking_token_count: 0 }),
			assistant('throwing thinking', 1784700015, { encrypted_thinking_content: 'throw-cipher' }),
			assistant('tokens only', 1784700016, { thinking_token_count: 7 }),
			user('user ignores assistant fields', 1784700017, { category: 'x', thinking_content: 'no', has_thinking: true, thinking_token_count: 3 }),
			{ message_id: 'm-sys', chat_id: 'chat-1', role: 'system', content: 'system text', created_at: 1784700018 } as Partial<Message>,
		],
	},
	{
		name: 'assistant-thinking-without-chat-key',
		chat: chat({ title: 'No key' }),
		metadata: null,
		chatKey: false,
		messages: [assistant('x', 1784700020, { encrypted_thinking_content: 'cipher-b', has_thinking: true })],
	},
	{
		name: 'tiptap-and-odd-content',
		chat: chat({ title: 'TipTap' }),
		metadata: null,
		messages: [
			user({ type: 'doc', content: [{ type: 'paragraph' }], __markdown: 'From **tiptap**\nsecond line' }, 1784700030),
			user({ type: 'doc', content: [{ type: 'paragraph' }], __markdown: '' }, 1784700031),
			user({ type: 'doc' }, 1784700032),
			user(null, 1784700033),
			user(undefined, 1784700034),
			user(12, 1784700035),
		],
	},
	{
		name: 'pii-revealed-originals',
		chat: chat({ title: 'PII' }),
		metadata: null,
		pii: {
			piiHidden: false,
			piiMappings: [mapping('[EMAIL_1_com]', 'user@example.com'), mapping('[PHONE_1]', '+49 170 1234567')],
		},
		messages: [
			user('Mail [EMAIL_1_com] or call [PHONE_1]; again [EMAIL_1_com].'),
			assistant('Bare EMAIL_1_com, (EMAIL_1_com), xEMAIL_1_com, EMAIL_1_comx, [EMAIL_1_com] PHONE_1\nPHONE_1.'),
		],
	},
	{
		name: 'pii-hidden-and-empty-mappings',
		chat: chat({ title: 'PII hidden' }),
		metadata: null,
		pii: { piiHidden: true, piiMappings: [mapping('[EMAIL_1_com]', 'user@example.com')] },
		messages: [user('Mail [EMAIL_1_com] bare EMAIL_1_com')],
	},
	{
		name: 'pii-no-mappings-revealed',
		chat: chat({ title: 'PII none' }),
		metadata: null,
		pii: { piiHidden: false, piiMappings: [] },
		messages: [user('Mail [EMAIL_1_com]')],
	},
	{
		name: 'pii-odd-placeholders',
		chat: chat({ title: 'PII odd' }),
		metadata: null,
		pii: {
			piiHidden: false,
			piiMappings: [
				mapping('[A.B*C]', 'regex-special'),
				mapping('', '_'),
				mapping('[]', 'empty-bare'),
				mapping('[X]', '[Y] and Y'),
				mapping('[Y]', 'why'),
				mapping('$&', 'dollar-amp'),
			],
		},
		messages: [user('abc [A.B*C] A.B*C A-B-C [X] X [Y] Y $& \u{1F600}z')],
	},
	{
		name: 'pii-astral-originals',
		chat: chat({ title: 'PII astral' }),
		metadata: null,
		pii: { piiHidden: false, piiMappings: [mapping('[E_1]', 'm\u{1F600}'), mapping('', '|')] },
		messages: [user('\u{1F600}[E_1}E_1 ab\u{1F600}')],
	},
	{
		name: 'draft-cleartext',
		chat: chat({ title: 'Draft', encrypted_draft_md: 'Typed but **unsent**' }),
		metadata: null,
		messages: [user('x')],
	},
	{
		name: 'draft-encrypted-and-failures',
		chat: chat({ title: 'Draft enc', encrypted_draft_md: 'v1:ciphertext-draft' }),
		metadata: null,
		messages: [user('x')],
	},
	{
		name: 'draft-encrypted-decrypts-to-null',
		chat: chat({ title: 'Draft null', encrypted_draft_md: 'encrypted:bad-draft' }),
		metadata: null,
		messages: [user('x')],
	},
	{
		name: 'draft-decrypt-throws',
		chat: chat({ title: 'Draft throws', encrypted_draft_md: 'v1:throw-draft' }),
		metadata: null,
		messages: [user('x')],
	},
	{
		name: 'draft-long-cleartext-treated-as-ciphertext',
		chat: chat({ title: 'Draft long', encrypted_draft_md: `${'long draft '.repeat(100)}` }),
		metadata: null,
		messages: [user('x')],
	},
	{
		name: 'hydration-partial-and-checkpoints',
		chat: chat({ title: 'Partial' }),
		metadata: null,
		hydration: {
			messages: [],
			checkpoints: [
				{ id: 'cp-1', chat_id: 'chat-1', user_id: 'u', created_at: 1784700500, compressed_up_to_timestamp: 1784700400, compressed_message_count: 80, summary: 'Older: history\nsecond line', summary_token_estimate: 42, status: 'active' },
				{ id: 'cp-2', chat_id: 'chat-1', user_id: 'u', created_at: Number.NaN, compressed_up_to_timestamp: 1e20, compressed_message_count: 0, status: 'active' },
				{ id: 'cp-3', chat_id: 'chat-1', user_id: 'u', created_at: 0, compressed_up_to_timestamp: -5, compressed_message_count: 3, summary: '', summary_token_estimate: 0, status: 'active' },
			] as unknown as ChatExportHydrationResult['checkpoints'],
			completeness: {
				status: 'partial', requested_message_count: 101, hydrated_message_count: 100, checkpoint_count: 3,
				warnings: ['Only 100 of 101 durable messages were available locally.', 'Could not hydrate: "quoted" warning'],
			},
		},
		messages: [user('a'), assistant('b')],
	},
	{
		name: 'timestamps-invalid-and-extreme',
		chat: chat({ title: 'Times' }),
		metadata: null,
		messages: [
			user('nan', Number.NaN),
			user('undefined timestamp', undefined as unknown as number),
			user('zero', 0),
			user('negative seconds', -86400),
			user('fraction', 1784700000.987654),
			user('boundary ms', 999999999999),
			user('boundary above', 1e12),
			user('max date', 8.64e15),
			user('over max date', 8.64e15 + 1),
			user('infinite', Number.POSITIVE_INFINITY),
			user('year 10000', 253402300800000),
			user('year -1', -62198755200000),
		],
	},
	{
		name: 'unicode-and-lone-surrogates',
		chat: chat({ title: 'Unicode \u{1F600}' }),
		metadata: { title: 'Türkiye \u{1F1E9}\u{1F1EA}', summary: 'café ‮ rtl' },
		messages: [user('emoji \u{1F600}\u{1F468}‍\u{1F469}‍\u{1F467}'), user('lone high \ud83d end'), user('lone low \ude00 end'), user('😀 pair ok')],
	},
	{
		name: 'embeds-nested-and-numbers',
		chat: chat({ title: 'Embeds' }),
		metadata: null,
		messages: [
			user('see [embed:parent-1] and [embed:plain-2] and [embed:bad-3] and [embed:nocontent-4] again [embed:plain-2]'),
			assistant('also [embed:pipe-5]'),
		],
		embeds: {
			'parent-1': {
				type: 'app_skill_use', status: 'finished', content: 'c-parent', createdAt: 1784700100, updatedAt: 1784700200.5,
				text_preview: 'Preview: text', embed_ids: ['child-a', 'child-b', 'plain-2'],
				decoded: { app_id: 'web', skill: 'search', embed_ids: ['child-a', 'child-c'], results: [1, 2.5, -0, 0.1, 1e21, 1e-7, 123456789012345680000, 2 ** 60, 5e-324] },
			},
			'child-a': { type: 'website', status: 'finished', content: 'c-a', createdAt: 0, decoded: { url: 'https://example.org/a?b=c', title: 'A: B', items: [{ k: 'v', n: null }, 'x y', true, null, ['nested', ['deep']], {}, []] } },
			'child-b': { type: 'website', status: 'finished', content: 'c-b', decoded: 'plain decoded string\nwith lines' },
			'child-c': { type: 'website', content: 'c-c', createdAt: 1784700001, updatedAt: 1784700002, decoded: { '2': 'two', b: 'bee', '1': 'one', nested: { flag: false, count: 3, empty: '' } } },
			'plain-2': { type: 'code', status: 'finished', content: 'c-plain', createdAt: 1e12, updatedAt: Number.NaN, decoded: { code: 'x = 1\ny = "2"', lang: 'python' } },
			'bad-3': { type: 'broken', status: 'finished', content: 'c-bad', decodeFails: true },
			'nocontent-4': { type: 'empty', status: 'finished' },
			'pipe-5': { type: 'composite', status: 'finished', content: 'c-pipe', decoded: { embed_ids: 'child-b| |child-c|', mixed: [Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY, undefined, 'after'], missing: undefined, nan: Number.NaN, inf: Number.POSITIVE_INFINITY } },
		},
	},
	{
		name: 'embed-content-null-and-scalar-roots',
		chat: chat({ title: 'Embeds scalar' }),
		metadata: null,
		messages: [user('[embed:null-1] [embed:num-2] [embed:str-3] [embed:arr-4]')],
		embeds: {
			'null-1': { type: 'x', status: 'finished', content: 'c-null', decoded: null },
			'num-2': { type: 'x', status: 'finished', content: 'c-num', decoded: 42 },
			'str-3': { type: 'x', status: 'finished', content: 'c-str', decoded: '007' },
			'arr-4': { type: 'x', status: 'finished', content: 'c-arr', decoded: ['a', 1, [2, 3], { z: [] }] },
		},
	},
];

export const filenameCases = [
	{ name: 'seconds', createdAt: 1784700000, metadataTitle: 'Trip to Rome', plainTitle: undefined, extension: 'yaml' },
	{ name: 'milliseconds', createdAt: 1784700000123, metadataTitle: undefined, plainTitle: 'Demo: chat/with*odd?chars', extension: 'yaml' },
	{ name: 'untitled', createdAt: 1784700000, metadataTitle: undefined, plainTitle: undefined, extension: 'yaml' },
	{ name: 'empty-titles-untitled', createdAt: 1784700000, metadataTitle: '', plainTitle: '', extension: 'md' },
	{ name: 'invalid-chars-removed', createdAt: 1784700000, metadataTitle: '<>:"/\\|?*', extension: 'yaml' },
	{ name: 'sanitized-to-empty', createdAt: 1784700000, metadataTitle: '???', plainTitle: 'fallback not used', extension: 'yaml' },
	{ name: 'trim-whitespace', createdAt: 1784700000, metadataTitle: '   padded  ', extension: 'yaml' },
	{ name: 'length-50', createdAt: 1784700000, metadataTitle: 'x'.repeat(80), extension: 'yaml' },
	{ name: 'length-50-trailing-space', createdAt: 1784700000, metadataTitle: `${'y'.repeat(49)} ${'z'.repeat(20)}`, extension: 'yaml' },
	{ name: 'emoji-split-at-50', createdAt: 1784700000, metadataTitle: `${'a'.repeat(49)}\u{1F600}tail`, extension: 'yaml' },
	{ name: 'emoji-whole-at-50', createdAt: 1784700000, metadataTitle: `${'a'.repeat(48)}\u{1F600}tail`, extension: 'yaml' },
	{ name: 'epoch-zero', createdAt: 0, metadataTitle: 'zero', extension: 'yaml' },
	{ name: 'negative', createdAt: -1, metadataTitle: 'neg', extension: 'yaml' },
	{ name: 'fractional', createdAt: 1784700000.9, metadataTitle: 'frac', extension: 'yaml' },
	{ name: 'year-10000', createdAt: 253402300800000, metadataTitle: 'far', extension: 'yaml' },
	{ name: 'nan-created-at', createdAt: Number.NaN, metadataTitle: 'nan', extension: 'yaml' },
	{ name: 'undefined-created-at', createdAt: undefined as unknown as number, metadataTitle: 'undef', extension: 'yaml' },
	{ name: 'infinite-created-at', createdAt: Number.POSITIVE_INFINITY, metadataTitle: 'inf', extension: 'yaml' },
	{ name: 'out-of-range', createdAt: 8.64e15 + 1000, metadataTitle: 'range', extension: 'yaml' },
] as Array<{ name: string; createdAt: number; metadataTitle?: string; plainTitle?: string; extension: string }>;

export const piiCases = [
	{ name: 'plain-placeholder', text: 'a [EMAIL_1] b [EMAIL_1]', mappings: [mapping('[EMAIL_1]', 'e@x.y')] },
	{ name: 'bare-variants', text: 'EMAIL_1 (EMAIL_1) xEMAIL_1 EMAIL_1x EMAIL_1_ EMAIL_1] [EMAIL_1 \nEMAIL_1\tEMAIL_1', mappings: [mapping('[EMAIL_1]', 'e@x.y')] },
	{ name: 'bare-at-start-and-end', text: 'EMAIL_1', mappings: [mapping('[EMAIL_1]', 'E')] },
	{ name: 'adjacent-bare-occurrences', text: 'EMAIL_1 EMAIL_1 EMAIL_1,EMAIL_1', mappings: [mapping('[EMAIL_1]', 'E')] },
	{ name: 'sequential-expansion', text: '[A] [B]', mappings: [mapping('[A]', '[B]'), mapping('[B]', 'final')] },
	{ name: 'later-original-not-reexpanded-backwards', text: '[A] [B]', mappings: [mapping('[B]', '[A]'), mapping('[A]', 'final')] },
	{ name: 'empty-placeholder', text: 'abc', mappings: [mapping('', '-')] },
	{ name: 'empty-placeholder-empty-text', text: '', mappings: [mapping('', '-')] },
	{ name: 'empty-placeholder-astral', text: 'a\u{1F600}b', mappings: [mapping('', '-')] },
	{ name: 'brackets-only', text: '[] [[]] ] [', mappings: [mapping('[]', 'E'), mapping('[]]', 'F'), mapping('[', 'G')] },
	{ name: 'regex-special', text: 'a.b*c (x) $1 \\d [a.b*c]', mappings: [mapping('[a.b*c]', '<$1>'), mapping('(x)', '\\0')] },
	{ name: 'dollar-replacement', text: '[P] $& $1', mappings: [mapping('[P]', "$& $` $' $$")] },
	{ name: 'no-mappings', text: 'untouched [EMAIL_1]', mappings: [] as PIIMapping[] },
	{ name: 'empty-original', text: '[P]x P', mappings: [mapping('[P]', '')] },
	{ name: 'unicode-boundary', text: 'éP \u{1F600}P Pé', mappings: [mapping('[P]', 'p')] },
	{ name: 'surrogate-prefix', text: '\u{1F600}P', mappings: [mapping('[P]', 'p')] },
];

/** Original `isCleartextDraft` expression of convertChatToYaml (the draft-kind oracle). */
export const draftCases = [
	'', 'Typed text', 'v1:abc', 'xv1:abc', 'has encrypted: marker', 'encrypted:abc', 'a'.repeat(999), 'a'.repeat(1000), 'a'.repeat(1001),
	'\u{1F600}'.repeat(499), '\u{1F600}'.repeat(500), 'line\nbreak',
];
