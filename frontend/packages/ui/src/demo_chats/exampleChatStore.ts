// frontend/packages/ui/src/demo_chats/exampleChatStore.ts
//
// Static in-memory store for hardcoded example chats.
// Replaces the old communityDemoStore which fetched demo chats from the backend.
//
// Example chats are real conversations reproduced 1:1 from shared chat links.
// They include full message content and embed data, and require NO backend loading.
// Each chat has a natural-language slug for SEO-friendly URLs.

import type { Chat, Message } from "../types/chat";
import type { ExampleChat, ExampleChatEmbed, ExampleSubChat } from "./types";
import { get } from "svelte/store";
import { text } from "../i18n/translations";
import { embedStore } from "../services/embedStore";
import { ALL_EXAMPLE_CHATS } from "./exampleChatData";

const FOCUS_ACTIVATION_EMBED_TYPE = "focus-mode-activation";

// ============================================================================
// ALL EXAMPLE CHATS — add new chats here
// ============================================================================

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

function toonField(content: string, key: string): string | null {
  const match = content.match(new RegExp(`(?:^|\\n)${key}:\\s*"?([^\\n"]+)"?`));
  return match?.[1]?.trim() ?? null;
}

function getFocusActivationEmbed(example: ExampleChatRecord): ExampleChatEmbed | null {
  if (isExampleSubChatRecord(example) || !example.metadata.active_focus_id) return null;
  return (
    example.embeds.find(
      (embed) =>
        embed.type === FOCUS_ACTIVATION_EMBED_TYPE &&
        toonField(embed.content, "focus_id") === example.metadata.active_focus_id,
    ) ?? null
  );
}

function focusActivationContent(embed: ExampleChatEmbed): string | null {
  const appId = toonField(embed.content, "app_id");
  const skillId = toonField(embed.content, "skill_id");
  const focusId = toonField(embed.content, "focus_id");
  const focusModeName = toonField(embed.content, "focus_mode_name");
  if (!appId || !skillId || !focusId || !focusModeName) return null;

  return `\`\`\`json\n${JSON.stringify({
    type: "focus_mode_activation",
    embed_id: embed.embed_id,
    status: toonField(embed.content, "status") ?? "finished",
    app_id: appId,
    skill_id: skillId,
    focus_id: focusId,
    focus_mode_name: focusModeName,
  })}\n\`\`\``;
}

// ============================================================================
// CONVERSION — ExampleChat → Chat/Message format used by the app
// ============================================================================

type ExampleChatRecord = ExampleChat | ExampleSubChat;

function isExampleSubChatRecord(example: ExampleChatRecord): example is ExampleSubChat {
  return "parent_id" in example && example.is_sub_chat === true;
}

function exampleChatToChat(example: ExampleChatRecord, rootOrder = 0): Chat {
  // Place example chats 7 days ago to appear in "Last 7 days" sidebar group
  const sevenDaysAgo = Date.now() - 7 * 24 * 60 * 60 * 1000;
  const messageTimestamps = example.messages
    .map((message) => message.created_at)
    .filter((value) => Number.isFinite(value));
  const timestamp = isExampleSubChatRecord(example)
    ? (messageTimestamps.length > 0 ? Math.max(...messageTimestamps) * 1000 : sevenDaysAgo - rootOrder * 1000)
    : sevenDaysAgo - example.metadata.order * 1000;

  return {
    chat_id: example.chat_id,
    title: translate(example.title),
    encrypted_title: null,
    category: example.category,
    icon: example.icon,
    chat_summary: translate(example.summary),
    follow_up_request_suggestions: JSON.stringify(
      example.follow_up_suggestions.map(translate),
    ),
    active_focus_id: isExampleSubChatRecord(example) ? null : example.metadata.active_focus_id ?? null,
    demo_chat_category: "for_everyone",
    messages_v: example.messages.length,
    title_v: 1,
    last_edited_overall_timestamp: timestamp,
    unread_count: 0,
    created_at: timestamp,
    updated_at: timestamp,
    parent_id: isExampleSubChatRecord(example) ? example.parent_id : null,
    is_sub_chat: isExampleSubChatRecord(example) ? true : false,
    budget_limit: isExampleSubChatRecord(example) ? example.budget_limit ?? null : null,
    budget_spent: isExampleSubChatRecord(example) ? example.budget_spent ?? 0 : undefined,
  };
}

function exampleMessagesToMessages(example: ExampleChatRecord): Message[] {
  const messages = example.messages.map((msg) => ({
    message_id: msg.id,
    chat_id: example.chat_id,
    role: msg.role,
    content: translate(msg.content),
    category: msg.category,
    model_name: msg.model_name,
    pii_mappings: msg.pii_mappings,
    created_at: msg.created_at,
    status: "synced" as const,
  }));

  const focusEmbed = getFocusActivationEmbed(example);
  const content = focusEmbed ? focusActivationContent(focusEmbed) : null;
  if (!focusEmbed || !content) return messages;

  // Keep checked-in public transcripts free of raw embed JSON while still
  // rendering the historical focus activation card in the interactive chat.
  const firstAssistantIndex = messages.findIndex((message) => message.role === "assistant");
  const insertAt = firstAssistantIndex >= 0 ? firstAssistantIndex : messages.length;
  const priorTimestamp = messages[Math.max(0, insertAt - 1)]?.created_at ?? Date.now() / 1000;
  const activationMessage: Message = {
    message_id: `${example.chat_id}-focus-mode-activation`,
    chat_id: example.chat_id,
    role: "assistant",
    content,
    category: example.category,
    model_name: "OpenMates",
    created_at: priorTimestamp + 1,
    status: "synced",
  };

  return [...messages.slice(0, insertAt), activationMessage, ...messages.slice(insertAt)];
}

