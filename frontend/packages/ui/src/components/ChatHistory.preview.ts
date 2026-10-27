/**
 * Fictional legacy memory-consent history for component verification.
 * Two historical clients recorded the same request with unknown/known counts.
 * Both record orders must show one pending request with the known count.
 * Toggling selection is local; fixtures must never confirm or reject remotely.
 * Architecture: docs/plans/memory-consent-convergence/plan.yml
 */
import { activeTeamContext } from '../stores/teamStore';

export const layout = 'fill';

if (typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('variant') === 'teamReminder') {
  activeTeamContext.set({ team: null, teamId: 'preview-team-reminder', epoch: 1 });
}

const chatId = "preview-memory-consent";
const requestId = "preview-memory-request";
const userId = "preview-memory-user";
const timestamp = 1788870532;
const user = { message_id: userId, chat_id: chatId, role: "user", content: "Help me reply to a photography enquiry using my saved writing preferences.", created_at: timestamp, status: "synced" };
function request(messageId: string, entryCount: number) {
  return { message_id: messageId, chat_id: chatId, role: "system", created_at: timestamp, status: "synced", content: JSON.stringify({ type: "app_settings_memories_request", request_id: requestId, user_message_id: userId, requested_keys: ["mail-writing_styles"], categories: [{ appId: "mail", itemType: "writing_styles", entryCount }] }) };
}
const unknown = request(requestId, 0);
const known = request("preview-web-request", 1);
// Saved/legacy assistant records can omit the live turn's user_message_id.
// Their rendering must not dereference absent processing feedback.
const savedAssistant = { message_id: "preview-saved-assistant", chat_id: chatId,
  role: "assistant", content: "Here is the saved photography reply.", created_at: timestamp + 1,
  status: "synced", model_name: "gemini-3.8-flash", category: "general_knowledge" };
const queuedUser = { message_id: "preview-queued-user", chat_id: chatId,
  role: "user", content: "Please shorten that reply.", created_at: timestamp + 2,
  status: "queued", queue_mode: "steer", queue_revision: 3 };
