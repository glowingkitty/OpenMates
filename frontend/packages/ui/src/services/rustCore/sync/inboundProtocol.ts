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
} as const;

export interface InboundProtocol {
	draftShell: { request: { messagesV: number; chat: Record<string, unknown> }; response: { clear: boolean } };
	updateFrame: { request: { kind: 'title' | 'draft'; payload: unknown }; response: { invalid: InboundFrameInvalid } };
	draftApply: {
		request: { local: Record<string, unknown>; incomingDraftV: number; deletion: boolean };
		response: { stale: boolean; clearedDraftV: number | null };
	};
}
