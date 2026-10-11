// Keep a bounded in-session handoff fence for socket events that arrive before
// their encrypted message row. Directus processing receipts take over on sync.
// The fence is cleared with account and Team context state.

const processing = new Set<string>();
const MAX_FENCES = 200;

const key = (chatId: string, messageId: string): string => `${chatId}\0${messageId}`;

export function recordQueuedProcessing(chatId: string, messageId: string): void {
  if (!chatId || !messageId) return;
  const value = key(chatId, messageId);
  processing.delete(value);
  processing.add(value);
  if (processing.size > MAX_FENCES) processing.delete(processing.values().next().value!);
}

export function hasQueuedProcessing(chatId: string, messageId: string): boolean {
  return processing.has(key(chatId, messageId));
}

export function clearQueuedProcessingForMessage(chatId: string, messageId: string): void {
  processing.delete(key(chatId, messageId));
}

export function clearQueuedProcessing(): void {
  processing.clear();
}
