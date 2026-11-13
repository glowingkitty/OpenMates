/**
 * Flag-on (VITE_OPENMATES_RUST_CORE) page adapter for the composer code-language
 * and URL-kind operations of the shared Rust core Worker `composer` unit. Loaded
 * only through guarded dynamic imports of async callers (handlePaste,
 * embedHandlers code-file embeds, createEmbedFromUrl), so default builds never
 * bundle it and no synchronous caller gains an await window. There is no
 * TypeScript fallback.
 *
 * Strings crossing to the Worker are made well-formed first (a lone UTF-16
 * surrogate cannot be carried in the Worker's UTF-8 strings), which only affects
 * malformed text.
 */
import { composerCall } from '../../../services/rustCore/composer/composerClient';
import { toWellFormedText } from '../../../services/shareState/anonymousChatPolicy';

/** Rust twin of `detectLanguageFromVSCode` plus `detectLanguageFromContent` for one paste. */
export async function rustDetectLanguages(text: string, vsCodeEditorData: string | null): Promise<{ vsCode: string | null; content: string | null }> {
	return composerCall('languageDetect', { text: toWellFormedText(text), vsCodeEditorData: vsCodeEditorData === null ? null : toWellFormedText(vsCodeEditorData) });
}

/** Rust twin of `detectLanguageFromContent(text)`. */
export async function rustDetectLanguageFromContent(text: string): Promise<string | null> {
	return (await composerCall('languageDetect', { text: toWellFormedText(text) })).content;
}

/** Rust twin of `isGitHubRepoUrl`, `isYouTubeUrl` and `extractYouTubeVideoId` for one URL. */
export async function rustClassifyUrl(url: string): Promise<{ youtube: boolean; githubRepo: boolean; videoId: string | null }> {
	return composerCall('urlClassify', { url: toWellFormedText(url) });
}

/** Kinds of pasted content the composer can turn into an embed. */
export type PastedContentKind = 'text' | 'code' | 'document' | 'sheet';

/** Rust twin of the plain-text to document-HTML formatter (paragraphs, escaped). */
export async function rustPlainTextToHtml(text: string): Promise<string> {
	return composerCall('plainTextToHtml', { text: toWellFormedText(text) });
}
