/** Prefer the complete decoded row already displayed by ChatHistory over disk.
 * Optimistic rows can render before their canonical IndexedDB write completes. */
export async function loadExpandedMessageMarkdown(
  message: { message_id?: string; chat_id?: string; content?: unknown },
  loadSaved: (messageId: string) => Promise<{ content?: unknown } | null>,
): Promise<string | null> {
  if (typeof message.content === 'string' && message.content.length > 0) return message.content;
  if (!message.message_id) return null;
  const saved = await loadSaved(message.message_id);
  return typeof saved?.content === 'string' ? saved.content : null;
}
