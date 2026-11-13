// Plan child-collection `work` parity vectors (work lane, Plans slice 3).
// packages/openmates-rust/src/web_work/plan_children_ts_vectors.json is
// regenerated here from the real flag-off userPlanService (crypto, fetch and key
// lookups stubbed); plans_tests.rs replays it through the planChildPath and
// planKeyWrappersAddBody ops. Regenerate:
//   WORK_VECTORS_WRITE=1 npx vitest run src/services/rustCore/__tests__/workPlanChildVectors.test.ts
// spec: specifications/features/plans#plans.content.client-encrypted
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../config/api', () => ({ getApiEndpoint: (path: string) => `https://api.test${path}` }));
vi.mock('../../cryptoService', () => ({
	decryptChatKeyWithMasterKey: vi.fn(async () => new Uint8Array([1])),
	decryptWithEmbedKey: vi.fn(async (value: string) => (value.startsWith('sealed:') ? value.slice(7) : null)),
	encryptWithEmbedKey: vi.fn(async (value: string) => `sealed:${value}`),
	encryptChatKeyWithMasterKey: vi.fn(async () => 'wrapped-master'),
	generateEmbedKey: vi.fn(() => new Uint8Array([9])),
	wrapEmbedKeyWithChatKey: vi.fn(async () => 'wrapped'),
}));
vi.mock('../../projectService', () => ({ listProjects: vi.fn(async () => []) }));
vi.mock('../../encryption/ChatKeyManager', () => ({ chatKeyManager: { getKey: vi.fn(async () => new Uint8Array([7])) } }));

import * as service from '../../userPlanService';
import { createCryptoUnit } from '../crypto/cryptoUnitInstaller';
import { workCall } from '../crypto/workOps';

const VECTORS = resolve(__dirname, '../../../../../../../packages/openmates-rust/src/web_work/plan_children_ts_vectors.json');
type Json = Record<string, unknown>;
let requests: Array<{ url: string; init?: RequestInit }> = [];

const planIds = ['plan-1', 'plan/1 ü'];
const wrappers = [{ key_type: 'master', encrypted_plan_key: 'wrapped-key', created_at: 1 }, { key_type: 'chat', hashed_chat_id: 'h', encrypted_plan_key: 'w', created_at: 2 }];

async function buildVectors(): Promise<Json> {
	const paths: Json[] = [];
	const lists: Array<[string, string, (id: string) => Promise<unknown>]> = [
		['criteria', 'criteria', (id) => service.listPlanCriteria({ plan_id: id, encrypted: { key_wrappers: [wrappers[0]] } } as never)],
		['verification', 'verifications', (id) => service.listPlanVerifications({ plan_id: id, encrypted: { key_wrappers: [wrappers[0]] } } as never)],
		['assumptions', 'assumptions', (id) => service.listPlanAssumptions({ plan_id: id, encrypted: { key_wrappers: [wrappers[0]] } } as never)],
		['reference-patterns', 'reference_patterns', (id) => service.listPlanReferencePatterns({ plan_id: id, encrypted: { key_wrappers: [wrappers[0]] } } as never)],
		['key-wrappers', 'key_wrappers', (id) => service.listUserPlanKeyWrappers(id)],
	];
	for (const [collection, , run] of lists) {
		for (const id of planIds) {
			requests = [];
			await run(id);
			paths.push({ name: `${collection} of ${id}`, op: 'planChildPath', input: { plan_id: id, collection }, expected: requests[0].url.replace('https://api.test', '') });
		}
	}
	const bodies: Json[] = [];
	for (const id of planIds) {
		requests = [];
		await service.addUserPlanKeyWrappers(id, wrappers as never);
		const sent = requests[0];
		bodies.push({ name: `add wrappers to ${id}`, op: 'planKeyWrappersAddBody', input: { plan_id: id, key_wrappers: wrappers },
			expected: { path: sent.url.replace('https://api.test', ''), method: sent.init?.method, body: JSON.parse(String(sent.init?.body)) } });
	}
	return { paths, bodies };
}

describe('user Plan child-collection work parity vectors (TypeScript side)', () => {
	beforeEach(() => {
		vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
			requests.push({ url: String(url), init });
			return new Response(JSON.stringify({ criteria: [], verifications: [], assumptions: [], reference_patterns: [], key_wrappers: [] }), { status: 200 });
		});
	});

	// contract-test: supporting surface=gui.web assertions=plans.content.client-encrypted
	it('the flag-off userPlanService reproduces every committed vector', async () => {
		const fresh = JSON.parse(JSON.stringify(await buildVectors()));
		if (process.env.WORK_VECTORS_WRITE === '1') writeFileSync(VECTORS, `${JSON.stringify(fresh, null, 1)}\n`);
		const committed = JSON.parse(readFileSync(VECTORS, 'utf8'));
		if (JSON.stringify(fresh) !== JSON.stringify(committed)) console.log(`WORK_VECTORS_FRESH_BEGIN\n${JSON.stringify(fresh, null, 1)}\nWORK_VECTORS_FRESH_END`);
		expect(fresh.paths).toHaveLength(10);
		expect(fresh).toEqual(committed);
	});

	// contract-test: supporting surface=gui.web assertions=plans.content.client-encrypted
	it('refuses a collection outside the Plan routes through the Rust export', async () => {
		const binding = new Proxy({ workDecide: () => JSON.stringify({ error: 'bad collection' }) } as Record<string, unknown>, { get: (t, n) => t[n as string] ?? (() => null) });
		const unit = createCryptoUnit(binding);
		const client = {
			call: async <T>(op: string, ...args: unknown[]) => {
				const replies = await unit.handle({ version: 1, requests: [{ id: 1, op: op as never, args }] });
				const response = replies!.responses[0];
				if (!('value' in response)) throw new Error('crypto unit refused the request');
				return response.value as T;
			},
		};
		await expect(workCall(client as never, 'planChildPath', { plan_id: 'p', collection: 'x' })).rejects.toThrow('bad collection');
	});
});
