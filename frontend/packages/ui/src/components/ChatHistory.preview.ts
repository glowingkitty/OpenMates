/**
 * Fictional legacy memory-consent history for component verification.
 * Two historical clients recorded the same request with unknown/known counts.
 * Both record orders must show one pending request with the known count.
 * Toggling selection is local; fixtures must never confirm or reject remotely.
 * Architecture: docs/plans/memory-consent-convergence/plan.yml
 */
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
const props = { currentChatId: chatId, chatTitle: "Writing preferences", chatCategory: "general_knowledge", canAnnotate: false, isExampleChat: true, sourceMessages: [user, unknown, known] };
export default props;
export const variants = { reversed: { ...props, sourceMessages: [user, known, unknown] } };
