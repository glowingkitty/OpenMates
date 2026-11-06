// TS side of the Apps request/results/schema parity vectors: the committed JSON
// (packages/openmates-rust/src/web_apps/{schema,results}_ts_vectors.json) holds
// outcomes of the flag-off TypeScript code; this test fails if that code drifts.
// web_apps/{schema,results,request}_tests.rs replay the same files against Rust.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { validateSkillInput, type SkillSchema } from '../../../components/apps/appsSkillFormUtils';
import { freshAppsRecommendations, type AppsRecommendation } from '../../appsWorkspaceLibraryService';
import { makePendingAppsResultId } from '../../appsWorkspaceResultOutbox';

const DIR = resolve(__dirname, '../../../../../../../packages/openmates-rust/src/web_apps');
const read = (name: string) => JSON.parse(readFileSync(resolve(DIR, name), 'utf8'));

describe('Apps policy parity vectors (TypeScript side)', () => {
	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('validateSkillInput matches the committed schema vectors', () => {
		for (const c of read('schema_ts_vectors.json').cases) {
			expect(validateSkillInput(c.schema as SkillSchema, c.input), c.name).toEqual(c.out);
		}
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('freshness and outbox ids match the committed results vectors', () => {
		const { freshness, scopes } = read('results_ts_vectors.json');
		const items = freshness.items as AppsRecommendation[];
		expect(freshAppsRecommendations(items, freshness.now).map((item) => items.indexOf(item))).toEqual(freshness.fresh);
		const valid = scopes.find((s: { name: string }) => s.name === 'escaped ids').scope;
		expect(makePendingAppsResultId(valid.userId, valid.teamId, valid.rootEmbedId)).toBe(valid.id);
	});
});
