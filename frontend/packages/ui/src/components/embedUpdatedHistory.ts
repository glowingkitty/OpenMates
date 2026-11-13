/**
 * Chat-history placement of folded `embed_updated` system events
 * (`feature.embed-user-edits`, `embed-user-edits.event.chat-notice`,
 * `.event.collapse`; VITE_OPENMATES_RUST_CORE builds only).
 *
 * The Rust core (`embed_group_updated_events`, through the shared Worker's
 * `embedEdit` unit) validates the events and folds the runs. This module only
 * builds its input rows and says where each folded run is drawn: at the newest
 * message of the run; the other messages of the run are hidden.
 */
import type { EmbedChatItem, EmbedEventRow } from '../services/rustCore/embeds/embedEditProtocol';
import type { EmbedUpdatedGroup } from './embedUpdatedGroup';

/** The history fields this module reads. */
export interface EmbedHistoryMessage {
	id: string;
	role: string;
	content: string;
}

/** Cheap pre-check only; the core validates the event. */
export function isEmbedUpdatedCandidate(message: EmbedHistoryMessage): boolean {
	return message.role === 'system' && message.content.includes('"embed_updated"');
}

/** Core input rows in history order; only candidate rows carry their content. */
export function embedEventRows(messages: EmbedHistoryMessage[]): EmbedEventRow[] {
	return messages.map((message) => ({
		message_id: message.id,
		role: message.role,
		content: isEmbedUpdatedCandidate(message) ? message.content : ''
	}));
}

/** Change key: re-fold only when the candidate rows or their positions change. */
export function embedUpdatedCandidateKey(messages: EmbedHistoryMessage[]): string {
	const parts: string[] = [];
	messages.forEach((message, index) => {
		if (isEmbedUpdatedCandidate(message)) parts.push(`${message.id}@${index}:${message.content.length}`);
	});
	return parts.join('|');
}

export interface EmbedUpdatedPlacement {
	/** Folded run drawn at this message id (its newest message). */
	shownAt: Record<string, EmbedUpdatedGroup>;
	/** Older message ids of the runs: not drawn. */
	hidden: Set<string>;
}

/** Where the core's folded runs are drawn. */
export function placeEmbedUpdatedGroups(items: EmbedChatItem[]): EmbedUpdatedPlacement {
	const shownAt: Record<string, EmbedUpdatedGroup> = {};
	const hidden = new Set<string>();
	for (const item of items) {
		if (item.kind !== 'embed_updated') continue;
		const { kind: _kind, ...group } = item;
		const ids = group.message_ids;
		const last = ids[ids.length - 1];
		if (!last) continue;
		shownAt[last] = group;
		for (const id of ids.slice(0, -1)) hidden.add(id);
	}
	return { shownAt, hidden };
}
