// TS-generated parity vectors for the shared Rust composer suggestion helpers. The
// committed JSON (packages/openmates-rust/src/web_composer/suggestion_ts_vectors.json) is
// written by helpers/generateSuggestionVectors.mjs from the real flag-off TypeScript
// modules; this test rebuilds it from them and fails on drift. web_composer/
// suggestion_tests.rs replays the same file against Rust.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { rankMentionResults } from '../../../components/enter_message/services/mentionRanking';
import { decodeComposerGhostSuggestion } from '../../composerGhostDecode';
import * as embed from '../../embedSuggestionSearch';
import { createComposerHandlers } from '../composer/composerUnit';
import type { ComposerBinding } from '../composer/composerProtocol';
import { buildSuggestionVectors } from './helpers/suggestionCases';

const VECTORS = resolve(__dirname, '../../../../../../../packages/openmates-rust/src/web_composer/suggestion_ts_vectors.json');

describe('composer suggestion parity vectors (TypeScript side)', () => {
	// contract-test: supporting surface=gui.web assertions=message-input.suggestions.contextual
	it('the TypeScript ranking and validation modules match the committed vectors', () => {
		const fresh = buildSuggestionVectors({ rankMentionResults, decodeComposerGhostSuggestion, embed } as never);
		expect(JSON.parse(JSON.stringify(fresh))).toEqual(JSON.parse(readFileSync(VECTORS, 'utf8')));
	});

	// contract-test: supporting surface=gui.web assertions=message-input.suggestions.contextual
	it('the composer handlers forward the suggestion ops as JSON text', async () => {
		const seen: string[] = [];
		const record = (name: string, answer: unknown) => (input: string) => { seen.push(`${name}:${input}`); return JSON.stringify(answer); };
		const binding = {
			composer_mentions_rank: record('m', [{ index: 1, score: 50 }]),
			composer_saved_embeds_rank: record('s', [0]),
			composer_ghost_validate: record('g', { valid: true }),
		} as unknown as ComposerBinding;
		const handlers = createComposerHandlers(binding);
		const none = undefined as never;
		expect(await handlers.mentionsRank({ query: 'a', limit: 2, candidates: [{ searchTerms: ['a'] }] }, none)).toEqual([{ index: 1, score: 50 }]);
		expect(await handlers.savedEmbedsRank({ query: 'a', limit: 2, entries: [] }, none)).toEqual([0]);
		expect(await handlers.ghostValidate({ value: '{}' }, none)).toEqual({ valid: true });
		expect(seen).toHaveLength(3);
		await expect(Promise.resolve().then(() => handlers.ghostValidate('x' as never, none))).rejects.toMatchObject({ code: 'protocol' });
	});
});
