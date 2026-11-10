/**
 * frontend/packages/ui/src/components/embeds/slides/slidesDeckVersion.ts
 *
 * Saves a manually edited deck as the next version of its deck embed. The markup
 * is the Rust core's serialised deck (always normaliser output, so the stored head
 * matches what the backend normaliser produces for assistant edits). The save is
 * the shared client-authored revision commit (`embedUserRevision.ts`): one atomic
 * server commit checked against the head revision and stored content hash, and
 * the local cache is written only after the server receipt. A stale edit is
 * refused (`conflict`) instead of overwriting the newer head. A Project deck keeps
 * the Project revision path (`commitEmbedContentRevision`).
 */
import { commitEmbedUserRevision } from '../../../services/embedUserRevision';
import { commitEmbedContentRevision, isHeadPersisted, type EmbedVersionContext } from '../../../services/embedDiffStore';
import type { DeckAspect } from '../../../services/rustCore/deckDocument/deckDocumentTypes';

/** What the editor hands over on Done: the core's markup and its deck facts. */
export interface EditedDeck {
	markup: string;
	title: string;
	aspect: DeckAspect;
	slideCount: number;
}

/** The deck version the edit was made on. */
export interface DeckHead {
	embedId: string;
	version: number;
	markup: string;
	/** Decoded embed content of that version (kept fields: embed_ref, app/skill ids …). */
	content: Record<string, unknown>;
}

export type DeckSaveResult = { saved: false } | { saved: true; version: number };

/** Stored TOON fields of a deck version, as `deck_embed_content` writes them on the server. */
export function deckVersionContent(
	content: Record<string, unknown>,
	deck: Omit<EditedDeck, 'markup'>,
	markup: string,
	version: number
): Record<string, unknown> {
	return {
		...content,
		slides_markup: markup,
		title: deck.title,
		slide_count: deck.slideCount,
		aspect: deck.aspect,
		version_number: version
	};
}

/**
 * Writes `edited` as version `head.version + 1`. An unchanged deck writes nothing.
 * Errors propagate so the editor can keep the edits open with a retry: a conflict
 * (the deck changed elsewhere), a server rejection or a lost confirmation is never
 * a saved version, and nothing is queued for a later replay.
 */
export async function saveEditedDeck(
	head: DeckHead,
	edited: EditedDeck,
	context: EmbedVersionContext
): Promise<DeckSaveResult> {
	if (edited.markup === head.markup) return { saved: false };
	if (context.projectId) return saveProjectDeck(head, edited, context);
	if (!context.chatId) throw new Error('A deck edit needs its chat or Project');
	const result = await commitEmbedUserRevision({
		embedId: head.embedId,
		chatId: context.chatId,
		current: { ...head.content, version_number: head.version },
		sourceField: 'slides_markup',
		originalSource: head.markup,
		editedSource: edited.markup,
		noun: 'deck',
		// The server stores sha256(slides_markup) as the head hash; the cached head
		// hash is that stored value and is sent as the compare-and-swap base.
		expectedHash: 'stored-head',
		buildContent: (markup, version) => deckVersionContent(head.content, edited, markup, version)
	});
	return { saved: true, version: result.version };
}

/** A Project deck keeps the Project revision path (Project-linked embeds are refused by the chat commit). */
async function saveProjectDeck(head: DeckHead, edited: EditedDeck, context: EmbedVersionContext): Promise<DeckSaveResult> {
	const result = await commitEmbedContentRevision(head.embedId, edited.markup, {
		currentVersion: head.version,
		currentContent: head.markup,
		projectId: context.projectId,
		teamId: context.teamId,
		buildRestoredContent: (markup, version) => deckVersionContent(head.content, edited, markup, version)
	});
	if (!isHeadPersisted(result.head)) {
		const code = 'failure_code' in result.head && result.head.failure_code ? `: ${result.head.failure_code}` : '';
		throw new Error(`Deck version ${result.version_number} was not saved on the server (${result.head.status}${code})`);
	}
	return { saved: true, version: result.version_number };
}
