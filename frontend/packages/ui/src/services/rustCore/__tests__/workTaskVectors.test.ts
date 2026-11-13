// User-Task `work` parity vectors (parked wave-5 `work` lane, slice 2).
// The committed packages/openmates-rust/src/web_work/tasks_ts_vectors.json is
// regenerated here from the real flag-off userTaskService (crypto, fetch, Team
// context and key lookups stubbed); tasks_tests.rs replays it through the Rust
// ops. Regenerate:
//   WORK_VECTORS_WRITE=1 npx vitest run src/services/rustCore/__tests__/workTaskVectors.test.ts
// spec: specifications/features/tasks#tasks.content.client-encrypted
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { webcrypto } from 'node:crypto';
import { resolve } from 'node:path';
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

const stub = vi.hoisted(() => ({
	encrypts: [] as Array<[string, number, string | null]>,
	team: { teamId: null as string | null, epoch: 0, team: null },
	masterKey: null as CryptoKey | null,
}));
const keys = vi.hoisted(() => ({
	decryptChatKeyWithMasterKey: vi.fn(async (_envelope: string) => new Uint8Array([1])),
	unwrapEmbedKeyWithEmbedKey: vi.fn(async (_envelope: string, _key: Uint8Array) => new Uint8Array([2])),
}));

vi.mock('../../../config/api', () => ({ getApiEndpoint: (path: string) => `https://api.test${path}` }));
vi.mock('../../cryptoService', () => ({
	...keys,
	decryptWithEmbedKey: vi.fn(async (value: string, _key: Uint8Array, context?: { associatedData?: string }) => {
		const prefix = context?.associatedData ? `sealedaad:${context.associatedData}|` : 'sealed:';
		return value.startsWith(prefix) ? value.slice(prefix.length) : null;
	}),
	encryptWithEmbedKey: vi.fn(async (value: string, key: Uint8Array, aad?: string) => {
		stub.encrypts.push([value, key[0], aad ?? null]);
		return aad ? `sealed:${key[0]}:${aad}|${value}` : `sealed:${key[0]}:${value}`;
	}),
	encryptChatKeyWithMasterKey: vi.fn(async () => 'wrapped-master'),
	generateEmbedKey: vi.fn(() => new Uint8Array([9])),
	wrapEmbedKeyWithChatKey: vi.fn(async (key: Uint8Array, wrapping: Uint8Array) => `wrap:${key[0]}:${wrapping[0]}`),
}));
vi.mock('../../cryptoKeyStorage', () => ({ getMasterKey: () => stub.masterKey }));
vi.mock('../../teamService', () => ({ getTeamKey: vi.fn(async () => new Uint8Array([4])) }));
vi.mock('../../projectService', () => ({
	listProjects: vi.fn(async () => [
		{ project_id: 'project-a', projectKey: new Uint8Array([5]) },
		{ project_id: 'project-b', projectKey: new Uint8Array([6]) },
	]),
}));
vi.mock('../../encryption/ChatKeyManager', () => ({ chatKeyManager: { getKey: vi.fn(async () => new Uint8Array([7])) } }));
vi.mock('../../../stores/teamStore', async (importOriginal) => ({
	...(await importOriginal<typeof import('../../../stores/teamStore')>()),
	getActiveTeamContextSnapshot: () => stub.team,
	isActiveTeamContext: (teamId: string | null) => stub.team.teamId === teamId,
}));
vi.mock('../../../message_parsing/utils', async (importOriginal) => ({
	...(await importOriginal<typeof import('../../../message_parsing/utils')>()),
	computeSHA256: vi.fn(async (value: string) => `hash:${value}`),
}));

import * as service from '../../userTaskService';
import { buildWorkBody, decryptWorkFields } from '../../work/workRust';
import {
	FRESH_ID, NOW_SECONDS, TEAM, activityCases, bodyCases, dependencies, envelopeCases, pathCases, taskRecord, taskViewCases, teamRecord, workflowRunCases,
} from './helpers/workTaskCases';

