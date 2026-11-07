/**
 * `composer` unit protocol of the shared Rust core Worker (unitPort.ts wire v1).
 *
 * The message composer's non-UI logic (paste classification, PII detection,
 * redaction, restore, known-original rewrite, local-model span merge, mention and
 * saved-embed ranking, ghost-suggestion validation) runs in
 * shared Rust (packages/openmates-rust/src/web_composer/*.rs). TipTap and the
 * editor DOM stay in Svelte. Matches carry no matched text: the page slices its
 * own string by the UTF-16 offsets. The unit holds no account state and does no IO.
 */
import type { UnitProtocol } from '../host/unitPort';

export interface ComposerPersonalEntry {
	id: string; textToHide?: string; replaceWith: string; additionalTexts?: string[]; type?: string;
}
export interface ComposerDetectOptions {
	excludedIds?: string[]; disabledCategories?: string[]; personalDataEntries?: ComposerPersonalEntry[];
}
/** A detected span without its text; `text.substring(startIndex, endIndex)` is the match. */
export interface ComposerMatch { type: string; startIndex: number; endIndex: number; placeholder: string; id: string }
export interface ComposerMapping { placeholder: string; original: string; type?: string }
export interface ComposerModelEntity { label: string; original: string; start: number; end: number; confidence: number }
export interface ComposerPasteResult { kind: string; reason: string; sheetMarkdown?: string; documentHtml?: string }

export interface ComposerUnitProtocol extends UnitProtocol {
	pasteClassify: { request: { text: string; html?: string; vsCodeLanguage?: string; detectedLanguage?: string }; response: ComposerPasteResult };
	plainTextToHtml: { request: { text: string }; response: string };
	piiDetect: { request: { text: string; options?: ComposerDetectOptions }; response: ComposerMatch[] };
	piiReplace: { request: { text: string; matches: { startIndex: number; endIndex: number; placeholder: string }[] }; response: string };
	piiRestore: { request: { text: string; mappings: ComposerMapping[] }; response: string };
	piiReplaceOriginals: { request: { text: string; mappings: ComposerMapping[] }; response: string };
	piiFindRestored: {
		request: { text: string; mappings: ComposerMapping[] };
		response: { startIndex: number; endIndex: number; label: string; type: string }[];
	};
	piiSummary: { request: { types: string[] }; response: string };
	piiRewrite: {
		request: { markdown: string; mappings: ComposerMapping[]; excludedOriginals?: string[]; excludedPlaceholders?: string[] };
		response: { markdown: string; applied: number[] };
	};
	piiWindows: { request: { text: string }; response: { start: number; end: number }[] };
	piiMergeWindowEntities: { request: { entities: ComposerModelEntity[] }; response: number[] };
	piiMergeMatches: {
		request: { text: string; entities: ComposerModelEntity[]; options?: ComposerDetectOptions; nonce: string };
		response: ComposerMatch[];
	};
	/** Candidates are indexed by the caller; the answer is indices (and scores), never text. */
	mentionsRank: {
		request: { query: string; limit: number; candidates: { searchTerms: string[]; type?: string }[] };
		response: { index: number; score: number }[];
	};
	savedEmbedsRank: {
		request: { query: string; limit: number; entries: { title: string; searchText: string; updatedAt: number }[] };
		response: number[];
	};
	ghostValidate: { request: { value: string }; response: { valid: boolean } };
}

/** Worker module exports (snake_case, JSON text) of browser_composer.rs. */
export interface ComposerBinding {
	composer_paste_classify(input: string): string;
	composer_plain_text_to_html(input: string): string;
	composer_pii_detect(input: string): string;
	composer_pii_replace(input: string): string;
	composer_pii_restore(input: string): string;
	composer_pii_replace_originals(input: string): string;
	composer_pii_find_restored(input: string): string;
	composer_pii_summary(input: string): string;
	composer_pii_rewrite(input: string): string;
	composer_pii_windows(input: string): string;
	composer_pii_merge_window_entities(input: string): string;
	composer_pii_merge_matches(input: string): string;
	composer_mentions_rank(input: string): string;
	composer_saved_embeds_rank(input: string): string;
	composer_ghost_validate(input: string): string;
}

const BINDING_EXPORTS: readonly (keyof ComposerBinding)[] = [
	'composer_paste_classify', 'composer_plain_text_to_html', 'composer_pii_detect', 'composer_pii_replace',
	'composer_pii_restore', 'composer_pii_replace_originals', 'composer_pii_find_restored', 'composer_pii_summary',
	'composer_pii_rewrite', 'composer_pii_windows', 'composer_pii_merge_window_entities', 'composer_pii_merge_matches',
	'composer_mentions_rank', 'composer_saved_embeds_rank', 'composer_ghost_validate',
];

export function isComposerBinding(value: unknown): value is ComposerBinding {
	if (typeof value !== 'object' || value === null) return false;
	const binding = value as Record<string, unknown>;
	return BINDING_EXPORTS.every((name) => typeof binding[name] === 'function');
}
