/**
 * Executes chat menu actions (download, copy, hide, pin, read status, delete,
 * projects, open in new tab) for a single chat outside the sidebar list.
 * Used by the welcome-screen card context menu and the fullscreen chat More
 * menu so both behave identically. Sidebar rows keep their own handlers in
 * Chat.svelte because they also drive list selection state.
 */
import { get } from 'svelte/store';

import type { Chat } from '../types/chat';
import type { ChatMenuAction } from '../components/chats/chatMenuItems';
import { DEMO_CHATS, getDemoMessages, isPublicChat } from '../demo_chats';
import { authStore } from '../stores/authStore';
import { notificationStore } from '../stores/notificationStore';
import { userProfile } from '../stores/userProfile';
import { chatDebugStore } from '../stores/chatDebugStore';
import { chatDB } from './db';
import { chatKeyManager } from './encryption/ChatKeyManager';
import { chatSyncService } from './chatSyncService';
import { chatListCache } from './chatListCache';
import { copyChatToClipboard } from './chatExportService';
import { downloadChatAsZip } from './zipExportService';
import { requestChatProjectPicker } from './chatProjectService';

/** Local UI follow-ups the caller should apply after an action. */
export interface ChatMenuActionResult {
  removedChatIds?: string[];
  updatedChat?: Chat;
}

async function loadMessages(chat: Chat) {
  return isPublicChat(chat.chat_id) ? getDemoMessages(chat.chat_id, DEMO_CHATS) : await chatDB.getMessagesForChat(chat.chat_id);
}

async function notifyListChanged(detail: Record<string, unknown>): Promise<void> {
  const { LOCAL_CHAT_LIST_CHANGED_EVENT } = await import('./drafts/draftConstants');
  window.dispatchEvent(new CustomEvent(LOCAL_CHAT_LIST_CHANGED_EVENT, { detail }));
}

async function setPinned(chat: Chat, pinned: boolean): Promise<ChatMenuActionResult> {
  const updatedChat = { ...chat, pinned };
  await chatDB.updateChat(updatedChat);
  chatListCache.markDirty();
  await notifyListChanged({ chat_id: chat.chat_id, pinned });
  const { webSocketService } = await import('./websocketService');
  if (webSocketService.isConnected()) {
    webSocketService.sendMessage('update_chat', { chat_id: chat.chat_id, pinned });
  }
  return { updatedChat };
}

async function setUnreadCount(chat: Chat, unreadCount: 0 | 1): Promise<ChatMenuActionResult> {
  const { unreadMessagesStore } = await import('../stores/unreadMessagesStore');
  unreadMessagesStore.clearUnread(chat.chat_id);
  if (unreadCount) unreadMessagesStore.incrementUnread(chat.chat_id);
  const updatedChat = { ...chat, unread_count: unreadCount };
  await chatDB.updateChat(updatedChat);
  chatListCache.markDirty();
  await notifyListChanged({ chat_id: chat.chat_id, unread_count: unreadCount });
  await chatSyncService.sendChatReadStatus(chat.chat_id, unreadCount);
  return { updatedChat };
}

async function deleteChat(chat: Chat): Promise<ChatMenuActionResult> {
  // Demo/example chats are hidden via the user profile instead of deleted.
  if (isPublicChat(chat.chat_id)) {
    if (!get(authStore).isAuthenticated) {
      notificationStore.error('Please sign up to customize your experience');
      return {};
    }
    const currentHidden = get(userProfile).hidden_demo_chats || [];
    if (currentHidden.includes(chat.chat_id)) return {};
    const updatedHidden = [...currentHidden, chat.chat_id];
    userProfile.update(profile => ({ ...profile, hidden_demo_chats: updatedHidden }));
    const { userDB } = await import('./userDB');
    await userDB.updateUserData({ hidden_demo_chats: updatedHidden });
    notificationStore.success('Chat hidden successfully');
    return { removedChatIds: [chat.chat_id] };
  }
  // Mirrors Chat.svelte handleDeleteChat: optimistic local delete, then server.
  const descendants = await chatDB.getChatDescendantIds(chat.chat_id);
  const allIds = [chat.chat_id, ...descendants];
  for (const id of allIds) {
    await chatDB.deleteChat(id);
    chatSyncService.dispatchEvent(new CustomEvent('chatDeleted', { detail: { chat_id: id } }));
    try {
      await chatSyncService.sendDeleteChat(id);
    } catch (sendError) {
      console.warn('[ChatMenuAction] Failed to send delete to server, queueing for reconnect:', id, sendError);
      const { addPendingChatDeletion } = await import('./pendingChatDeletions');
      addPendingChatDeletion(id);
    }
  }
  notificationStore.success('Chat deleted');
  return { removedChatIds: allIds };
}

