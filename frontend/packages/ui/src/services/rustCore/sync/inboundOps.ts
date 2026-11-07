/**
 * Inbound chat-update decisions of the shared Rust core Worker `sync` unit
 * (web_sync/inbound.rs). Loaded only by the guarded branches of
 * chatInboundDecisions.ts, so default builds never bundle it. The ops are
 * merged into SYNC_OPS (syncProtocol.ts).
 */
import type { Chat } from '../../../types/chat';
import { syncCall } from './syncUnitClient';

export { INBOUND_OPS, type InboundProtocol } from './inboundProtocol';

export function draftShell(chat: Chat, messagesV: number) {
	return syncCall('draftShell', {
		messagesV,
		chat: {
			messages_v: chat.messages_v,
			encrypted_draft_md: chat.encrypted_draft_md,
			encrypted_draft_preview: chat.encrypted_draft_preview,
		},
	});
}
