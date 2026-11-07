/**
 * Flag-on (VITE_OPENMATES_RUST_CORE) page adapter for the composer suggestion
 * operations of the shared Rust core Worker `composer` unit: mention and
 * saved-embed ranking and ghost-suggestion validation. Loaded only through guarded
 * dynamic imports of async callers (searchProjectMentions, searchSavedEmbeds,
 * decryptComposerGhostSuggestion), so default builds never bundle it and no
 * synchronous caller gains an await window. There is no TypeScript fallback.
 *
 * Rust answers indices; the page reorders its own objects. Strings crossing to the
 * Worker are made well-formed first (a lone UTF-16 surrogate cannot be carried in
 * the Worker's UTF-8 strings), which only affects malformed text.
 */
import { composerCall } from '../../../services/rustCore/composer/composerClient';
import type { IndexedSavedEmbed, SavedEmbedSuggestion } from '../../../services/embedSuggestionSearch';
import type { ComposerGhostSuggestion } from '../../../services/composerGhostDecode';
import { toWellFormedText } from '../../../services/shareState/anonymousChatPolicy';
import type { RankableMention } from './mentionRanking';

const wellFormed = toWellFormedText;

/** Rust twin of `rankMentionResults(results, query, limit)`. */
export async function rustRankMentionResults<T extends RankableMention>(results: T[], query: string, limit: number): Promise<T[]> {
	const ranked = await composerCall('mentionsRank', {
		query: wellFormed(query), limit,
		candidates: results.map((r) => ({ searchTerms: r.searchTerms.map(wellFormed), type: r.type })),
	});
	return ranked.map(({ index, score }) => ({ ...results[index], score }));
}

/** Rust twin of `rankSavedEmbedIndex(index, normalizedQuery, limit)`. */
export async function rustRankSavedEmbeds(index: IndexedSavedEmbed[], normalized: string, limit: number): Promise<SavedEmbedSuggestion[]> {
	const kept = await composerCall('savedEmbedsRank', {
		query: wellFormed(normalized), limit,
		entries: index.map((e) => ({ title: wellFormed(e.title), searchText: wellFormed(e.searchText), updatedAt: e.updatedAt })),
	});
	return kept.map((i) => {
		const { searchText: _searchText, ...result } = index[i];
		return result;
	});
}

/** Rust twin of `decodeComposerGhostSuggestion(value)`; the page re-parses the validated text itself. */
export async function rustDecodeComposerGhostSuggestion(value: string): Promise<ComposerGhostSuggestion | null> {
	const { valid } = await composerCall('ghostValidate', { value });
	return valid ? (JSON.parse(value) as ComposerGhostSuggestion) : null;
}
