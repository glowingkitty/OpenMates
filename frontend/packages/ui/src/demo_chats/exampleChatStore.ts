// frontend/packages/ui/src/demo_chats/exampleChatStore.ts
//
// Static in-memory store for hardcoded example chats.
// Replaces the old communityDemoStore which fetched demo chats from the backend.
//
// Example chats are real conversations reproduced 1:1 from shared chat links.
// They include full message content and embed data, and require NO backend loading.
// Each chat has a natural-language slug for SEO-friendly URLs.

import type { Chat, Message } from "../types/chat";
import type { ExampleChat, ExampleChatEmbed } from "./types";
import { get } from "svelte/store";
import { text } from "../i18n/translations";
import { embedStore } from "../services/embedStore";

// Import all example chats
import { giganticAirplanesChat } from "./data/example_chats/gigantic-airplanes";
import { artemisIIMissionChat } from "./data/example_chats/artemis-ii-mission";
import { beautifulSinglePageHtmlChat } from "./data/example_chats/beautiful-single-page-html";

// ============================================================================
// ALL EXAMPLE CHATS — add new chats here
// ============================================================================

const ALL_EXAMPLE_CHATS: ExampleChat[] = [
  giganticAirplanesChat,
  artemisIIMissionChat,
  beautifulSinglePageHtmlChat,
].sort((a, b) => a.metadata.order - b.metadata.order);

/** Maximum number of example chats shown on the homepage */
const FEATURED_LIMIT = 10;

// ============================================================================
// TRANSLATION HELPER
// ============================================================================

/**
 * Resolve an i18n key via the text store, or return the string as-is
 * if it doesn't look like an i18n key (e.g. JSON tool call content).
 */
function translate(value: string): string {
  // Assistant messages are JSON tool calls — not i18n keys
  if (value.startsWith("`") || value.startsWith("{") || value.startsWith("[")) {
    return value;
  }
  // i18n keys follow the pattern "example_chats.xxx.yyy"
  if (value.startsWith("example_chats.")) {
    const t = get(text) as (key: string) => string;
    return t(value);
  }
  return value;
}

// ============================================================================
// CONVERSION — ExampleChat → Chat/Message format used by the app
// ============================================================================

function exampleChatToChat(example: ExampleChat): Chat {
  // Place example chats 7 days ago to appear in "Last 7 days" sidebar group
  const sevenDaysAgo = Date.now() - 7 * 24 * 60 * 60 * 1000;
  const timestamp = sevenDaysAgo - example.metadata.order * 1000;

  return {
    chat_id: example.chat_id,
    title: translate(example.title),
    encrypted_title: null,
    category: example.category,
    icon: example.icon,
    chat_summary: translate(example.summary),
    follow_up_request_suggestions: JSON.stringify(
      example.follow_up_suggestions.map(translate)
    ),
    demo_chat_category: "for_everyone",
    messages_v: example.messages.length,
    title_v: 1,
    last_edited_overall_timestamp: timestamp,
    unread_count: 0,
    created_at: timestamp,
    updated_at: timestamp,
  };
}

function exampleMessagesToMessages(example: ExampleChat): Message[] {
  return example.messages.map((msg) => ({
    message_id: msg.id,
    chat_id: example.chat_id,
    role: msg.role as "user" | "assistant",
    content: translate(msg.content),
    category: msg.category,
    model_name: msg.model_name,
    created_at: msg.created_at,
    status: "synced" as const,
  }));
}

// ============================================================================
// Pre-built lookup maps (built once at import time)
// ============================================================================

const chatById = new Map<string, ExampleChat>();
const chatBySlug = new Map<string, ExampleChat>();
const embedById = new Map<string, { embed: ExampleChatEmbed; chatId: string }>();

for (const example of ALL_EXAMPLE_CHATS) {
  chatById.set(example.chat_id, example);
  chatBySlug.set(example.slug, example);
  for (const embed of example.embeds) {
    embedById.set(embed.embed_id, { embed, chatId: example.chat_id });
  }
}

// ============================================================================
// EMBED REGISTRATION — register embed_ref → embed_id mappings
// ============================================================================

/** Regex to extract embed_ref from TOON content */
const EMBED_REF_RE = /^embed_ref:\s*"?([^\n"]+)"?\s*$/m;
const APP_ID_RE = /^app_id:\s*"?([^\n"]+)"?\s*$/m;

/**
 * Register all example chat embed_ref → embed_id mappings in the embedStore.
 * This must be called once so inline embed references in messages
 * (e.g. [!](embed:popularmechanics.com-kIm)) can be resolved to embed UUIDs.
 */
export function registerExampleChatEmbedRefs(): void {
  let registered = 0;
  for (const example of ALL_EXAMPLE_CHATS) {
    for (const embed of example.embeds) {
      if (!embed.content || !embed.embed_id) continue;
      const refMatch = embed.content.match(EMBED_REF_RE);
      if (!refMatch) continue;
      const appIdMatch = embed.content.match(APP_ID_RE);
      embedStore.registerEmbedRef(
        refMatch[1].trim(),
        embed.embed_id,
        appIdMatch ? appIdMatch[1].trim() : null,
      );
      registered++;
    }
  }
  if (registered > 0) {
    console.debug(
      `[exampleChatStore] Registered ${registered} embed_ref mappings for example chats`,
    );
  }
}

// ============================================================================
// PUBLIC API — drop-in replacement for communityDemoStore
// ============================================================================

/** Check if a chat ID belongs to an example chat */
export function isExampleChat(chatId: string): boolean {
  return chatById.has(chatId);
}

/** Get an example chat by ID */
export function getExampleChat(chatId: string): Chat | null {
  const example = chatById.get(chatId);
  return example ? exampleChatToChat(example) : null;
}

/** Get an example chat by slug */
export function getExampleChatBySlug(slug: string): ExampleChat | undefined {
  return chatBySlug.get(slug);
}

/** Get messages for an example chat */
export function getExampleChatMessages(chatId: string): Message[] {
  const example = chatById.get(chatId);
  return example ? exampleMessagesToMessages(example) : [];
}

/** Get embeds for an example chat */
export function getExampleChatEmbeds(chatId: string): ExampleChatEmbed[] {
  const example = chatById.get(chatId);
  return example?.embeds ?? [];
}

/** Get a specific embed by ID from any example chat */
export function getExampleChatEmbed(
  embedId: string,
): ExampleChatEmbed | null {
  return embedById.get(embedId)?.embed ?? null;
}

/** Get all example chats as Chat objects (for sidebar listing) */
export function getAllExampleChats(): Chat[] {
  return ALL_EXAMPLE_CHATS.map(exampleChatToChat);
}

/** Get featured example chats (limited to homepage display count) */
export function getFeaturedExampleChats(): Chat[] {
  return ALL_EXAMPLE_CHATS.filter((c) => c.metadata.featured)
    .slice(0, FEATURED_LIMIT)
    .map(exampleChatToChat);
}

/** Get the raw ExampleChat data (for SEO pages, etc.) */
export function getExampleChatData(chatId: string): ExampleChat | undefined {
  return chatById.get(chatId);
}

/** Get all raw ExampleChat data */
export function getAllExampleChatData(): ExampleChat[] {
  return ALL_EXAMPLE_CHATS;
}

/** Total number of example chats */
export function getExampleChatCount(): number {
  return ALL_EXAMPLE_CHATS.length;
}

// resolveExampleChatI18nKey is in a separate server-only module to avoid
// bundling en.json (400KB) into the client. See ./resolveI18nServer.ts
