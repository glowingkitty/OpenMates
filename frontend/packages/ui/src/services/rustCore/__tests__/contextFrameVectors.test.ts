/**
 * Parity vectors of the retained admission-phase frame check (TypeScript side).
 *
 * Runs the real fastAdmissionPhaseJournal on the committed inputs and compares the
 * outcome to packages/openmates-rust/src/web_stream/context_frame_ts_vectors.json,
 * which the Rust tests replay against web_stream::recovery::context_frame_json.
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { retainOrReuseContextPhaseFrameWithSeal, type AdmissionContextPhase } from '../../fastAdmissionPhaseJournal';

const VECTORS = resolve(__dirname, '../../../../../../../packages/openmates-rust/src/web_stream/context_frame_ts_vectors.json');
type Case = { plaintext: string | null; identity: Record<string, unknown>; phase: AdmissionContextPhase; out: { kind: string; code?: string } };
const cases: Case[] = JSON.parse(readFileSync(VECTORS, 'utf8')).contextFrame;

const CODES: Array<[string, string]> = [
	['cannot be decrypted', 'undecryptable'], ['is invalid', 'invalid'], ['different turn identity', 'identity'],
];

describe('retained admission frame parity vectors (TypeScript side)', () => {
	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('matches the committed outcomes', async () => {
		expect(cases.length).toBeGreaterThan(30);
		for (const c of cases) {
			let out: Case['out'];
			try {
				await retainOrReuseContextPhaseFrameWithSeal({
					identity: c.identity as never, phase: c.phase,
					read: async () => 'sealed', commit: async (s) => s, seal: async (f) => JSON.stringify(f),
					open: async () => c.plaintext,
				});
				out = { kind: 'ok' };
			} catch (e) {
				const message = (e as Error).message;
				const code = CODES.find(([needle]) => message.includes(needle))?.[1];
				out = { kind: 'error', code };
			}
			expect(out, JSON.stringify(c)).toEqual(c.out);
		}
	});
});
