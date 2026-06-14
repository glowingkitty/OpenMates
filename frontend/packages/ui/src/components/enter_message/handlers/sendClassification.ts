/**
 * Pure send-classification helpers for MessageInput.
 *
 * The main send handler imports many browser/editor services, so these small
 * predicates live separately for cheap regression tests. They decide whether a
 * local send should activate ActiveChat's new-chat path or normal append path.
 */
import type { Chat } from '../../../types/chat';

export function shouldDispatchDraftChatAsNewChat(args: {
  currentChatId?: string;
  draftChatId?: string | null;
  chatIdToUse: string;
  existingChat: Pick<Chat, 'messages_v'> | null;
  existingChatHasUsableKey: boolean;
}): boolean {
  return Boolean(
    !args.currentChatId &&
      args.draftChatId &&
      args.chatIdToUse === args.draftChatId &&
      args.existingChat &&
      args.existingChatHasUsableKey &&
      (args.existingChat.messages_v ?? 0) === 0,
  );
}
