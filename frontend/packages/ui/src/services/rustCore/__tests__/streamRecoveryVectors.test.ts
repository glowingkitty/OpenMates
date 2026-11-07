/**
 * Parity vectors of the web AI-stream recovery decisions (TypeScript side).
 *
 * Runs the real TypeScript functions on the committed inputs and compares them to
 * packages/openmates-rust/src/web_stream/ts_vectors.json, which the Rust tests
 * replay against web_stream. Regenerate with UPDATE_STREAM_VECTORS=1.
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { decode, encode } from '@toon-format/toon';

const api = vi.hoisted(() => ({ body: null as unknown, ok: true }));
vi.mock('../../../config/api', () => ({
	getApiEndpoint: (path: string) => path,
	storageArchiveFetch: async () => ({ ok: api.ok, json: async () => api.body }),
}));
// refreshPersistedAssistantVersion reads through the global fetch.
vi.stubGlobal('fetch', async () => ({ ok: api.ok, json: async () => api.body }));

import { chatAfterRecoveredReply } from '../../chatRecoveryVersionApply';
import { refreshPersistedAssistantVersion, refreshRecoveryChatVersion } from '../../chatRecoveryVersionRefresh';
import { catalogContextFromSealedEmbed, historySourceFromSealedEmbed, isUnwrittenInitialDiffRead } from '../../recoveryEmbedSource';
import { clearRecoveryFinalTimestamps, recordRecoveryFinalTimestamp, recoveryFinalTimestamp } from '../../recoveryAssistantTimestamp';
import type { Chat } from '../../../types/chat';

const VECTORS = resolve(__dirname, '../../../../../../../packages/openmates-rust/src/web_stream/ts_vectors.json');
const update = process.env.UPDATE_STREAM_VECTORS === '1';
const stored = update ? {} : JSON.parse(readFileSync(VECTORS, 'utf8'));
const generated: Record<string, unknown> = { schema: 1 };
const json = (value: unknown) => JSON.parse(JSON.stringify(value === undefined ? null : value));
const error = (e: unknown) => ({ error: (e as Error).message });

function check(name: string, value: unknown) {
	generated[name] = value;
	if (!update) expect(value, name).toEqual(stored[name]);
}

const CHAT_ID = 'chat-1';
const fence = (v?: number, l?: number, u?: number) => ({ messages_v: v, last_edited_overall_timestamp: l, updated_at: u });

describe('stream recovery parity vectors (TypeScript side)', () => {
	afterEach(() => {
		if (update && generated.finalTimestamps !== undefined) writeFileSync(VECTORS, JSON.stringify(generated, null, 1) + '\n');
	});

	// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy
	it('version fence', () => {
		const cases = [] as unknown[];
		for (const latest of [fence(5, 100, 100), fence(7, 100, 100), fence(6, 100, 100), fence(0, 0, 0), fence(undefined, 100, 100), fence(3, undefined, 50), fence(3, 900, 20)]) {
			for (const committed of [0, 5, 6, 7, 12]) {
				for (const now of [50, 200]) {
					const baseline = latest as unknown as Chat;
					const out = chatAfterRecoveredReply(null, baseline, committed, now);
					const wire = out === baseline ? { keep: true } : { keep: false, ...json({ messages_v: out.messages_v, last_edited_overall_timestamp: out.last_edited_overall_timestamp, updated_at: out.updated_at }) };
					cases.push({ latest: json(latest), committedVersion: committed, now, out: wire });
				}
			}
		}
		check('apply', cases);
	});

	// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy
	it('window and persisted-assistant version responses', async () => {
		const chat = { chat_id: CHAT_ID } as Chat;
		const row = (o: Record<string, unknown> = {}) => ({ message_id: 'a1', chat_id: CHAT_ID, role: 'assistant', user_message_id: 'u1', encrypted_content: 'enc', ...o });
		const bodies = [
			{ chat_id: CHAT_ID, messages_v: 4 }, { chat_id: CHAT_ID, messages_v: 0 }, { chat_id: CHAT_ID, messages_v: -1 },
			{ chat_id: CHAT_ID, messages_v: 1.5 }, { chat_id: CHAT_ID, messages_v: '4' }, { chat_id: CHAT_ID, messages_v: 9007199254740992 },
			{ chat_id: 'other', messages_v: 4 }, { messages_v: 4 }, { chat_id: CHAT_ID }, null, 5, [],
			{ chat_id: CHAT_ID, messages_v: 6, messages: [row()] }, { chat_id: CHAT_ID, messages_v: 6, messages: [row({ encrypted_content: '   ﻿ ' })] },
			{ chat_id: CHAT_ID, messages_v: 6, messages: [row({ encrypted_content: '\u0085' })] }, { chat_id: CHAT_ID, messages_v: 6, messages: [row({ role: 'user' })] },
			{ chat_id: CHAT_ID, messages_v: 6, messages: [row({ user_message_id: 'u2' })] }, { chat_id: CHAT_ID, messages_v: 6, messages: [row({ chat_id: 'x' })] },
			{ chat_id: CHAT_ID, messages_v: 6, messages: [row({ message_id: 'a2' })] }, { chat_id: CHAT_ID, messages_v: 6, messages: [null, row()] },
			{ chat_id: CHAT_ID, messages_v: 6, messages: [row({ encrypted_content: 7 })] }, { chat_id: CHAT_ID, messages_v: 6, messages: {} },
			{ chat_id: CHAT_ID, messages_v: 6 }, { chat_id: CHAT_ID, messages_v: 6, messages: [] },
		];
		const windowCases = [] as unknown[];
		const assistantCases = [] as unknown[];
		for (const body of bodies) {
			api.body = body;
			const w = await refreshRecoveryChatVersion(chat);
			windowCases.push({ chatId: CHAT_ID, result: body, out: { version: w ? w.messages_v : null } });
			const a = await refreshPersistedAssistantVersion(chat, 'a1', 'u1');
			assistantCases.push({ chatId: CHAT_ID, assistantMessageId: 'a1', userMessageId: 'u1', result: body, out: { version: a } });
		}
		check('windowVersion', windowCases);
		check('assistantVersion', assistantCases);
	});

	// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy
	it('initial diff, catalog and history source', async () => {
		const diff = [] as unknown[];
		for (const status of [409, 404, 200]) for (const detail of ['snapshot_required', 'other', null, 7]) for (const version of [1, 2, 0]) {
			diff.push({ status, detail, version, out: { unwritten: isUnwrittenInitialDiffRead(status, detail, version) } });
		}
		check('initialDiff', diff);

		const catalog = [] as unknown[];
		const producers: unknown[] = [undefined, null, 'app_1', 'Bad', '', 'a'.repeat(64), 'a'.repeat(65), 5, '1abc', 'a-b'];
		const fieldSets: Array<Record<string, unknown> | null> = [null, {}, { app_id: 'web', skill_id: 'search' }, { app_id: null, skill_id: 'x' }, { app_id: 'web' }, { skill_id: 'Search' }, { app_id: 7, skill_id: 'x' }];
		for (const app of producers) for (const skill of [undefined, 'search', null, 'Bad']) for (const fields of fieldSets) {
			const content = fields ? encode(fields) : 'just text';
			let out: unknown;
			try { out = await catalogContextFromSealedEmbed(content, app, skill); } catch (e) { out = error(e); }
			const needsFields = app === undefined || skill === undefined;
			// The page decodes only when a producer id is missing, and keeps plain objects.
			const read = needsFields ? decode(content, { strict: false }) : null;
			const decoded = read && typeof read === 'object' && !Array.isArray(read) ? read : null;
			catalog.push({ producerApp: app === undefined ? undefined : app, producerSkill: skill, fields: decoded, out: json(out) });
		}
		check('catalog', json(catalog));

		const history = [] as unknown[];
		const decodedSet: Array<[string, Record<string, unknown>]> = [
			['code', { type: 'code', code: 'let a = 1;' }], ['code', { type: 'code', code: 5 }], ['code', { type: 'sheet', code: 'x' }],
			['pcb_schematic', { type: 'pcb_schematic', code: 'pcb' }], ['sheet', { type: 'sheet', table: 'a|b' }], ['mermaid', { type: 'mermaid', diagram_code: 'graph TD' }],
			['mermaid', { type: 'mermaid' }], ['image', { type: 'image', code: 'x' }],
			['mail', { type: 'mail', receiver: 'a@b.c', subject: 'Hi', content: 'Body', footer: 'Bye' }], ['mail', { type: 'mail', content: 'Body' }],
			['mail', { type: 'mail' }], ['mail', { type: 'mail', receiver: 5 }], ['mail', { type: 'mail', subject: 'S', footer: 'F' }],
			['document', { type: 'document', html: '<p>x</p>', docx_model: { b: 1, a: [1, 2] } }], ['document', { type: 'document', html: '', docx_model: { z: 1, a: { y: 2, b: [] } } }],
			['document', { type: 'document', docx_model: [1] }], ['document', { type: 'document' }], ['document', { type: 'document', html: 5, docx_model: { k: 'v' } }],
			['notebook', { type: 'notebook', notebook: { cells: [], meta: { n: 1 } } }], ['notebook', { type: 'notebook', content: 'raw' }], ['notebook', { type: 'notebook', content: '' }],
			['notebook', { type: 'notebook', notebook: 'str', content: 'c' }], ['notebook', { type: 'notebook' }], ['notebook', { type: 'document', notebook: {} }],
		];
		for (const [type, decoded] of decodedSet) {
			let out: unknown;
			try { out = await historySourceFromSealedEmbed(encode(decoded), type); } catch (e) { out = error(e); }
			history.push({ type, decoded, out: json(out) });
		}
		check('historySource', history);
	});

	describe('recovery final timestamps', () => {
		beforeEach(() => { vi.useFakeTimers(); clearRecoveryFinalTimestamps(); });
		afterEach(() => vi.useRealTimers());

		// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy
		it('record, expire and bound', () => {
			const ev = (n: number, over: Record<string, unknown> = {}) => ({
				chat_id: 'c', message_id: `m${n}`, user_message_id: 'u', recovery_job_id: 'j', recovery_turn_id: 't',
				recovery_protocol_version: 1, created_at: 1000 + n, is_final_chunk: true, ...over,
			});
			const steps: unknown[] = [];
			let now = 1_000_000;
			const at = (t: number) => { now = t; vi.setSystemTime(now); };
			const record = (event: Record<string, unknown>) => {
				recordRecoveryFinalTimestamp(event as never);
				steps.push({ op: 'record', now, event: json(event) });
			};
			const get = (n: number, job = 'j') => {
				const out = recoveryFinalTimestamp('c', `m${n}`, job, 't');
				steps.push({ op: 'get', now, chat_id: 'c', message_id: `m${n}`, job_id: job, turn_id: 't', out: { createdAt: out } });
			};
			at(now);
			record(ev(1)); get(1); get(2); get(1, 'other');
			record(ev(1, { created_at: 5000 })); get(1);
			for (const over of [{ is_final_chunk: false }, { recovery_protocol_version: 2 }, { chat_id: '' }, { message_id: '' }, { user_message_id: '' },
				{ recovery_job_id: null }, { recovery_turn_id: undefined }, { created_at: 0 }, { created_at: 1.5 }, { created_at: '5' }]) {
				record(ev(9, over)); get(9);
			}
			at(now + 599_999); get(1);
			at(now + 2); get(1);
			at(1_000_000 + 700_000); record(ev(3)); get(1); get(3);
			at(now + 100);
			for (let n = 10; n < 10 + 130; n++) { record(ev(n)); }
			get(10); get(11); get(12); get(138); get(139);
			check('finalTimestamps', steps);
		});
	});
});
