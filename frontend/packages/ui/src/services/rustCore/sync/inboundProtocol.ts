/**
 * Wire contract of the inbound chat-update decisions of the `sync` unit
 * (web_sync/inbound.rs). Types and constants only, so the Worker-side installer
 * can import it without pulling the page client.
 */
/** Operation to binding export of the inbound decisions. */
export const INBOUND_OPS = {
	draftShell: 'sync_draft_shell',
} as const;

export interface InboundProtocol {
	draftShell: { request: { messagesV: number; chat: Record<string, unknown> }; response: { clear: boolean } };
}
