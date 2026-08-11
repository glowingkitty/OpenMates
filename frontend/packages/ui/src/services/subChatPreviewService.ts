// frontend/packages/ui/src/services/subChatPreviewService.ts
//
// Shared loader for sub-chat preview cards shown inside assistant messages.
// It merges static example sub-chats with local IndexedDB sub-chats, decrypts
// preview metadata when keys are available, and preserves explicit batch order.
// The UI can use it from legacy message-shell placement or inline render nodes.

import type { Chat, Message } from "../types/chat";
import { chatDB } from "./db";
import { getSubChatsForParent } from "./db/chatCrudOperations";
import { chatKeyManager } from "./encryption/ChatKeyManager";
import { decryptWithChatKey } from "./encryption/MessageEncryptor";
import { getValidIconName } from "../utils/categoryUtils";

export type SubChatPreview = Chat & {
  previewSummary?: string | null;
  previewCategory?: string | null;
  previewIcon?: string | null;
};

const subChatsByParentCache = new Map<string, Chat[]>();
const pendingSubChatsByParent = new Map<string, Promise<Chat[]>>();
const INTERNAL_PROTOCOL_FENCE_PATTERN =
  /```(?:json)?\s*[\r\n]+[\s\S]*?"type"\s*:\s*"(?:app[-_]skill[-_]use|sub[-_]chat[-_]batch)"[\s\S]*?```/gi;