// ============================================================================
// Pre-built lookup maps (built once at import time)
// ============================================================================

const chatById = new Map<string, ExampleChat>();
const chatBySlug = new Map<string, ExampleChat>();
const chatRecordById = new Map<string, { example: ExampleChatRecord; rootOrder: number }>();
const embedById = new Map<
  string,
  { embed: ExampleChatEmbed; chatId: string }
>();

for (const example of ALL_EXAMPLE_CHATS) {
  chatById.set(example.chat_id, example);
  chatBySlug.set(example.slug, example);
  chatRecordById.set(example.chat_id, { example, rootOrder: example.metadata.order });
  for (const embed of example.embeds) {
    embedById.set(embed.embed_id, { embed, chatId: example.chat_id });
  }
  for (const subChat of example.sub_chats ?? []) {
    chatRecordById.set(subChat.chat_id, { example: subChat, rootOrder: example.metadata.order });
    for (const embed of subChat.embeds) {
      embedById.set(embed.embed_id, { embed, chatId: subChat.chat_id });
    }
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
    const embeds = [
      ...example.embeds,
      ...(example.sub_chats ?? []).flatMap((subChat) => subChat.embeds),
    ];
    for (const embed of embeds) {
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
  return chatRecordById.has(chatId);
}

/** Get an example chat by ID */
export function getExampleChat(chatId: string): Chat | null {
  const record = chatRecordById.get(chatId);
  return record ? exampleChatToChat(record.example, record.rootOrder) : null;
}

/** Get an example chat by slug */
export function getExampleChatBySlug(slug: string): ExampleChat | undefined {
  return chatBySlug.get(slug);
}

/** Get messages for an example chat */
export function getExampleChatMessages(chatId: string): Message[] {
  const record = chatRecordById.get(chatId);
  return record ? exampleMessagesToMessages(record.example) : [];
}

/** Get embeds for an example chat */
export function getExampleChatEmbeds(chatId: string): ExampleChatEmbed[] {
  const record = chatRecordById.get(chatId);
  return record?.example.embeds ?? [];
}

/** Get static sub-chats for an example chat parent. */
export function getExampleSubChats(parentChatId: string): Chat[] {
  const parent = chatById.get(parentChatId);
  if (!parent?.sub_chats?.length) return [];
  return parent.sub_chats.map((subChat) => exampleChatToChat(subChat, parent.metadata.order));
}

/** Get a specific embed by ID from any example chat */
export function getExampleChatEmbed(embedId: string): ExampleChatEmbed | null {
  return embedById.get(embedId)?.embed ?? null;
}

/** Get all example chats as Chat objects (for sidebar listing) */
export function getAllExampleChats(): Chat[] {
  return ALL_EXAMPLE_CHATS.map(exampleChatToChat);
}

/** Get the most recently added example chats for compact sidebar display. */
export function getRecentExampleChats(limit = FEATURED_LIMIT): Chat[] {
  return ALL_EXAMPLE_CHATS.slice()
    .sort((a, b) => a.metadata.order - b.metadata.order)
    .slice(0, limit)
    .map(exampleChatToChat);
}

/** Get example chats explicitly linked to an app-store skill page. */
export function getExampleChatsForSkill(appId: string, skillId: string): Chat[] {
  const key = `${appId}.${skillId}`;
  return ALL_EXAMPLE_CHATS.filter((example) =>
    example.metadata.app_skill_examples?.includes(key),
  ).map(exampleChatToChat);
}

/** Get example chats explicitly linked to an app-store content type page. */
export function getExampleChatsForContentEmbed(appId: string, contentTypeId: string): Chat[] {
  const key = `${appId}.${contentTypeId}`;
  return ALL_EXAMPLE_CHATS.filter((example) =>
    example.metadata.content_embed_examples?.includes(key),
  ).map(exampleChatToChat);
}

/** Get example chats explicitly linked to an app-store focus mode page. */
export function getExampleChatsForFocusMode(appId: string, focusModeId: string): Chat[] {
  const key = `${appId}.${focusModeId}`;
  return ALL_EXAMPLE_CHATS.filter((example) =>
    example.metadata.app_focus_mode_examples?.includes(key),
  ).map(exampleChatToChat);
}

/** Get example chats explicitly linked to an app-store settings/memory page. */
export function getExampleChatsForSettingsMemory(appId: string, categoryId: string): Chat[] {
  const key = `${appId}.${categoryId}`;
  return ALL_EXAMPLE_CHATS.filter((example) =>
    example.metadata.app_settings_memory_examples?.includes(key),
  ).map(exampleChatToChat);
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
