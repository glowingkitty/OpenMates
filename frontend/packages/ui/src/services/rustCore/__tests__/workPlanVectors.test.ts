// User-Plan `work` parity vectors (parked wave-5 `work` lane, slice 1).
// The committed packages/openmates-rust/src/web_work/plans_ts_vectors.json is
// regenerated here from the real flag-off userPlanService (crypto, fetch and key
// lookups stubbed); plans_tests.rs replays it through the Rust ops. Regenerate:
//   WORK_VECTORS_WRITE=1 npx vitest run src/services/rustCore/__tests__/workPlanVectors.test.ts
// spec: specifications/features/plans#plans.content.client-encrypted
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const stub = vi.hoisted(() => ({ encrypts: [] as Array<[string, number]> }));

vi.mock('../../../config/api', () => ({ getApiEndpoint: (path: string) => `https://api.test${path}` }));
vi.mock('../../cryptoService', () => ({
	decryptChatKeyWithMasterKey: vi.fn(async () => new Uint8Array([1])),
	decryptWithEmbedKey: vi.fn(async (value: string) => (value.startsWith('sealed:') ? value.slice(7) : null)),
	encryptWithEmbedKey: vi.fn(async (value: string, key: Uint8Array) => {
		stub.encrypts.push([value, key[0]]);
		return `sealed:${key[0]}:${value}`;
	}),
	encryptChatKeyWithMasterKey: vi.fn(async () => 'wrapped-master'),
	generateEmbedKey: vi.fn(() => new Uint8Array([9])),
	wrapEmbedKeyWithChatKey: vi.fn(async (key: Uint8Array, wrapping: Uint8Array) => `wrap:${key[0]}:${wrapping[0]}`),
}));
vi.mock('../../projectService', () => ({
	listProjects: vi.fn(async () => [
		{ project_id: 'project-a', projectKey: new Uint8Array([5]) },
		{ project_id: 'project-b', projectKey: new Uint8Array([6]) },
	]),
}));
vi.mock('../../encryption/ChatKeyManager', () => ({ chatKeyManager: { getKey: vi.fn(async () => new Uint8Array([7])) } }));
vi.mock('../../../message_parsing/utils', async (importOriginal) => ({
	...(await importOriginal<typeof import('../../../message_parsing/utils')>()),
	computeSHA256: vi.fn(async (value: string) => `hash:${value}`),
}));

import * as service from '../../userPlanService';
import { buildWorkBody, decryptWorkFields, workView } from '../../work/workRust';
import { createCryptoUnit } from '../crypto/cryptoUnitInstaller';
import { workCall } from '../crypto/workOps';
import { FRESH_ID, NOW_SECONDS, bodyCases, childViewCases, pathCases, planRecord, planViewCases } from './helpers/workPlanCases';

const VECTORS = resolve(__dirname, '../../../../../../../packages/openmates-rust/src/web_work/plans_ts_vectors.json');
const PLAN_KEY = new Uint8Array([1]);
type Json = Record<string, unknown>;

let reply: unknown = {};
let requests: Array<{ url: string; init?: RequestInit }> = [];

function json<T>(value: T): T {
	return JSON.parse(JSON.stringify(value)) as T;
}
async function outcome(run: () => Promise<unknown>): Promise<unknown> {
	try {
		const value = (await run()) as Json;
		const { encrypted: _record, ...view } = value;
		return json(view);
	} catch (error) {
		return { error: (error as Error).message };
	}
}

async function buildVectors(): Promise<Json> {
	const views: Json[] = [];
	for (const c of planViewCases) {
		reply = { plan: c.record };
		views.push({ name: c.name, op: 'planView', input: { record: c.record, fields: await decryptWorkFields(c.record, PLAN_KEY) },
			expected: await outcome(() => service.getFreshUserPlan('plan-1')) });
	}
	reply = { plan: planRecord() };
	const plan = await service.getFreshUserPlan('plan-1');
	for (const c of childViewCases) {
		reply = { [c.member]: [c.record] };
		const list = service[c.list] as (plan: service.UserPlanViewModel) => Promise<unknown[]>;
		const expected = await outcome(async () => (await list(plan))[0]);
		views.push({ name: c.name, op: c.op, input: { record: c.record, fields: await decryptWorkFields(c.record, PLAN_KEY) }, expected });
	}
	const paths: Json[] = [];
	for (const c of pathCases) {
		requests = [];
		reply = { plans: [], plan: planRecord() };
		if (c.op === 'planListPath') await service.listFreshUserPlanRecords(c.filters ?? {}, c.teamId);
		else await service.getFreshUserPlan(c.planId ?? '', c.teamId);
		const input = c.op === 'planListPath' ? { filters: c.filters, team_id: c.teamId ?? null } : { plan_id: c.planId, team_id: c.teamId ?? null };
		paths.push({ name: c.name, op: c.op, input, expected: requests[0].url.replace('https://api.test', '') });
	}
	const bodies: Json[] = [];
	for (const c of bodyCases) {
		requests = [];
		stub.encrypts = [];
		reply = c.reply;
		const source = c.source(plan);
		let expected: Json;
		try {
			await c.run(service, plan);
			const sent = requests[requests.length - 1];
			expected = { path: sent.url.replace('https://api.test', ''), method: sent.init?.method, body: JSON.parse(String(sent.init?.body)), encrypt_calls: stub.encrypts };
		} catch (error) {
			expected = { error: (error as Error).message };
		}
		const encryptInputs = Object.fromEntries(['userFlows', 'linkedProjectIds'].map((m) => [m, JSON.stringify(source[m] ?? [])]));
		// A new Plan seals with its freshly generated key (the generateEmbedKey stub, byte 9).
		const keys = c.op === 'planCreateBody' ? { plan: 9, task: 9 } : { plan: 1, task: 9 };
		bodies.push({ name: c.name, op: c.op, input: json(c.input(plan)), encrypt_inputs: encryptInputs, keys, expected: json(expected) });
	}
	return { views, paths, bodies };
}

