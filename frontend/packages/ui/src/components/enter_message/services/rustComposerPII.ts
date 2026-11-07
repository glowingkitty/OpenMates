/**
 * Flag-on (VITE_OPENMATES_RUST_CORE) page adapter for the composer PII
 * operations of the shared Rust core Worker `composer` unit. Loaded only through
 * guarded dynamic imports of the async composer paths, so default builds never
 * bundle it. There is no TypeScript fallback: a refused call rejects.
 *
 * Rust returns spans without matched text; this adapter slices the page's own
 * string by the UTF-16 offsets, so no text is copied back out of the Worker.
 */
import type { PIIDetectionOptions, PIIMatch, PIIType } from './piiDetectionService';
import type { WebPIIEntity } from './webPIIMatches';
import type { WebPIIWindow } from './webPIIWindows';
import { composerCall } from '../../../services/rustCore/composer/composerClient';
import type { ComposerDetectOptions, ComposerMatch, ComposerPasteResult } from '../../../services/rustCore/composer/composerProtocol';

function wireOptions(options: PIIDetectionOptions): ComposerDetectOptions {
	return {
		excludedIds: options.excludedIds ? [...options.excludedIds] : undefined,
		disabledCategories: options.disabledCategories ? [...options.disabledCategories] : undefined,
		personalDataEntries: options.personalDataEntries?.map((entry) => ({ ...entry, additionalTexts: entry.additionalTexts ? [...entry.additionalTexts] : undefined })),
	};
}

function withText(text: string, matches: ComposerMatch[]): PIIMatch[] {
	return matches.map((m) => ({
		type: m.type as PIIType, match: text.substring(m.startIndex, m.endIndex),
		startIndex: m.startIndex, endIndex: m.endIndex, placeholder: m.placeholder, id: m.id,
	}));
}

/** Rust twin of `detectPII(text, options)`. */
export async function rustDetectPII(text: string, options: PIIDetectionOptions = {}): Promise<PIIMatch[]> {
	return withText(text, await composerCall('piiDetect', { text, options: wireOptions(options) }));
}

/** Rust twin of `mergeWebPIIMatches(text, entities, options)`. */
export async function rustMergeWebPIIMatches(text: string, entities: WebPIIEntity[], options: PIIDetectionOptions = {}): Promise<PIIMatch[]> {
	// Same 16-hex nonce as the TS path; one per call, generated on the page (no RNG in the Worker).
	const nonce = crypto.randomUUID().replace(/-/g, '').slice(0, 16);
	try {
		return withText(text, await composerCall('piiMergeMatches', { text, entities, options: wireOptions(options), nonce }));
	} catch (error) {
		if ((error as { code?: string }).code === 'invalid_offsets') throw new Error('PII detector returned invalid character offsets');
		throw error;
	}
}

/** Rust twin of `buildWebPIIWindows(text)`. */
export function rustBuildWebPIIWindows(text: string): Promise<WebPIIWindow[]> {
	return composerCall('piiWindows', { text });
}

/** Rust twin of `mergeWebPIIWindowEntities(entities)`. */
export async function rustMergeWebPIIWindowEntities(entities: WebPIIEntity[]): Promise<WebPIIEntity[]> {
	const kept = await composerCall('piiMergeWindowEntities', { entities });
	return kept.map((index) => entities[index]);
}

/** Rust twin of `classifyPastedContent`. */
export function rustClassifyPastedContent(input: {
	text: string; html?: string | null; vsCodeLanguage?: string | null; detectedLanguage?: string | null;
}): Promise<ComposerPasteResult> {
	return composerCall('pasteClassify', {
		text: input.text, html: input.html ?? undefined,
		vsCodeLanguage: input.vsCodeLanguage ?? undefined, detectedLanguage: input.detectedLanguage ?? undefined,
	});
}

/** Rust twin of `replacePIIWithPlaceholders(text, matches)`. */
export function rustReplacePIIWithPlaceholders(text: string, matches: PIIMatch[]): Promise<string> {
	return composerCall('piiReplace', {
		text, matches: matches.map((m) => ({ startIndex: m.startIndex, endIndex: m.endIndex, placeholder: m.placeholder })),
	});
}
