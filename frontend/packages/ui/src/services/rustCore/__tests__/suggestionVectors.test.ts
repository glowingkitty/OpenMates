// Page-side handler forwarding for the shared Rust composer suggestion helpers. The
// committed vectors (packages/openmates-rust/src/web_composer/suggestion_ts_vectors.json)
// are replayed against Rust by web_composer/suggestion_tests.rs.
import { describe, expect, it } from 'vitest';
import { createComposerHandlers } from '../composer/composerUnit';
import type { ComposerBinding } from '../composer/composerProtocol';

describe('composer suggestion handlers', () => {
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