describe('user Plan work parity vectors (TypeScript side)', () => {
	beforeEach(() => {
		vi.spyOn(Date, 'now').mockReturnValue(NOW_SECONDS * 1000);
		vi.spyOn(globalThis.crypto, 'randomUUID').mockReturnValue(FRESH_ID);
		vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
			requests.push({ url: String(url), init });
			return new Response(JSON.stringify(reply), { status: 200 });
		});
	});

	// contract-test: supporting surface=gui.web assertions=plans.content.client-encrypted
	it('the flag-off userPlanService reproduces every committed vector', async () => {
		const fresh = json(await buildVectors());
		if (process.env.WORK_VECTORS_WRITE === '1') writeFileSync(VECTORS, `${JSON.stringify(fresh, null, 1)}\n`);
		const committed = JSON.parse(readFileSync(VECTORS, 'utf8'));
		// Hosts that cannot write the file (isolated CI) get the regenerated document in the log.
		if (JSON.stringify(fresh) !== JSON.stringify(committed)) console.log(`WORK_VECTORS_FRESH_BEGIN\n${JSON.stringify(fresh, null, 1)}\nWORK_VECTORS_FRESH_END`);
		expect((fresh.views as unknown[]).length + (fresh.bodies as unknown[]).length).toBeGreaterThanOrEqual(40);
		expect(fresh).toEqual(committed);
	});
});

describe('user Plan work page adapter', () => {
	// contract-test: supporting surface=gui.web assertions=plans.content.client-encrypted
	it('decrypts only non-empty encrypted members, never wrapped keys', async () => {
		const fields = await decryptWorkFields({ encrypted_title: 'sealed:T', encrypted_goal: '', encrypted_risks: null, encrypted_task_key: 'sealed:k', encrypted_bad: 'x', status: 'sealed:s' }, PLAN_KEY);
		expect(fields).toEqual({ encrypted_title: 'T', encrypted_bad: '' });
	});

	// contract-test: supporting surface=gui.web assertions=plans.content.client-encrypted
	it('applies body steps in order and refuses a missing key or slot builder', async () => {
		stub.encrypts = [];
		const body = await buildWorkBody([
			['a', { value: 1 }], ['b', { encrypt: 'x', key: 'plan' }], ['c', { encrypt_input: 'flows', key: 'task' }], ['d', { slot: 'd' }],
		], { flows: [{ z: 1, a: 2 }] }, { plan: PLAN_KEY, task: new Uint8Array([9]) }, { d: async () => ['w'] });
		expect(body).toEqual({ a: 1, b: 'sealed:1:x', c: 'sealed:9:[{"z":1,"a":2}]', d: ['w'] });
		expect(stub.encrypts).toEqual([['x', 1], ['[{"z":1,"a":2}]', 9]]);
		await expect(buildWorkBody([['b', { encrypt: 'x', key: 'task' }]], {}, { task: null })).rejects.toThrow('no task key');
		await expect(buildWorkBody([['d', { slot: 'd' }]], {}, {})).rejects.toThrow('no builder for slot d');
	});

	// contract-test: supporting surface=gui.web assertions=plans.content.client-encrypted
	it('routes work to the Rust export, reattaches the record and rethrows an error answer', async () => {
		const calls: unknown[][] = [];
		const own: Record<string, unknown> = {
			workDecide: (name: string, input: string) => {
				calls.push([name, input]);
				return name === 'boom' ? JSON.stringify({ error: 'Plan user flows must be an array' }) : JSON.stringify({ title: 'T' });
			},
		};
		const binding = new Proxy(own, { get: (target, name) => target[name as string] ?? (() => null) });
		const unit = createCryptoUnit(binding);
		const client = {
			call: async <T>(op: string, ...args: unknown[]) => {
				const replies = await unit.handle({ version: 1, requests: [{ id: 1, op: op as never, args }] });
				const response = replies!.responses[0];
				if (!('value' in response)) throw new Error('crypto unit refused the request');
				return response.value as T;
			},
		};
		const record = { plan_id: 'p', encrypted_title: 'sealed:T' };
		expect(await workView(client as never, 'planView', record, PLAN_KEY)).toEqual({ title: 'T', encrypted: record });
		expect(calls[0]).toEqual(['planView', JSON.stringify({ record, fields: { encrypted_title: 'T' } })]);
		await expect(workCall(client as never, 'boom', {})).rejects.toThrow('Plan user flows must be an array');
	});
});
