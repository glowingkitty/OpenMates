// TS↔Rust parity vectors for the web Project decisions. The committed JSON
// (packages/openmates-rust/src/web_projects_ts_vectors.json) is written by
// packages/openmates-rust/tests/crypto_fixtures/ts_web_projects/generate.mjs from the
// real projectState/*Policy.ts rules; this test re-runs those rules against it and
// web_projects_tests.rs replays the same file through Rust.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

import { PROJECT_STATE_POLICY, runProjectStatePolicy, type ProjectStateOpName } from '../../projectState/policy';
import { createProjectStateHandlers } from '../chatState/projectStateOps';
import { UnitRefusal } from '../host/unitPort';

const FIXTURES = resolve(__dirname, '../../../../../../../packages/openmates-rust');
const vectors = JSON.parse(readFileSync(resolve(FIXTURES, 'src/web_projects_ts_vectors.json'), 'utf8'));

interface VectorCase { name: string; input: unknown; expected: unknown }

describe('project state parity vectors', () => {
	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('TypeScript rules reproduce every recorded vector outcome', () => {
		const ops = Object.entries(vectors.ops) as [ProjectStateOpName, VectorCase[]][];
		expect(ops.map(([op]) => op).sort()).toEqual(Object.keys(PROJECT_STATE_POLICY).sort());
		for (const [op, cases] of ops) {
			for (const c of cases) {
				expect(runProjectStatePolicy(op, c.input), `${op}: ${c.name}`).toEqual(c.expected);
			}
		}
	});
});

describe('chatState projectDecide op', () => {
	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('forwards op and JSON input to the Rust export and refuses with protocol on failure', () => {
		const calls: unknown[][] = [];
		const handlers = createProjectStateHandlers({
			chat_state_project_decide: (op: string, input: string) => {
				calls.push([op, input]);
				if (op === 'boom') throw new Error('unknown_op:boom');
				return JSON.stringify({ pending: null });
			},
		});
		const decide = handlers.projectDecide as (payload: unknown) => unknown;
		expect(decide({ op: 'projectWorkflowRemoteGate', input: { phase: 'source' } })).toEqual({ pending: null });
		expect(calls[0]).toEqual(['projectWorkflowRemoteGate', '{"phase":"source"}']);
		expect(() => decide({ op: 'boom', input: {} })).toThrow(UnitRefusal);
		expect(() => decide({ input: {} })).toThrow(UnitRefusal);
		const unbound = createProjectStateHandlers({}).projectDecide as (payload: unknown) => unknown;
		expect(() => unbound({ op: 'projectWorkflowRemoteGate', input: {} })).toThrow(UnitRefusal);
	});
});