const VECTORS = resolve(__dirname, '../../../../../../../packages/openmates-rust/src/web_work/tasks_ts_vectors.json');
const KEY = new Uint8Array([1]);
type Json = Record<string, unknown>;

let replies: unknown[] = [{}];
let requests: Array<{ url: string; init?: RequestInit }> = [];

function json<T>(value: T): T {
	return JSON.parse(JSON.stringify(value)) as T;
}
function strip(value: unknown): unknown {
	if (!value || typeof value !== 'object' || Array.isArray(value)) return json(value);
	const { encrypted: _record, ...view } = value as Json;
	return json(view);
}
async function outcome(run: () => Promise<unknown>): Promise<unknown> {
	try {
		return strip(await run());
	} catch (error) {
		return { error: (error as Error).message };
	}
}
async function inTeam<T>(team: string | null | undefined, run: () => Promise<T>): Promise<T> {
	stub.team = { teamId: team ?? null, epoch: 0, team: null };
	try {
		return await run();
	} finally {
		stub.team = { teamId: null, epoch: 0, team: null };
	}
}
async function firstBoardItem(record: Json, team?: string): Promise<unknown> {
	replies = [{ tasks: [record] }];
	return inTeam(team, async () => (await service.listTaskBoardItems({}))[0]);
}
const path = (index: number) => requests[index].url.replace('https://api.test', '');

async function buildVectors(): Promise<Json> {
	const views: Json[] = [];
	for (const c of taskViewCases) {
		const encrypted = c.envelope ? { ...c.record, encrypted_task_key: c.envelope } : c.record;
		views.push({ name: c.name, op: 'taskView',
			input: json({ record: encrypted, fields: await decryptWorkFields(encrypted, KEY), team_id: c.team ?? null }),
			expected: await outcome(() => firstBoardItem(c.record, c.team)) });
	}
	for (const c of envelopeCases) {
		keys.decryptChatKeyWithMasterKey.mockClear();
		keys.unwrapEmbedKeyWithEmbedKey.mockClear();
		let expected: unknown;
		try {
			await firstBoardItem(c.record, c.team);
			expected = { envelope: keys.unwrapEmbedKeyWithEmbedKey.mock.calls[0]?.[0] ?? keys.decryptChatKeyWithMasterKey.mock.calls[0]?.[0] ?? null };
		} catch (error) {
			expected = { error: (error as Error).message };
		}
		const record = { task_id: c.record.task_id, encrypted_task_key: c.record.encrypted_task_key, key_wrappers: c.record.key_wrappers };
		views.push({ name: c.name, op: 'taskKeyEnvelope', input: json({ record, team_id: c.team ?? null, team_hash: c.team ? `hash:${c.team}` : null }), expected: json(expected) });
	}
	for (const c of workflowRunCases) {
		views.push({ name: c.name, op: 'taskWorkflowRunView', input: { record: c.record }, expected: await outcome(() => firstBoardItem(c.record)) });
	}
	replies = [{ dependencies }];
	views.push({ name: 'dependency edges', op: 'taskDependenciesView', input: { dependencies },
		expected: await outcome(() => service.listUserTaskDependencies('task-1')) });

	const personal = (await firstBoardItem(taskRecord())) as service.UserTaskViewModel;
	const team = (await firstBoardItem(teamRecord(), TEAM)) as service.UserTaskViewModel;
	const activity: Json[] = [];
	for (const c of activityCases) {
		replies = [{ entries: [c.record], next_cursor: null }];
		activity.push({ name: c.name, input: { task_id: personal.task_id, record: c.record },
			expected: await outcome(async () => (await service.listUserTaskActivity(personal))[0]) });
	}

	const paths: Json[] = [];
	for (const c of pathCases) {
		requests = [];
		replies = c.replies;
		let expected: unknown;
		try {
			await inTeam(c.team, () => c.run(service, personal));
			expected = path(c.request ?? 0);
		} catch (error) {
			expected = requests.length > (c.request ?? 0) ? path(c.request ?? 0) : { error: (error as Error).message };
		}
		const input = typeof c.input === 'function' ? await c.input(service, personal) : c.input;
		paths.push({ name: c.name, op: c.op, input: json(input), expected });
	}

	const bodies: Json[] = [];
	for (const c of bodyCases) {
		const task = c.team ? team : personal;
		requests = [];
		stub.encrypts = [];
		replies = [c.reply];
		let expected: Json;
		try {
			await inTeam(c.team ? TEAM : null, () => c.run(service, task));
			const sent = requests[requests.length - 1];
			expected = { path: path(requests.length - 1), method: sent.init?.method, body: JSON.parse(String(sent.init?.body)), encrypt_calls: stub.encrypts };
		} catch (error) {
			expected = { error: (error as Error).message };
		}
		const source = c.source(task);
		const encryptInputs = Object.fromEntries(['tags', 'linkedProjectIds'].map((m) => [m, JSON.stringify(source[m] ?? [])]));
		// A new Task seals with its fresh key (byte 9); Team rows unwrap to byte 2, personal rows to byte 1.
		const sealKeys = { task: c.op === 'taskCreateBody' ? 9 : c.team ? 2 : 1 };
		bodies.push({ name: c.name, op: c.op, input: json(c.input(task)), encrypt_inputs: encryptInputs, keys: sealKeys, expected: json(expected) });
	}
	return { views, activity, paths, bodies };
}

