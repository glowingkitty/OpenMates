/**
 * Shared chat action catalog for the chat right-click menu and the fullscreen
 * chat More menu, so both surfaces offer the same actions with the same icons,
 * labels and visibility rules. Ordering by usage lives in chatMenuUsage.ts.
 */
import type { Chat } from '../../types/chat';
import { isDemoChat, isLegalChat, isPublicChat } from '../../demo_chats';

export type ChatMenuAction =
  | 'addToProject' | 'createProject' | 'moveToProject' | 'openNewTab' | 'enterSelectMode'
  | 'download' | 'copy' | 'share' | 'hide' | 'unhide' | 'pin' | 'unpin'
  | 'markUnread' | 'markRead' | 'delete' | 'toggleDebug';

export interface ChatMenuItem {
  action: ChatMenuAction;
  /** Stable key for usage ranking; toggled pairs share one key (pin/unpin). */
  usageId: string;
  icon: string;
  labelKey: string;
  testId: string;
  tone?: 'danger' | 'muted';
  disabled?: boolean;
  /** Keep at the bottom regardless of usage. */
  pinned?: 'end';
}

export interface ChatMenuContext {
  chat: Chat | undefined;
  isAuthenticated: boolean;
  isAdmin: boolean;
  shareAllowed: boolean;
  isUnread: boolean;
  debugActive: boolean;
  /** Project actions are offered only when the projects feature is released/active. */
  projectsEnabled: boolean;
  hide?: Partial<Record<'delete' | 'download' | 'copy' | 'select' | 'share' | 'visibility' | 'pin' | 'readStatus' | 'openNewTab', boolean>>;
}

export function buildChatMenuItems(ctx: ChatMenuContext): ChatMenuItem[] {
  const { chat, isAuthenticated, hide = {} } = ctx;
  const items: ChatMenuItem[] = [];
  const isPublic = chat ? isPublicChat(chat.chat_id) : false;
  const ownsChat = Boolean(
    isAuthenticated && chat && !chat.is_incognito && !chat.is_shared_by_others
      && !isDemoChat(chat.chat_id) && !isLegalChat(chat.chat_id) && !isPublic,
  );

  if (ownsChat && ctx.projectsEnabled) {
    items.push(
      { action: 'addToProject', usageId: 'addToProject', icon: 'icon_project', labelKey: 'chats.projects.add', testId: 'chat-context-add-to-project' },
      { action: 'createProject', usageId: 'createProject', icon: 'icon_create', labelKey: 'chats.projects.create', testId: 'chat-context-create-project' },
      { action: 'moveToProject', usageId: 'moveToProject', icon: 'icon_project', labelKey: 'chats.projects.move', testId: 'chat-context-move-to-project' },
    );
  }
  if (!hide.openNewTab) {
    items.push({ action: 'openNewTab', usageId: 'openNewTab', icon: 'icon_chat', labelKey: 'chats.context_menu.open_new_tab', testId: 'chat-context-open-new-tab' });
  }
  if (!hide.select) {
    items.push({ action: 'enterSelectMode', usageId: 'select', icon: 'icon_select', labelKey: 'chats.context_menu.select', testId: 'chat-context-select' });
  }
  if (!hide.download) {
    items.push({ action: 'download', usageId: 'download', icon: 'icon_download', labelKey: 'common.download', testId: 'chat-context-download' });
  }
  if (!hide.copy) {
    items.push({ action: 'copy', usageId: 'copy', icon: 'icon_copy', labelKey: 'common.copy', testId: 'chat-context-copy' });
  }
  if (!hide.share && chat && ctx.shareAllowed && !isPublic) {
    items.push({ action: 'share', usageId: 'share', icon: 'icon_share', labelKey: 'common.share', testId: 'chat-context-share' });
  }
  if (!hide.visibility && chat && !chat.is_incognito && !chat.is_hidden && !isPublic) {
    items.push({ action: 'hide', usageId: 'hide', icon: 'icon_hidden', labelKey: 'chats.context_menu.hide', testId: 'chat-context-hide', disabled: !isAuthenticated });
  }
  if (!hide.visibility && chat?.is_hidden) {
    items.push({ action: 'unhide', usageId: 'hide', icon: 'icon_unhide', labelKey: 'chats.context_menu.unhide', testId: 'chat-context-unhide', disabled: !isAuthenticated });
  }
  if (!hide.pin && chat && !chat.is_incognito && !isPublic) {
    items.push(chat.pinned
      ? { action: 'unpin', usageId: 'pin', icon: 'icon_pin_off', labelKey: 'chats.context_menu.unpin', testId: 'chat-context-unpin', disabled: !isAuthenticated }
      : { action: 'pin', usageId: 'pin', icon: 'icon_pin', labelKey: 'chats.context_menu.pin', testId: 'chat-context-pin', disabled: !isAuthenticated });
  }
  if (!hide.readStatus && chat && !chat.is_incognito && !isPublic) {
    items.push(ctx.isUnread
      ? { action: 'markRead', usageId: 'readStatus', icon: 'icon_mail', labelKey: 'chats.context_menu.mark_read', testId: 'chat-context-mark-read' }
      : { action: 'markUnread', usageId: 'readStatus', icon: 'icon_mail', labelKey: 'chats.context_menu.mark_unread', testId: 'chat-context-mark-unread' });
  }
  if (!hide.delete && !(chat && (isDemoChat(chat.chat_id) || isLegalChat(chat.chat_id)) && !isAuthenticated)) {
    items.push({ action: 'delete', usageId: 'delete', icon: 'icon_delete', labelKey: 'common.delete', testId: 'chat-context-delete', tone: 'danger', pinned: 'end' });
  }
  if (ctx.isAdmin) {
    items.push({
      action: 'toggleDebug', usageId: 'debug', icon: 'icon_bug', testId: 'context-menu-toggle-debug', tone: 'muted', pinned: 'end',
      labelKey: ctx.debugActive ? 'chats.context_menu.end_debugging' : 'chats.context_menu.start_debugging',
    });
  }
  return items;
}
