/**
 * Pure send-classification helpers for MessageInput.
 *
 * The main send handler imports many browser/editor services, so these small
 * predicates live separately for cheap regression tests. They decide whether a
 * local send should activate ActiveChat's new-chat path or normal append path.
 */
import type { Chat } from '../../../types/chat';

export function isDraftOnlyChatMissingDurableKey(args: {
  draftChatId?: string | null;
  chatIdToUse: string;
  existingChat: Pick<Chat, 'messages_v' | 'encrypted_chat_key'> | null;
}): boolean {
  return Boolean(
    args.draftChatId &&
      args.chatIdToUse === args.draftChatId &&
      args.existingChat &&
      !args.existingChat.encrypted_chat_key &&
      (args.existingChat.messages_v ?? 0) === 0,
  );
}

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

export function isUnsupportedTeamIncognitoContext(
  teamId: string | null | undefined,
  isIncognito: boolean,
): boolean {
  return Boolean(teamId && isIncognito);
}

export function shouldAwaitAITaskStart(args: {
  authenticated: boolean;
  teamId: string | null | undefined;
  invokesTeamAI: boolean;
}): boolean {
  return args.authenticated && (!args.teamId || args.invokesTeamAI);
}