describe('user Task work parity vectors (TypeScript side)', () => {
	beforeAll(async () => {
		vi.stubGlobal('crypto', webcrypto);
		stub.masterKey = await crypto.subtle.importKey('raw', new Uint8Array(32).fill(7), 'AES-GCM', true, ['encrypt', 'decrypt']);
	});

	beforeEach(() => {
		vi.spyOn(Date, 'now').mockReturnValue(NOW_SECONDS * 1000);
		vi.spyOn(globalThis.crypto, 'randomUUID').mockReturnValue(FRESH_ID);
		vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
			requests.push({ url: String(url), init });
			const reply = replies.length > 1 ? replies.shift() : replies[0];
			return new Response(JSON.stringify(reply), { status: 200 });
		});
	});

	// contract-test: supporting surface=gui.web assertions=tasks.content.client-encrypted
	it('the flag-off userTaskService reproduces every committed vector', async () => {
		const fresh = json(await buildVectors());
		if (process.env.WORK_VECTORS_WRITE === '1') writeFileSync(VECTORS, `${JSON.stringify(fresh, null, 1)}\n`);
		const committed = existsSync(VECTORS) ? JSON.parse(readFileSync(VECTORS, 'utf8')) : null;
		// Hosts that cannot write the file (isolated CI) get the regenerated document in the log.
		if (JSON.stringify(fresh) !== JSON.stringify(committed)) console.log(`WORK_VECTORS_FRESH_BEGIN\n${JSON.stringify(fresh, null, 1)}\nWORK_VECTORS_FRESH_END`);
		expect((fresh.views as unknown[]).length + (fresh.bodies as unknown[]).length).toBeGreaterThanOrEqual(60);
		expect(fresh).toEqual(committed);
	});
});

describe('user Task work page adapter', () => {
	// contract-test: supporting surface=gui.web assertions=tasks.content.client-encrypted
	it('seals AAD-bound steps with their associated data and plain steps without', async () => {
		stub.encrypts = [];
		const body = await buildWorkBody([['m', { encrypt: 'Hi', key: 'task', aad: 'task_activity_comment:t:e:v1' }], ['t', { encrypt: 'T', key: 'task' }]], {}, { task: KEY });
		expect(body).toEqual({ m: 'sealed:1:task_activity_comment:t:e:v1|Hi', t: 'sealed:1:T' });
		expect(stub.encrypts).toEqual([['Hi', 1, 'task_activity_comment:t:e:v1'], ['T', 1, null]]);
	});
});