async function hideChat(chat: Chat): Promise<ChatMenuActionResult> {
  const { hiddenChatService } = await import('./hiddenChatService');
  if (!hiddenChatService.isUnlocked()) {
    window.dispatchEvent(new CustomEvent('showOverscrollUnlockForHide', { detail: { chatId: chat.chat_id } }));
    return {};
  }
  let chatKey = await chatKeyManager.getKey(chat.chat_id);
  if (!chatKey && chat.encrypted_chat_key) {
    const result = await hiddenChatService.tryDecryptChatKey(chat.encrypted_chat_key);
    if (result.chatKey) {
      chatKey = result.chatKey;
      chatDB.setChatKey(chat.chat_id, chatKey);
      if (result.isHidden) {
        notificationStore.success('Chat is already hidden');
        return {};
      }
    }
  }
  if (!chatKey) {
    notificationStore.error('Failed to hide chat. Chat key not found.');
    return {};
  }
  const encryptedChatKey = await hiddenChatService.encryptChatKeyWithCombinedSecret(chatKey);
  if (!encryptedChatKey) {
    notificationStore.error('Failed to hide chat. Encryption failed.');
    return {};
  }
  await chatDB.updateChat({ ...chat, encrypted_chat_key: encryptedChatKey });
  chatListCache.markDirty();
  await chatSyncService.sendUpdateEncryptedChatKey(chat.chat_id, encryptedChatKey);
  try {
    await chatDB.hideNewChatSuggestionsForChat(chat.chat_id);
  } catch (suggestionError) {
    console.warn('[ChatMenuAction] Could not hide new-chat suggestions for hidden chat', suggestionError);
  }
  window.dispatchEvent(new CustomEvent('chatHidden', { detail: { chat_id: chat.chat_id } }));
  notificationStore.success('Chat hidden successfully');
  return { removedChatIds: [chat.chat_id] };
}

async function unhideChat(chat: Chat): Promise<ChatMenuActionResult> {
  const { hiddenChatService } = await import('./hiddenChatService');
  if (!hiddenChatService.isUnlocked()) {
    notificationStore.error('Please unlock hidden chats first to unhide this chat.');
    return {};
  }
  if (!(await hiddenChatService.unhideChat(chat.chat_id))) {
    notificationStore.error('Failed to unhide chat.');
    return {};
  }
  try {
    await chatDB.unhideNewChatSuggestionsForChat(chat.chat_id);
  } catch (suggestionError) {
    console.warn('[ChatMenuAction] Could not restore new-chat suggestions for unhidden chat', suggestionError);
  }
  chatListCache.markDirty();
  window.dispatchEvent(new CustomEvent('chatUnhidden', { detail: { chat_id: chat.chat_id } }));
  notificationStore.success('Chat unhidden successfully');
  return {};
}

const FAILURE_MESSAGES: Partial<Record<ChatMenuAction, string>> = {
  download: 'Download failed',
  copy: 'Copy failed',
  delete: 'Failed to delete chat',
  hide: 'Failed to hide chat',
  unhide: 'Failed to unhide chat',
  pin: 'Failed to pin chat',
  unpin: 'Failed to unpin chat',
  markUnread: 'Failed to mark chat as unread',
  markRead: 'Failed to mark chat as read',
};

/**
 * Run one chat action. Must be called directly from the user gesture so
 * `openNewTab` is not blocked as a popup. Failures are reported to the user
 * via notifications and logged; the returned result is then empty.
 */
export async function runChatMenuAction(action: ChatMenuAction, chat: Chat): Promise<ChatMenuActionResult> {
  if (action === 'openNewTab') {
    window.open(`${window.location.origin}/#chat-id=${encodeURIComponent(chat.chat_id)}`, '_blank', 'noopener,noreferrer');
    return {};
  }
  if (action === 'addToProject' || action === 'createProject' || action === 'moveToProject') {
    requestChatProjectPicker([chat], action === 'createProject', action === 'moveToProject' ? 'move' : 'add');
    return {};
  }
  if (action === 'toggleDebug') {
    await chatDebugStore.toggle({ chatId: chat.chat_id });
    return {};
  }
  try {
    switch (action) {
      case 'download':
        await downloadChatAsZip(chat, await loadMessages(chat));
        notificationStore.success('Chat downloaded successfully');
        return {};
      case 'copy':
        await copyChatToClipboard(chat, await loadMessages(chat));
        notificationStore.success('Chat copied to clipboard');
        return {};
      case 'delete': return await deleteChat(chat);
      case 'hide': return await hideChat(chat);
      case 'unhide': return await unhideChat(chat);
      case 'pin': return await setPinned(chat, true);
      case 'unpin': return await setPinned(chat, false);
      case 'markUnread': return await setUnreadCount(chat, 1);
      case 'markRead': return await setUnreadCount(chat, 0);
      default:
        // share and enterSelectMode are owned by the calling surface.
        return {};
    }
  } catch (error) {
    console.error(`[ChatMenuAction] ${action} failed:`, error);
    notificationStore.error(FAILURE_MESSAGES[action] ?? 'Action failed');
    return {};
  }
}
