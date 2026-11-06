// TS-generated parity vectors for the shared Rust TOON decoder
// (packages/openmates-rust/src/toon_decode.rs). The committed JSON
// (packages/openmates-rust/src/toon_decode_ts_vectors.json, written by
// scripts/generate-toon-decode-vectors.mjs) records what the pinned
// `@toon-format/toon` `decode(input, { strict: false })` returns; this test fails
// if the TS decoder drifts from it, and toon_decode_tests.rs replays the same
// file against the Rust decoder.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { decode } from '@toon-format/toon';
import { describe, expect, it } from 'vitest';

type Vector = { name: string; input: string; json?: string; error?: true };

const VECTORS = resolve(__dirname, '../../../../../../../packages/openmates-rust/src/toon_decode_ts_vectors.json');
const file = JSON.parse(readFileSync(VECTORS, 'utf8')) as { library: string; vectors: Vector[] };

describe('TOON decode vectors (TS source of truth for the Rust decoder)', () => {
	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('pins the library version the web client ships', () => {
		const pkg = JSON.parse(readFileSync(resolve(__dirname, '../../../../package.json'), 'utf8')) as {
			dependencies: Record<string, string>;
		};
		expect(file.library).toBe(`@toon-format/toon@${pkg.dependencies['@toon-format/toon']}`);
		expect(file.vectors.length).toBeGreaterThanOrEqual(60);
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it.each(file.vectors.map((vector) => [vector.name, vector] as const))('%s', (_name, vector) => {
		let actual: { json: string } | { error: true };
		try {
			actual = { json: JSON.stringify(decode(vector.input, { strict: false })) };
		} catch {
			actual = { error: true };
		}
		expect(actual).toEqual(vector.error ? { error: true } : { json: vector.json });
	});
});
