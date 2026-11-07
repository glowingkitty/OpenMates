import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { referenceOps } from './persistPolicyReference';

const VECTORS = resolve(__dirname, '../../../../../../../packages/openmates-rust/src/web_persist/policy_vectors.json');
const vectors = JSON.parse(readFileSync(VECTORS, 'utf8')) as Record<string, Array<{ input: unknown; out: unknown }>>;
const roundTrip = (value: unknown) => JSON.parse(JSON.stringify(value));

describe('cache and chat-row policy parity vectors (TypeScript side)', () => {
	// contract-test: supporting surface=gui.web assertions=storage.client.shared-policy-existing-adapters
	it('covers every op of the reference table', () => {
		expect(Object.keys(vectors).sort()).toEqual(Object.keys(referenceOps).sort());
	});

	for (const [op, cases] of Object.entries(vectors)) {
		// contract-test: supporting surface=gui.web assertions=storage.client.shared-policy-existing-adapters
		it(`${op} matches the committed vectors`, () => {
			expect(cases.length).toBeGreaterThan(0);
			for (const c of cases) expect(roundTrip(referenceOps[op](c.input)), JSON.stringify(c)).toEqual(c.out);
		});
	}
});