const memoryReceipt = (messageId: string, ids: Record<string, string> = {}) => ({
  message_id: messageId, chat_id: chatId, role: 'system', created_at: timestamp + 1, status: 'synced',
  content: JSON.stringify({ type: 'memories_loaded', count: 1, set_key: 'a'.repeat(64), ...ids,
    memories: [{ id: 'app:diagrams:type-flowchart', title: 'Diagram Design: Flowchart', source: 'app', app_id: 'diagrams',
      revision: 'b'.repeat(64), body: '- Make the direction of the flow clear.' }] }),
});
const activeAssistant = { ...savedAssistant, status: "streaming", user_message_id: userId };
const sendingFollowUp = { ...queuedUser, status: "sending" };
const props = { currentChatId: chatId, chatTitle: "Writing preferences", chatCategory: "general_knowledge", canAnnotate: false, isExampleChat: true, sourceMessages: [user, unknown, known] };
const activeResponseProps = { ...props, activeAssistantTurn: {
  taskId: activeAssistant.message_id, userMessageId: userId,
} };
const compressedChatId = 'demo-preview-compressed-history';
const cachedCompressedRows = Array.from({ length: 4 }, (_, index) => ({
  message_id: `preview-cached-${index}`, chat_id: compressedChatId,
  role: index % 2 ? 'assistant' : 'user', content: `Cached fictional history ${index}.`,
  created_at: timestamp + index, status: 'synced',
}));
export default props;
export const variants = {
  timelineHistory: { ...props, currentChatId: 'preview-timeline-history', chatTitle: 'Timeline history',
    sourceMessages: Array.from({ length: 2000 }, (_, index) => ({
      message_id: `timeline-history-${index}`, chat_id: 'preview-timeline-history', role: index % 2 ? 'assistant' : 'user',
      created_at: timestamp + index, status: 'synced',
      user_message_id: index % 2 ? `timeline-history-${index - 1}` : undefined,
      content: `${index % 2 ? 'Response' : 'Question'} ${Math.floor(index / 2)}: project budget and train tickets.` + (index % 2 && index % 7 === 1 ? '\n\n' + 'A detailed fictional explanation of the venue and travel budget.\n\n'.repeat(18) : ''),
    })), compressionCheckpoints: [{ id: 'timeline-history-checkpoint', chat_id: 'preview-timeline-history',
      summary: 'Earlier planning turns were summarized.', compressed_up_to_timestamp: timestamp + 1499,
      compressed_up_to_message_id: 'timeline-history-1499', compressed_message_count: 1500, created_at: timestamp + 1500 }] },
  partialCompressedHistory: { ...props, currentChatId: compressedChatId, isExampleChat: false, isSharedChat: true,
    chatTitle: 'Compressed fictional history', sourceMessages: cachedCompressedRows,
    compressionCheckpoints: [{ id: 'preview-compressed-checkpoint', chat_id: compressedChatId,
      summary: 'Earlier fictional planning turns.', compressed_up_to_timestamp: timestamp + 4,
      compressed_up_to_message_id: 'preview-boundary-reply', compressed_message_count: 5, created_at: timestamp + 5 }] },
  teamReminder: { ...props, isExampleChat: false, chatTitle: 'Volunteer planning', sourceMessages: [
    { ...user, sender_name: 'Alex', content: 'I will check the venue near Alexanderplatz.' },
    { ...user, message_id: 'preview-second-human', sender_name: 'Bea', content: 'I will prepare the invitation for our volunteers.', created_at: timestamp + 1 },
  ] },
  reversed: { ...props, sourceMessages: [user, known, unknown] },
  draftOnly: { ...props, isDraftOnly: true, chatTitle: '{"type":"image","embed_id":"fictional-image"}', sourceMessages: [] },
  titlePending: { ...props, chatTitle: '', provisionalChatTitle: user.content, isNewChatGeneratingTitle: true, sourceMessages: [user] },
  titleReady: { ...props, chatTitle: 'Photography reply', provisionalChatTitle: user.content, isNewChatGeneratingTitle: false, sourceMessages: [user] },
  savedAssistant: { ...props, pendingAssistantResponse: null, sourceMessages: [user, savedAssistant, queuedUser] },
  activeResponseSendingFollowUp: { ...activeResponseProps, sourceMessages: [user, activeAssistant, sendingFollowUp] },
  activeResponseQueuedFollowUp: { ...activeResponseProps, sourceMessages: [user, activeAssistant, queuedUser] },
  loadedMemoryAttached: { ...props, pendingAssistantResponse: null, sourceMessages: [user,
    memoryReceipt('preview-memory-receipt', { assistant_message_id: savedAssistant.message_id, user_message_id: userId }),
    { ...savedAssistant, user_message_id: userId }, queuedUser] },
  loadedMemoryOrphan: { ...props, pendingAssistantResponse: null, sourceMessages: [user,
    memoryReceipt('preview-memory-orphan', { assistant_message_id: 'missing-assistant', user_message_id: userId }),
    savedAssistant, queuedUser] },
  loadedMemoryPending: { ...props, pendingAssistantResponse: { taskId: 'preview-pending-task', userMessageId: userId },
    sourceMessages: [user, memoryReceipt('preview-memory-pending', { assistant_message_id: 'preview-pending-task', user_message_id: userId })] },
  loadedMemoryOtherTurn: { ...props, pendingAssistantResponse: null, sourceMessages: [user,
    memoryReceipt('preview-memory-other-turn', { assistant_message_id: 'preview-next-assistant', user_message_id: 'preview-queued-user' }),
    { ...savedAssistant, user_message_id: userId }, queuedUser,
    { ...savedAssistant, message_id: 'preview-next-assistant', user_message_id: 'preview-queued-user', created_at: timestamp + 3 }] },
};
