/**
 * Case tables for the composer suggestion parity vectors (mention ranking,
 * saved-embed ranking, ghost-suggestion validation). Import-free: the real
 * TypeScript modules are passed in so Node type stripping can load this file in
 * generateSuggestionVectors.mjs and vitest can load it in suggestionVectors.test.ts.
 * No provider-key-shaped strings appear in any case.
 */
interface Mention { id: number; searchTerms: string[]; type?: string; score?: number }
interface Saved { embedId: string; title: string; appId: string; savedAt: number; itemValue: Record<string, unknown> }

export interface SuggestionModules {
	rankMentionResults(results: Mention[], query: string, limit: number): Mention[];
	decodeComposerGhostSuggestion(value: string): unknown;
	embed: {
		savedEmbedIndex(state: unknown): { title: string; searchText: string; updatedAt: number; embedId: string }[];
		rankSavedEmbedIndex(index: unknown[], normalized: string, limit: number): { embedId: string }[];
		savedEmbedsToMemoriesLike(items: Saved[]): unknown;
	};
}

const MENTION_POOL: Omit<Mention, 'id'>[] = [
	{ searchTerms: ['gemini', 'gemini-pro', 'pro'], type: 'model' },
	{ searchTerms: ['best', 'best-model'], type: 'model_alias' },
	{ searchTerms: ['mobile preference', 'mobile', 'preference'], type: 'settings_memory_entry' },
	{ searchTerms: ['memories', 'preferences'], type: 'settings_memory' },
	{ searchTerms: ['demo-project', 'demo', 'project'], type: 'project' },
	{ searchTerms: ['demo-docs', 'readme.md'], type: 'project_file' },
	{ searchTerms: ['demo-folder', 'src'], type: 'project_folder' },
	{ searchTerms: ['pro', 'pro-search'], type: 'skill' },
	{ searchTerms: ['istanbul guide', 'i̇stanbul'], type: 'mate' },
	{ searchTerms: ['οδός', 'σας'], type: 'focus_mode' },
	{ searchTerms: [], type: 'model' },
	{ searchTerms: ['pro', 'professional', 'approach'] },
	{ searchTerms: ['🚀 launch', 'launch'], type: 'mate' },
];
const MENTION_QUERIES = ['', 'pro', 'PRO', 'gem', 'best', 'mobile', 'demo', 'DEMO-PROJECT', 'src', 'zzz', 'i̇st', 'σας', 'ΣΑΣ', '🚀', 'a', 'pre'];
const MENTION_LIMITS = [0, 1, 3, 8, 100, -1, -5];

const SAVED: Saved[] = [
	{ embedId: 'e1', appId: 'travel', title: 'Berlin flights', savedAt: 30, itemValue: { origin: 'Berlin', destination: 'Rome' } },
	{ embedId: 'e2', appId: 'travel', title: 'Rome hotel', savedAt: 50, itemValue: { location: 'Rome', provider: 'Example Stays' } },
	{ embedId: 'e3', appId: 'maps', title: '', savedAt: 40, itemValue: { name: 'Gathering spot', address: 'Gathering Street 4' } },
	{ embedId: 'e4', appId: 'maps', title: 'Gathering notes', savedAt: 40, itemValue: { note: 'gathering at six' } },
	{ embedId: 'e5', appId: 'notes', title: 'Café İstanbul', savedAt: 10, itemValue: { text: 'Turkish coffee' } },
	{ embedId: 'e6', appId: 'notes', title: 'Plain', savedAt: 5, itemValue: { text: 'x'.repeat(700), url: 'https://example.invalid/rome' } },
	{ embedId: 'e7', appId: 'notes', title: 'Rome', savedAt: 5, itemValue: { text: 'rome' } },
];
const SAVED_QUERIES = ['rome', 'berlin', 'gathering', 'café', 'i̇stanbul', 'turkish', 'x', 'nothing-here', 'example.invalid', 'six'];
const SAVED_LIMITS = [1, 2, 6, 50, -1];

const GHOST = { sourceMessageId: 'm1', sourceUserMessageId: 'u1', sourceTaskId: 't1' };
const ghost = (patch: Record<string, unknown>) => JSON.stringify({ text: 'Tell me more', ...GHOST, ...patch });
const GHOST_VALUES: string[] = [
	ghost({}), ghost({ extra: { nested: [1, 2] } }), ghost({ text: '' }), ghost({ text: '   ' }), ghost({ text: '﻿' }),
	ghost({ text: '\u0085' }), ghost({ text: '  ' }), ghost({ text: 'a'.repeat(400) }), ghost({ text: 'a'.repeat(401) }),
	ghost({ text: `${'a'.repeat(398)}🚀` }), ghost({ text: `${'a'.repeat(399)}🚀` }),
	ghost({ text: 7 }), ghost({ text: null }), ghost({ sourceMessageId: '' }), ghost({ sourceUserMessageId: 5 }),
	ghost({ sourceTaskId: undefined }), ghost({ sourceTaskId: ' ' }), JSON.stringify({ text: 'x' }), '{}', '[]', 'null', '7', '"text"', 'true',
	'', '{', 'not json', '{"text":"a","text":"b","sourceMessageId":"m","sourceUserMessageId":"u","sourceTaskId":"t"}',
	'{"text":"caf\\u00e9","sourceMessageId":"m","sourceUserMessageId":"u","sourceTaskId":"t"}',
];

export function buildSuggestionVectors(modules: SuggestionModules) {
	const mentionCandidates = MENTION_POOL.map((m, id) => ({ ...m, id }));
	const mentions = [];
	for (const query of MENTION_QUERIES) {
		for (const limit of MENTION_LIMITS) {
			const ranked = modules.rankMentionResults(mentionCandidates, query, limit);
			mentions.push({
				in: { query, limit, candidates: mentionCandidates.map(({ searchTerms, type }) => (type === undefined ? { searchTerms } : { searchTerms, type })) },
				out: ranked.map((r) => ({ index: r.id, score: r.score })),
			});
		}
	}
	const state = modules.embed.savedEmbedsToMemoriesLike(SAVED);
	const index = modules.embed.savedEmbedIndex(state);
	const entries = index.map(({ title, searchText, updatedAt }) => ({ title, searchText, updatedAt }));
	const saved = [];
	for (const raw of SAVED_QUERIES) {
		const query = raw.trim().toLowerCase();
		for (const limit of SAVED_LIMITS) {
			const ranked = modules.embed.rankSavedEmbedIndex(index, query, limit);
			saved.push({ in: { query, limit, entries }, out: ranked.map((r) => index.findIndex((e) => e.embedId === r.embedId)) });
		}
	}
	const ghosts = GHOST_VALUES.map((value) => ({ in: { value }, out: { valid: modules.decodeComposerGhostSuggestion(value) !== null } }));
	return { mentions, saved, ghosts };
}
