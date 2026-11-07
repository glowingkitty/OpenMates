import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { parseEmbedLinkTarget, generateDirectEmbedRef } from '../../../utils/embedFragmentUtils';
import { applyVersionPatch } from '../../../utils/embedVersionReconstruction';
import { isTerminalStatus, normalizeEmbedStatus, validateEmbedTransition } from '../../embedStateMachine';

type Vector = Record<string, string | null | undefined> & { kind: string };

const VECTORS = resolve(__dirname, '../../../../../../../packages/openmates-rust/src/embed_read_ts_vectors.json');
const file = JSON.parse(readFileSync(VECTORS, 'utf8')) as { vectors: Vector[] };

function run(v: Vector): { json: string } | { error: string } {
	try {
		switch (v.kind) {
			case 'transition': return { json: JSON.stringify(validateEmbedTransition(v.current as string, v.target as string)) };
			case 'terminal': return { json: JSON.stringify(isTerminalStatus(v.status as string)) };
			case 'normalize': return { json: JSON.stringify(normalizeEmbedStatus(v.status)) };
			case 'link': return { json: JSON.stringify(parseEmbedLinkTarget(v.input as string)) };
			case 'ref': return { json: JSON.stringify(generateDirectEmbedRef(v.embed_type as string, v.embed_id as string,
				{ filename: v.filename, title: v.title, subject: v.subject })) };
			default: return { json: JSON.stringify(applyVersionPatch(v.content as string, v.patch as string)) };
		}
	} catch (error) {
		return { error: (error as Error).message };
	}
}

describe('embed_read vectors (TS source of truth for the Rust port)', () => {
	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('has broad coverage', () => expect(file.vectors.length).toBeGreaterThan(150));
	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('TS still produces every committed outcome', () => {
		const warn = console.warn;
		console.warn = () => undefined;
		try {
			for (const v of file.vectors) {
				const actual = run(v);
				expect(actual, JSON.stringify(v)).toEqual(v.error ? { error: v.error } : { json: v.json });
			}
		} finally {
			console.warn = warn;
		}
	});
});
