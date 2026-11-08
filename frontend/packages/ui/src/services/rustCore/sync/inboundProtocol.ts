/**
 * Wire contract of the inbound chat-update decisions of the `sync` unit
 * (web_sync/inbound.rs). Types and constants only, so the Worker-side installer
 * can import it without pulling the page client.
 */
/** First failed admission check of a title/draft frame, or null when it is admitted. */
export type InboundFrameInvalid = 'chat_id' | 'data' | 'versions' | null;

/** Operation to binding export of the inbound decisions. */
export const INBOUND_OPS = {
	draftShell: 'sync_draft_shell',
	updateFrame: 'sync_update_frame',
	draftApply: 'sync_draft_apply',
	messagePrep: 'sync_message_prep',
	metadataVersions: 'sync_metadata_versions',
	draftDeleted: 'sync_draft_deleted',
	messagesVersion: 'sync_messages_version',
} as const;

/** Version counters of a version-wins plan (web_sync/versions.rs); absent = `undefined`. */
type VersionRecord = Partial<Record<'messages_v' | 'metadata_v' | 'title_v' | 'draft_v' | 'cleared_draft_v', unknown>>;

/** Decision fields of one synced message (absent = `undefined`); `null` marks a failed JSON parse. */
export interface MessagePrepEntry {
	message_id?: unknown;
	client_message_id?: unknown;
	id?: unknown;
	chat_id?: unknown;
	role?: unknown;
	status?: unknown;
	queue_dispatch_status?: unknown;
	queue_dispatch_mode?: unknown;
}

/** Storage plan of one synced message (web_sync/message_prep.rs). */
export type MessagePrepPlan =
	| { skip: 'parse' | 'id' }
	| {
		skip: null;
		idKey: 'message_id' | 'client_message_id' | 'id';
		chatOwn: boolean;
		roleOwn: boolean;
		statusOwn: boolean;
		queue: 'paused' | 'processing' | 'queued' | 'none';
	};

export interface InboundProtocol {
	draftShell: { request: { messagesV: number; chat: Record<string, unknown> }; response: { clear: boolean } };
	updateFrame: { request: { kind: 'title' | 'draft'; payload: unknown }; response: { invalid: InboundFrameInvalid } };
	draftApply: {
		request: { local: Record<string, unknown>; incomingDraftV: number; deletion: boolean };
		response: { stale: boolean; clearedDraftV: number | null };
	};
	messagePrep: {
		request: { mode: 'phased' | 'batch'; messages: (MessagePrepEntry | null)[] };
		response: { plans: MessagePrepPlan[] };
	};
	metadataVersions: {
		request: { local: VersionRecord; versions?: VersionRecord };
		response: { acceptsRevision: boolean; apply: ('messages_v' | 'metadata_v' | 'title_v' | 'draft_v')[] };
	};
	draftDeleted: {
		request: { local: VersionRecord; draftV?: number };
		response: { ignore: 'versionless' | 'stale' | null; clearedDraftV: number | null };
	};
	messagesVersion: {
		request: { local?: number | null; candidates: number[] };
		response: { messagesV: number; advanced: boolean };
	};
}
