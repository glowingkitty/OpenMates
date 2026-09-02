/**
 * Owner-side helpers for historical assistant speech generation.
 * The paired CLI projects decrypted text locally and sends only bounded
 * transient paragraph text to the first-party speech WebSocket contract.
 * Summaries intentionally exclude content, keys, provider IDs, and S3 paths.
 */

export { projectAssistantSpeech } from "../../assistantSpeechProjection";
import { projectAssistantSpeech } from "../../assistantSpeechProjection";

export interface SpeechMessage {
  id: string;
  clientMessageId?: string;
  role: string;
  content: string;
}

export interface SpeechMessageResult {
  messageId: string;
  generated: number;
  reused: number;
  failed: number;
  charged: number;
}

export function selectAssistantMessagesForSpeech<T extends SpeechMessage>(
  messages: T[],
  selection: { messageId?: string; all?: boolean },
): T[] {
  if (Boolean(selection.messageId) === Boolean(selection.all)) {
    throw new Error("Select exactly one of --message <id> or --all.");
  }
  const assistantMessages = messages.filter((message) => message.role === "assistant" && projectAssistantSpeech(message.content).length > 0);
  if (selection.all) return assistantMessages;
  const selected = messages.find((message) =>
    message.id === selection.messageId
    || message.id.startsWith(selection.messageId ?? "")
    || message.clientMessageId === selection.messageId
    || message.clientMessageId?.startsWith(selection.messageId ?? ""));
  if (!selected || selected.role !== "assistant") throw new Error("The selected message is not an eligible assistant message.");
  return [selected];
}

export function summarizeAssistantSpeech(chatId: string, results: SpeechMessageResult[]) {
  return {
    chat_id: chatId,
    messages: results.length,
    generated_segments: results.reduce((total, result) => total + result.generated, 0),
    reused_segments: results.reduce((total, result) => total + result.reused, 0),
    failed_segments: results.reduce((total, result) => total + result.failed, 0),
    charged_segments: results.reduce((total, result) => total + result.charged, 0),
  };
}
