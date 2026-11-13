/**
 * Flag-on (VITE_OPENMATES_RUST_CORE) "hide chat" flow shared by Chat.svelte and
 * chatMenuActionService.ts. Rust (chatState `hiddenPlanHide`) decides whether the
 * chat needs unlock, is already hidden, has no key or is wrapped with the combined
 * secret; this module only persists the new wrapper, caches the key and syncs the
 * `encrypted_chat_metadata` key-update frame (built by `hiddenKeyUpdate`). Loaded
 * only by guarded branches, so default builds never bundle it. No TS fallback.
 * spec: specifications/architecture/sync#sync.client.shared-rust-policy
 */
import type { Chat } from '../../../types/chat';
import { chatDB } from '../../db';
import { chatKeyManager } from '../../encryption/ChatKeyManager';
import { chatListCache } from '../../chatListCache';
import { rustHiddenPlanHide } from './rustHiddenChat';

export type RustHideResult = 'hidden' | 'already_hidden' | 'missing_key' | 'needs_unlock';

/** Plans and applies hiding `chat`; never touches the UI. */
export async function rustHideChat(chat: Chat): Promise<RustHideResult> {
	const cached = await chatKeyManager.getKey(chat.chat_id);
	const plan = await rustHiddenPlanHide(cached ?? null, chat.encrypted_chat_key ?? null);
	if (plan.plan !== 'hide') return plan.plan;
	if (plan.decryptedChatKey) chatDB.setChatKey(chat.chat_id, plan.decryptedChatKey);
	await chatDB.updateChat({ ...chat, encrypted_chat_key: plan.encryptedChatKey });
	chatListCache.markDirty();
	const { chatSyncService } = await import('../../chatSyncService');
	await chatSyncService.sendUpdateEncryptedChatKey(chat.chat_id, plan.encryptedChatKey);
	return 'hidden';
}
