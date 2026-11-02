import { validLocalRead, validSavedRead } from "./savedReadProtocol";
import type { LocalChatReadback, SavedChatReadback, SavedMessageMetadata } from "./savedReadProtocol";

type ReadonlyTree<T> = T extends readonly (infer U)[] ? readonly ReadonlyTree<U>[]
  : T extends object ? { readonly [K in keyof T]: ReadonlyTree<T[K]> } : T;
type Role = "user" | "assistant" | "system";

/** Presentation only. Deliberately not a durable Message or Chat, nor a send capability.
 * The caller must validate its active owner/chat/lifetime before and after publishing.
 * This synchronous function cannot establish session freshness or writer ownership.
 */
export interface SavedChatRendererMessage {
  readonly id: string;
  readonly message_id: string;
  readonly chat_id: string;
  readonly role: Role;
  readonly content: string;
  readonly created_at: number;
  readonly sender_name: string;
  readonly thinking_content: string;
  readonly category: string | null;
  readonly model_name: string | null;
  readonly thinking_signature: string | null;
  readonly has_thinking: boolean | null;
  readonly thinking_token_count: number | null;
  /** Uninterpreted saved status; never default to delivered/synced. */
  readonly rawStatus: string | null;
  /** Separate exact logical/storage/source/client identities and remaining metadata. */
  readonly metadata: ReadonlyTree<SavedMessageMetadata>;
}
export interface SavedChatRendererProjection {
  readonly chatId: string;
  readonly title: string;
  readonly category: string;
  readonly messages: readonly SavedChatRendererMessage[];
  /** Exact transport page, including nullable boundaries, PII mappings and provenance.
   * No mappings are applied here or exposed as legacy cumulative pii_mappings.
   */
  readonly page: ReadonlyTree<SavedChatReadback | LocalChatReadback>;
}

// Copy/freeze only validated plain DTOs, so callers cannot mutate the captured view
// through the response or a nested metadata/cursor/mapping alias.
function snapshot<T>(value: T): ReadonlyTree<T> {
  if (Array.isArray(value)) return Object.freeze(value.map(item => snapshot(item))) as ReadonlyTree<T>;
  if (value !== null && typeof value === "object") {
    return Object.freeze(Object.fromEntries(Object.entries(value).map(([key, item]) => [key, snapshot(item)]))) as ReadonlyTree<T>;
  }
  return value as ReadonlyTree<T>;
}

/** Exact shared presentation field mapping. Callers first validate their own
 * distinct source envelope; this function never manufactures one or upgrades
 * read provenance, boundaries, PII history or durability authority. */
export function projectSavedRendererMessages(
  chat: SavedChatReadback["chat"], messageMetadata: readonly SavedMessageMetadata[],
): readonly SavedChatRendererMessage[] {
  if (messageMetadata.length !== chat.messages.length) throw new Error("invalid_saved_renderer_page");
  const seen = new Set<string>();
  return Object.freeze(chat.messages.map((message, index): SavedChatRendererMessage => {
    const metadata = messageMetadata[index];
    if (!metadata || metadata.id !== message.id || metadata.chatId !== chat.id || seen.has(message.id)) {
      throw new Error("invalid_saved_renderer_page");
    }
    seen.add(message.id);
    // Role is the only renderer enum admitted here. Do not relabel unknown roles.
    if (message.role !== "user" && message.role !== "assistant" && message.role !== "system") {
      throw new Error("invalid_saved_renderer_page");
    }
    return Object.freeze({
      id: message.id,
      message_id: message.id,
      chat_id: metadata.chatId,
      role: message.role,
      content: message.content,
      created_at: metadata.createdAt,
      sender_name: message.sender,
      thinking_content: message.thinking,
      category: metadata.category,
      model_name: metadata.modelName,
      thinking_signature: metadata.thinkingSignature,
      has_thinking: metadata.hasThinking,
      thinking_token_count: metadata.thinkingTokenCount,
      rawStatus: metadata.rawStatus,
      metadata: snapshot(metadata),
    });
  }));
}

/** Map one already decrypted Rust page, preserving its exact order and content.
 * expectedChatId is a consistency guard, not authority. Rich saved metadata is
 * mandatory; bare local previews cannot supply renderer timestamps/identities.
 * Throws a fixed nonpersonal error instead of logging response data.
 */
export function projectSavedChatForRenderer(
  input: unknown,
  expectedChatId: string,
): SavedChatRendererProjection {
  if (!validSavedRead(input) && !validLocalRead(input, true)) throw new Error("invalid_saved_renderer_page");
  if (input.chat.id !== expectedChatId || !input.chatMetadata || !input.messageMetadata) {
    throw new Error("invalid_saved_renderer_page");
  }
  const messages = projectSavedRendererMessages(input.chat, input.messageMetadata);
  return Object.freeze({
    chatId: input.chat.id,
    title: input.chat.title,
    category: input.chat.category,
    messages: Object.freeze(messages),
    page: snapshot(input),
  });
}
