/**
 * View glue for message-scoped image versions
 * (`images-generate.revision.message-shows-its-version`).
 *
 * A generated-image card inside a chat message shows the version valid at
 * that message. The Rust core decides the version and opens its content
 * (services/rustCore/embeds/messageEmbedVersion.ts); this module only finds the
 * card's message, turns the result into what a card renders and carries the
 * version a card was opened at to the fullscreen view.
 */
import {
	EMBED_VERSIONS_ENABLED,
	embedContentAtVersion,
	embedVersionForMessage,
	messageIdOf,
	publishedChatId
} from '../../../services/rustCore/embeds/messageEmbedVersion';
import { decodeToonContent } from '../../../services/embedResolver';

/** What a card shows: `content` is null when the message shows the stored head. */
export interface ImageVersionView {
	version: number;
	headVersion: number;
	/** The pinned version is newer than this device's head: it arrives with the head. */
	waitingForHead: boolean;
	content: Record<string, unknown> | null;
}

const MESSAGE_LOOKUP_FRAMES = 12;

/** Badge text for a card: only when the image has more than one version. */
export function versionBadgeLabel(version: number | undefined, headVersion: number | undefined): string | null {
	if (!version || !headVersion || headVersion <= 1) return null;
	return `v${version}`;
}

/**
 * The message id of a card. Node views are attached to the message after they
 * mount, so the lookup waits a few frames; null means "not in a chat message"
 * (Apps workspace, previews), where the head is the right picture.
 */
export async function findMessageId(element: Element, frames = MESSAGE_LOOKUP_FRAMES): Promise<string | null> {
	if (!EMBED_VERSIONS_ENABLED) return null;
	for (let frame = 0; frame < frames; frame++) {
		const id = messageIdOf(element);
		if (id) return id;
		await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
	}
	return messageIdOf(element);
}

/**
 * Resolve what a card in message `messageId` shows for `embedId`; null outside a
 * published chat. `headContent`: also open the head's content when the message
 * shows the head (a card that waited for the head holds an older version's data).
 */
export async function resolveImageVersionView(messageId: string, embedId: string, chatId: string | null,
	options: { headContent?: boolean } = {}): Promise<ImageVersionView | null> {
	const resolved = await embedVersionForMessage(messageId, embedId);
	if (!resolved) return null;
	const { version, headVersion } = resolved;
	if (version > headVersion) return { version, headVersion, waitingForHead: true, content: null };
	if (version === headVersion && !options.headContent) return { version, headVersion, waitingForHead: false, content: null };
	const lookupChat = chatId ?? publishedChatId();
	if (!lookupChat) return null;
	const content = await decodeToonContent(await embedContentAtVersion(lookupChat, embedId, version));
	if (!content) throw new Error('embed_version_content_undecodable');
	return { version, headVersion, waitingForHead: false, content };
}

/** Content of version `version` for a view that is not tied to a message (fullscreen timeline). */
export async function imageContentAtVersion(chatId: string | null, embedId: string, version: number): Promise<Record<string, unknown>> {
	const lookupChat = chatId ?? publishedChatId();
	if (!lookupChat) throw new Error('embed_version_chat_unknown');
	const content = await decodeToonContent(await embedContentAtVersion(lookupChat, embedId, version));
	if (!content) throw new Error('embed_version_content_undecodable');
	return content;
}

const fullscreenVersions = new Map<string, number>();

/** A card opens fullscreen: the fullscreen starts at the version this card shows. */
export function rememberFullscreenVersion(embedId: string, version: number | undefined): void {
	if (version) fullscreenVersions.set(embedId, version);
	else fullscreenVersions.delete(embedId);
}

/** The version a fullscreen of `embedId` should start at (consumed once). */
export function takeFullscreenVersion(embedId: string | undefined): number | undefined {
	if (!embedId) return undefined;
	const version = fullscreenVersions.get(embedId);
	fullscreenVersions.delete(embedId);
	return version;
}