const INTERNAL_PROTOCOL_MARKER_PATTERN =
  /(?:```json|"type"\s*:\s*"(?:app[-_]skill[-_]use|sub[-_]chat[-_]batch)")/i;
const DERIVED_PREVIEW_SUMMARY_MAX_LENGTH = 180;

export function sanitizeSubChatPreviewText(value: string | null | undefined): string | null {
  const sanitized = (value || "")
    .replace(INTERNAL_PROTOCOL_FENCE_PATTERN, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (!sanitized || INTERNAL_PROTOCOL_MARKER_PATTERN.test(sanitized)) return null;
  return sanitized;
}

function getMessageContentText(value: unknown): string {
  if (typeof value === "string") return value;
  if (!value || typeof value !== "object") return "";
  if (Array.isArray(value)) return value.map(getMessageContentText).filter(Boolean).join(" ");

  const node = value as { text?: unknown; content?: unknown };
  const ownText = typeof node.text === "string" ? node.text : "";
  const childText = getMessageContentText(node.content);
  return [ownText, childText].filter(Boolean).join(" ");
}

function truncateDerivedPreviewSummary(summary: string): string {
  if (summary.length <= DERIVED_PREVIEW_SUMMARY_MAX_LENGTH) return summary;
  return `${summary.slice(0, DERIVED_PREVIEW_SUMMARY_MAX_LENGTH).trimEnd()}...`;
}

function canUseAssistantMessageForPreview(message: Message, allowUnsyncedAssistantSummary: boolean): boolean {
  if (message.role !== "assistant") return false;
  if (message.status === "failed" || message.status === "waiting_for_user") return false;
  return message.status === "synced" || allowUnsyncedAssistantSummary;
}

async function derivePreviewSummaryFromCompletedMessage(
  chatId: string,
  allowUnsyncedAssistantSummary: boolean,
): Promise<string | null> {
  try {
    const messages = await chatDB.getMessagesForChat(chatId);
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      const message = messages[index];
      if (!canUseAssistantMessageForPreview(message, allowUnsyncedAssistantSummary)) continue;
      const summary = sanitizeSubChatPreviewText(getMessageContentText(message.content));
      if (summary) return truncateDerivedPreviewSummary(summary);
    }
  } catch (error) {
    console.error(`[SubChatPreviewService] Failed to derive completed sub-chat summary for ${chatId}:`, error);
  }
  return null;
}

export function clearSubChatsForParentCache(parentChatId: string): void {
  subChatsByParentCache.delete(parentChatId);
}

async function getSubChatsForParentChat(
  parentChatId: string,
  forceRefresh = false,
): Promise<Chat[]> {
  if (!forceRefresh && subChatsByParentCache.has(parentChatId)) {
    return subChatsByParentCache.get(parentChatId) ?? [];
  }

  const pending = pendingSubChatsByParent.get(parentChatId);
  if (!forceRefresh && pending) return pending;

  const loadPromise = (async () => {
    const { getExampleSubChats } = await import("../demo_chats");
    const exampleSubChats = getExampleSubChats(parentChatId);
    const dbSubChats = await getSubChatsForParent(chatDB, parentChatId);
    const seenChatIds = new Set(exampleSubChats.map((chat) => chat.chat_id));
    const subChats = [
      ...exampleSubChats,
      ...dbSubChats.filter((chat) => !seenChatIds.has(chat.chat_id)),
    ];
    subChatsByParentCache.set(parentChatId, subChats);
    return subChats;
  })().finally(() => {
    pendingSubChatsByParent.delete(parentChatId);
  });

  pendingSubChatsByParent.set(parentChatId, loadPromise);
  return loadPromise;
}

function orderByRequestedIds(chats: Chat[], requestedIds: string[]): Chat[] {
  if (requestedIds.length === 0) return chats;
  const byId = new Map(chats.map((chat) => [chat.chat_id, chat]));
  return requestedIds.map((chatId) => byId.get(chatId)).filter((chat): chat is Chat => Boolean(chat));
}

export async function loadSubChatPreviews(
  parentChatId: string,
  options: {
    messageCreatedAt?: number;
    subChatIds?: string[];
    forceRefresh?: boolean;
    allowUnsyncedAssistantSummary?: boolean;
    terminalSubChatIds?: Iterable<string>;
  } = {},
): Promise<SubChatPreview[]> {
  const all = await getSubChatsForParentChat(parentChatId, options.forceRefresh);
  const requestedIds = options.subChatIds?.filter(Boolean) ?? [];
  const matchingSubChats = requestedIds.length > 0
    ? orderByRequestedIds(all, requestedIds)
    : all.filter((chat) => {
        const isSubChat = chat.is_sub_chat || chat.parent_id !== null;
        if (!isSubChat) return false;
        if (parentChatId.startsWith("example-")) return chat.parent_id === parentChatId;
        if (!options.messageCreatedAt) return chat.parent_id === parentChatId;
        return Math.abs(chat.created_at - options.messageCreatedAt) < 60;
      });

  const previews: SubChatPreview[] = [];
  const fallbackKey = await chatKeyManager.getKey(parentChatId);
  const terminalSubChatIds = new Set(options.terminalSubChatIds ?? []);

  for (const chat of matchingSubChats) {
    const chatKey = (await chatKeyManager.getKey(chat.chat_id)) || fallbackKey;
    const preview: SubChatPreview = { ...chat };

    if (chatKey) {
      if (!preview.title && chat.encrypted_title) {
        preview.title =
          (await decryptWithChatKey(chat.encrypted_title, chatKey, {
            chatId: chat.chat_id,
            fieldName: "sub_chat_title",
          })) || preview.title;
      }
      if (chat.encrypted_chat_summary) {
        preview.previewSummary = await decryptWithChatKey(chat.encrypted_chat_summary, chatKey, {
          chatId: chat.chat_id,
          fieldName: "sub_chat_summary",
        });
      }
      if (chat.encrypted_category) {
        preview.previewCategory = await decryptWithChatKey(chat.encrypted_category, chatKey, {
          chatId: chat.chat_id,
          fieldName: "sub_chat_category",
        });
      }
      if (chat.encrypted_icon) {
        preview.previewIcon = await decryptWithChatKey(chat.encrypted_icon, chatKey, {
          chatId: chat.chat_id,
          fieldName: "sub_chat_icon",
        });
      }
    }

    preview.title = sanitizeSubChatPreviewText(preview.title) || undefined;
    preview.previewSummary =
      sanitizeSubChatPreviewText(preview.previewSummary) ||
      sanitizeSubChatPreviewText(chat.chat_summary) ||
      await derivePreviewSummaryFromCompletedMessage(
        chat.chat_id,
        options.allowUnsyncedAssistantSummary === true || terminalSubChatIds.has(chat.chat_id),
      );
    preview.previewCategory ||= chat.category || "general_knowledge";
    preview.previewIcon = getValidIconName(
      preview.previewIcon || "",
      preview.previewCategory || "general_knowledge",
    );
    previews.push(preview);
  }

  return previews;
}
