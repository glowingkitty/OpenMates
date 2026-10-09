import { isPublicChat } from '../demo_chats/convertToChat';
import type { Chat } from '../types/chat';
import { isAnonymousChatId } from './anonymousChatIds';

type ShareChat = Pick<Chat, 'chat_id' | 'is_anonymous' | 'is_incognito' | 'is_shared_by_others' | 'encrypted_chat_key' | 'anonymous_encrypted_chat_key'>;

/** Tab-local chats have no server transcript a share recipient could open. */
export function canShareChat(chat: ShareChat | null | undefined, isAuthenticated: boolean): boolean {
  if (!chat?.chat_id || chat.is_incognito || chat.is_anonymous || chat.anonymous_encrypted_chat_key) return false;
  // Signup promotion keeps the ID but replaces the tab wrapper with an account
  // key. A recipient of that promoted chat may only have the original share URL.
  if (isAnonymousChatId(chat.chat_id) && !chat.encrypted_chat_key && !chat.is_shared_by_others) return false;
  return isPublicChat(chat.chat_id) || !!chat.is_shared_by_others || isAuthenticated;
}
