// Billing-context and referral `work` parity vectors (work lane, billing slice).
// The committed packages/openmates-rust/src/web_work/billing_ts_vectors.json is
// regenerated here from the real flag-off billingContext and referralService
// (fetch stubbed: no payment, purchase or referral is ever sent anywhere);
// billing_tests.rs replays it through the Rust ops. Regenerate:
//   WORK_VECTORS_WRITE=1 npx vitest run src/services/rustCore/__tests__/workBillingVectors.test.ts
// spec: specifications/features/teams#teams.billing.context-parity
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../config/api', async (importOriginal) => ({
	...(await importOriginal<typeof import('../../../config/api')>()),
	getApiEndpoint: (path: string = '') => `https://api.test${path}`,
}));

import { billingPath, loadBillingAddress, saveBillingAddress, type BillingAddress, type BillingContext } from '../../billingContext';

const VECTORS = resolve(__dirname, '../../../../../../../packages/openmates-rust/src/web_work/billing_ts_vectors.json');
const PENDING_REFERRAL_KEY = 'openmates_pending_referral_code';
type Json = Record<string, unknown>;

const OPERATIONS = ['address', 'balance', 'methods', 'cardOrder', 'savedCardOrder', 'bankOrder', 'bankStatus', 'invoices', 'autoTopup', 'monthly', 'usage', 'usageExport', 'saveMethod'] as const;
const PERSONAL: BillingContext = { kind: 'personal' };
const TEAM: BillingContext = { kind: 'team', teamId: 'team/1 ä?#&' };
// Placeholder buyer data; the member order is deliberately not alphabetical (the page keeps it).
const ADDRESS: BillingAddress = {
	name: 'Example GmbH', street_line_1: 'Examplestr. 1', street_line_2: null, postal_code: '10115',
	city: 'Berlin', region: null, country: 'DE', vat_id: 'DE000000000',
};

let status = 200;
let reply: unknown = { buyer_address: ADDRESS };
let requests: Array<{ url: string; init?: RequestInit }> = [];

const strip = (url: string) => url.replace('https://api.test', '');
async function outcome(run: () => Promise<unknown>): Promise<Json> {
	try {
		await run();
		return {};
	} catch (error) {
		return { error: (error as Error).message };
	}
}
function sent(index = 0): Json {
	const request = requests[index];
	return { path: strip(request.url), method: request.init?.method ?? 'GET', body: JSON.parse(String(request.init?.body)) };
}
async function freshReferralService(): Promise<typeof import('../../referralService')> {
	vi.resetModules();
	return import('../../referralService');
}

async function buildVectors(): Promise<Json> {
	const contexts: Array<[string, BillingContext]> = [
		['personal', PERSONAL], ['team', TEAM], ['team plain id', { kind: 'team', teamId: 'team-2' }],
		['team blank id', { kind: 'team', teamId: '' }], ['team whitespace id', { kind: 'team', teamId: ' \t ﻿\n' }],
	];
	const paths: Json[] = [];
	for (const [label, context] of contexts) {
		for (const operation of OPERATIONS) {
			let expected: unknown;
			try {
				expected = strip(billingPath(context, operation));
			} catch (error) {
				expected = { error: (error as Error).message };
			}
			paths.push({ name: `${label} ${operation}`, op: 'billingPath', input: { context, operation }, expected });
		}
	}
	const service = await freshReferralService();
	requests = [];
	status = 200;
	await service.loadReferralStatus();
	paths.push({ name: 'referral status', op: 'referralStatusPath', input: {}, expected: strip(requests[0].url) });

	const bodies: Json[] = [];
	const saves: Array<[string, BillingContext, BillingAddress | null]> = [
		['personal address', PERSONAL, ADDRESS], ['personal clears address', PERSONAL, null],
		['team address', TEAM, ADDRESS], ['team blank id is refused', { kind: 'team', teamId: ' ' }, ADDRESS],
	];
	for (const [name, context, address] of saves) {
		requests = [];
		status = 200;
		reply = { buyer_address: address };
		const result = await outcome(() => saveBillingAddress(context, address));
		bodies.push({ name, op: 'billingAddressBody', input: { context }, expected: requests.length ? sent() : result });
	}
	for (const code of ['ABCD1234', 'ZZZZ']) {
		const referral = await freshReferralService();
		requests = [];
		status = 200;
		reply = {};
		sessionStorage.setItem(PENDING_REFERRAL_KEY, code);
		await referral.submitPendingReferralCode();
		bodies.push({ name: `referral capture ${code}`, op: 'referralCaptureBody', input: { code }, expected: sent() });
	}

	const results: Json[] = [];
	for (const code of [200, 201, 400, 404, 500]) {
		for (const action of ['load', 'save'] as const) {
			status = code;
			reply = { buyer_address: null };
			const expected = await outcome(() => (action === 'load' ? loadBillingAddress(PERSONAL) : saveBillingAddress(PERSONAL, null)));
			results.push({ name: `${action} ${code}`, op: 'billingAddressResult', input: { action, ok: code < 300, status: code }, expected });
		}
		const referral = await freshReferralService();
		const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
		status = code;
		reply = {};
		const loaded = await referral.loadReferralStatus();
		const warned = warn.mock.calls[0]?.[1] as Error | undefined;
		warn.mockRestore();
		results.push({ name: `referral status ${code}`, op: 'referralStatusResult', input: { ok: code < 300, status: code },
			expected: loaded ? {} : { error: warned?.message ?? null } });
	}
	return { paths, bodies, results };
}

describe('billing work parity vectors (TypeScript side)', () => {
	beforeEach(() => {
		sessionStorage.clear();
		vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
			requests.push({ url: String(url), init });
			return new Response(JSON.stringify(reply), { status });
		});
	});

	// contract-test: supporting surface=gui.web assertions=teams.billing.context-parity,billing.purchase.provider-routing
	it('the flag-off billing and referral services reproduce every committed vector', async () => {
		const fresh = JSON.parse(JSON.stringify(await buildVectors()));
		if (process.env.WORK_VECTORS_WRITE === '1') writeFileSync(VECTORS, `${JSON.stringify(fresh, null, 1)}\n`);
		const committed = existsSync(VECTORS) ? JSON.parse(readFileSync(VECTORS, 'utf8')) : null;
		// Hosts that cannot write the file (isolated CI) get the regenerated document in the log.
		if (JSON.stringify(fresh) !== JSON.stringify(committed)) console.log(`WORK_VECTORS_FRESH_BEGIN\n${JSON.stringify(fresh, null, 1)}\nWORK_VECTORS_FRESH_END`);
		expect((fresh.paths as unknown[]).length + (fresh.bodies as unknown[]).length).toBeGreaterThanOrEqual(70);
		expect(fresh).toEqual(committed);
	});
});
