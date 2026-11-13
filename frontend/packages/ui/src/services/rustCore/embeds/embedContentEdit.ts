/**
 * Page glue of user content edits (`feature.embed-user-edits`, assertions
 * `edit.next-version`, `event.chat-notice`, `event.project-edit-reaches-chat`):
 * the diagram, slides and sheet editors save an edit as the next version
 * through the Worker's `embedEdit` unit (`commitContentRevision`).
 * VITE_OPENMATES_RUST_CORE builds only.
 *
 * This module only picks the save scope from where the editor was opened (the
 * chat, or the Projects workspace) and hands the core the new head content in
 * its stored form (TOON). The core reads the server head, refuses a moved head
 * (`embed_version_conflict`), encrypts, commits and writes the chat's
 * `embed_updated` event: in chat scope into that chat, in Project scope into
 * the embed's own chat when it has one (a Project-only file gets none).
 *
 * Team chats and Team Projects stay on the editors' earlier save path: the
 * core's event write and key handling cover personal accounts only so far.
 */
import type { EmbedEditScope, EmbedRevisionResult } from './embedEditProtocol';
import { commitContentRevision } from './embedEditSession';

/** Where the editor was opened. */
export interface ContentEditPlace {
	chatId?: string | null;
	/** Team of the chat (or the active Team) when the chat is a Team chat. */
	chatTeamId?: string | null;
	projectId?: string | null;
	projectTeamId?: string | null;
}

/** Core save scope of an edit opened at `place`; null when the core does not save it (no place, Team). */
export function contentEditScope(place: ContentEditPlace): EmbedEditScope | null {
	if (place.projectId) return place.projectTeamId ? null : { kind: 'project', project_id: place.projectId };
	if (!place.chatId || place.chatTeamId) return null;
	return { kind: 'chat', chat_id: place.chatId };
}

/** Team of chat `chatId` as the page knows it (its own team, else the active Team), or null. */
export async function chatTeamOf(chatId: string | null | undefined): Promise<string | null> {
	if (!chatId) return null;
	const [{ chatDB }, { activeTeamId }, { get }] = await Promise.all([
		import('../../db'), import('../../../stores/teamStore'), import('svelte/store')
	]);
	const chat = await chatDB.getChat(chatId);
	return chat?.team_id ?? get(activeTeamId) ?? null;
}

/**
 * Save the edit made on version `baseVersion` as version `baseVersion + 1`;
 * `build(version)` returns the new head content object. Afterwards the page's
 * embed cache holds the saved head (content, version, the server's content
 * hash), so the cards, a reopened fullscreen and a reload show the saved
 * version; the cards refresh via `embedUpdated`. Rejects with the core's
 * stable code (`UnitPortError.code`).
 */
export async function saveContentEdit(
	embedId: string,
	scope: EmbedEditScope,
	baseVersion: number,
	build: (version: number) => Record<string, unknown>
): Promise<EmbedRevisionResult> {
	const { encode } = await import('@toon-format/toon');
	const content = encode(build(baseVersion + 1));
	const saved = await commitContentRevision(embedId, scope, baseVersion, content);
	await adoptSavedHead(embedId, scope, content, saved);
	return saved;
}

/** Page embed cache seam (`embedStore`, `embedResolver`, `chatSyncService`); injectable for tests. */
export interface SavedHeadCache {
	update(embedId: string, content: string, version: number, contentHash: string): Promise<boolean>;
	refetch(embedId: string, chatId: string | null): Promise<void>;
	announce(embedId: string, chatId: string | null): void;
}

const pageCache: SavedHeadCache = {
	async update(embedId, content, version, contentHash) {
		const { embedStore } = await import('../../embedStore');
		return (await embedStore.prepareVersionRestoreUpdate(embedId, content, version, contentHash)).updated;
	},
	async refetch(embedId, chatId) {
		const { requestEmbedFromServerOnce } = await import('../../embedResolver');
		await requestEmbedFromServerOnce(embedId, 'user embed version saved', { chatId });
	},
	announce(embedId, chatId) {
		void import('../../chatSyncService').then(({ chatSyncService }) => chatSyncService.dispatchEvent(
			new CustomEvent('embedUpdated', { detail: { embed_id: embedId, chat_id: chatId, status: 'finished' } })));
	}
};

/**
 * Writes the committed head into the page's embed cache. The server read
 * alone is not enough: `request_embed` is suppressed for 10 s after the open
 * that loaded the embed, so the cache (and every reload) kept the old head.
 * An embed the page has not cached yet is read from the server instead.
 */
export async function adoptSavedHead(embedId: string, scope: EmbedEditScope, content: string,
	saved: EmbedRevisionResult, cache: SavedHeadCache = pageCache): Promise<void> {
	const chatId = scope.kind === 'chat' ? scope.chat_id : null;
	if (await cache.update(embedId, content, saved.version, saved.content_hash)) {
		cache.announce(embedId, chatId);
		return;
	}
	await cache.refetch(embedId, chatId);
}
