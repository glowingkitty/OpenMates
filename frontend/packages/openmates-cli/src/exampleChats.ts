/*
 * Public example chat helpers for unauthenticated CLI usage.
 *
 * Source: frontend/packages/ui/src/demo_chats/exampleChatData.ts
 * Purpose: expose the same bundled web example chats in the terminal without
 * requiring a session or backend sync.
 * Security: examples are public content only; user chats still require login.
 */

import { ALL_EXAMPLE_CHATS } from "../../ui/src/demo_chats/exampleChatData";
import enLocale from "../../ui/src/i18n/locales/en.json" with { type: "json" };

type LocaleNode = string | { [key: string]: LocaleNode };

export interface ExampleChatListItem {
  id: string;
  shortId: string;
  slug: string;
  title: string | null;
  summary: string | null;
  updatedAt: number | null;
  category: string | null;
  mateName: string | null;
  source: "example";
}

export interface ExampleChatMessage {
  id: string;
  chatId: string;
  role: string;
  content: string;
  senderName: string | null;
  category: string | null;
  modelName: string | null;
  createdAt: number;
  embedIds: string[];
}

export interface ExampleChatConversation {
  chat: ExampleChatListItem;
  messages: ExampleChatMessage[];
  followUpSuggestions: string[];
}

function translate(value: string): string {
  if (!value.startsWith("example_chats.")) return value;
  const parts = value.split(".");
  let current: LocaleNode | undefined = enLocale as LocaleNode;
  for (const part of parts) {
    if (typeof current !== "object" || current === null) return value;
    current = current[part];
  }
  if (typeof current === "string") return current;
  if (typeof current === "object" && current !== null && typeof current.text === "string") {
    return current.text;
  }
  return value;
}

function latestTimestamp(chat: (typeof ALL_EXAMPLE_CHATS)[number]): number | null {
  const timestamps = chat.messages
    .map((message) => message.created_at)
    .filter((value) => Number.isFinite(value));
  return timestamps.length > 0 ? Math.max(...timestamps) : null;
}

function toListItem(chat: (typeof ALL_EXAMPLE_CHATS)[number]): ExampleChatListItem {
  return {
    id: chat.chat_id,
    shortId: chat.chat_id,
    slug: chat.slug,
    title: translate(chat.title),
    summary: translate(chat.summary),
    updatedAt: latestTimestamp(chat),
    category: chat.category,
    mateName: null,
    source: "example",
  };
}

export function listExampleChats(limit = 10, page = 1) {
  const total = ALL_EXAMPLE_CHATS.length;
  const offset = (page - 1) * limit;
  const slice = ALL_EXAMPLE_CHATS.slice(offset, offset + limit);
  return {
    chats: slice.map(toListItem),
    total,
    page,
    limit,
    hasMore: offset + limit < total,
  };
}

export function searchExampleChats(query: string): ExampleChatListItem[] {
  const normalized = query.trim().toLowerCase();
  if (!normalized) return [];
  return ALL_EXAMPLE_CHATS
    .map(toListItem)
    .filter((chat) => {
      const fields = [chat.id, chat.slug, chat.title, chat.summary, chat.category];
      return fields.some((field) => String(field ?? "").toLowerCase().includes(normalized));
    });
}

export function getExampleChatConversation(query: string): ExampleChatConversation | null {
  const normalized = query.trim().toLowerCase();
  const chat = ALL_EXAMPLE_CHATS.find((candidate) => {
    const title = translate(candidate.title).toLowerCase();
    return (
      candidate.chat_id.toLowerCase() === normalized ||
      candidate.chat_id.toLowerCase().startsWith(normalized) ||
      candidate.slug.toLowerCase() === normalized ||
      title === normalized ||
      title.includes(normalized)
    );
  });
  if (!chat) return null;

  return {
    chat: toListItem(chat),
    messages: chat.messages.map((message) => ({
      id: message.id,
      chatId: chat.chat_id,
      role: message.role,
      content: translate(message.content),
      senderName: message.role === "user" ? "User" : null,
      category: message.category ?? chat.category,
      modelName: message.model_name ?? null,
      createdAt: message.created_at,
      embedIds: [],
    })),
    followUpSuggestions: chat.follow_up_suggestions.map(translate),
  };
}
