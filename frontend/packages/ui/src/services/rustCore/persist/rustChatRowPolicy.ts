/**
 * Flag-on (VITE_OPENMATES_RUST_CORE) chat-row decisions: the page adapter over the
 * shared Rust core Worker `persist` unit. Loaded only through db/chatRowDecisions.ts,
 * so default builds never bundle it.
 *
 * Rust (packages/openmates-rust/src/web_persist/chat_policy.rs) decides stored
 * defaults, the keyless draft-only sync shell, candidate keys and the draft /
 * Team draft-intent merges. Only the fields a decision reads cross the Worker
 * boundary; merges answer a patch the page applies to the row it holds, so no
 * chat row is ever rebuilt from JSON. There is no TypeScript fallback.
 *
 * spec: specifications/architecture/storage-lifecycle#storage.client.shared-policy-existing-adapters
 */
import type { ChatRowDecisions } from '../../db/chatRowDecisions';
import { persistCall } from './persistUnitClient';

type Row = Record<string, unknown>;

/** The listed fields of `row` that are present (a missing field is JS `undefined`). */
function pick(row: object, fields: readonly string[]): Row {
	const source = row as Row;
	const out: Row = {};
	for (const field of fields) if (source[field] !== undefined) out[field] = source[field];
	return out;
}

const DEFAULT_FIELDS = ['draft_v', 'title_v', 'messages_v', 'last_edited_overall_timestamp', 'updated_at', 'created_at'] as const;
const SHELL_FIELDS = [
	'team_id', 'chat_visibility', 'is_anonymous', 'anonymous_encrypted_chat_key', 'is_shared', 'is_shared_by_others',
	'encrypted_chat_key', 'encrypted_title', 'messages_v', 'draft_v', 'encrypted_draft_md',
] as const;
const MERGE_FIELDS = ['chat_id', 'team_id', 'draft_v', 'cleared_draft_v', 'updated_at'] as const;
const TEAM_FIELDS = ['team_id', 'team_draft_pending_sync', 'encrypted_draft_md', 'draft_v', 'cleared_draft_v'] as const;

export const rustChatRowDecisions: ChatRowDecisions = {
	deferred: true,
	chatDefaults: (chat, now) => persistCall('chatDefaults', { chat: pick(chat, DEFAULT_FIELDS), now }),
	keylessDraftOnly: async (chat, existing) => (await persistCall('keylessDraftOnly', {
		chat: pick(chat, SHELL_FIELDS), existing: existing ? pick(existing, SHELL_FIELDS) : null,
	})).expected,
	candidateKeys: async (existing, blob) => (await persistCall('candidateKeys', { existing, blob })).updated,
	draftMerge: ({ chatId, current, fields, missingRow }) => persistCall('draftMerge', {
		chatId,
		current: current ? pick(current, MERGE_FIELDS) : null,
		fields: Object.fromEntries(Object.entries(fields).filter(([, value]) => value !== undefined)) as typeof fields,
		missingRow: missingRow ? pick(missingRow, MERGE_FIELDS) : null,
		undefinedKeys: Object.entries(fields).filter(([, value]) => value === undefined).map(([key]) => key),
	}),
	teamDraftIntent: ({ chat, teamId, pending, expected }) => persistCall('teamDraftIntent', {
		chat: chat ? pick(chat, TEAM_FIELDS) : null, teamId, pending, expected,
	}),
};
