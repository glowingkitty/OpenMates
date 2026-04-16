import type { DemoChat } from "./types";
import { forEveryoneChat } from "./data/for_everyone";
import { forDevelopersChat } from "./data/for_developers";
import { whoDevelopsOpenmatesChat } from "./data/who_develops_openmates";
import { LEGAL_CHATS } from "../legal";
import {
  getNewsletterChatById as _getNewsletterChatById,
  getAllActiveNewsletterChats as _getAllActiveNewsletterChats,
} from "./newsletterChatStore";

// Export types
export type { DemoChat, DemoMessage, ExampleChat, ExampleChatEmbed, ExampleChatMessage } from "./types";

// Export conversion utilities
export {
  convertDemoChatToChat,
  convertDemoMessagesToMessages,
  getDemoMessages,
  isDemoChat,
  isLegalChat,
  isPublicChat,
} from "./convertToChat";

// Export translation utilities (for i18n support)
export { translateDemoChat, translateDemoChats } from "./translateDemoChat";

// Export legal chats for use in components
export { LEGAL_CHATS, getLegalChatBySlug, getLegalChatById } from "../legal";

// Export example chat store — static hardcoded example chats (replaces old communityDemoStore)
export {
  isExampleChat,
  getExampleChat,
  getExampleChatBySlug,
  getExampleChatMessages,
  getExampleChatEmbeds,
  getExampleChatEmbed,
  getAllExampleChats,
  getFeaturedExampleChats,
  getExampleChatData,
  getAllExampleChatData,
  getExampleChatCount,
  registerExampleChatEmbedRefs,
} from "./exampleChatStore";

// Export newsletter chat store — DemoChats generated from newsletter issues.
// Each issue of Updates & Announcements or Tips & Tricks becomes one entry.
export {
  ALL_NEWSLETTER_CHATS,
  getNewsletterChatById,
  getNewsletterChatBySlug,
  getAllActiveNewsletterChats,
  getActiveNewsletterChatsByKind,
  newsletterKindFromChatId,
} from "./newsletterChatStore";
export type { NewsletterKind } from "./newsletterChatStore";

/** Load published default Daily Inspirations from server on page load. */
export { loadDefaultInspirations } from "./loadDefaultInspirations";

/**
 * Intro chats shown in sidebar for new/non-authenticated users
 * (excluding legal docs - they're accessed via dedicated routes)
 *
 * NAMING CONVENTION:
 * - INTRO_CHATS: Static intro chats bundled with the app (welcome, what-makes-different, etc.)
 * - Example chats: Static example chats reproduced from real conversations (in exampleChatStore)
 *
 * IMPORTANT: ALL intro chats use translation keys from i18n/locales/{locale}.json
 * You MUST use translateDemoChat() or translateDemoChats() to resolve translations at runtime.
 */
export const INTRO_CHATS: DemoChat[] = [
  forEveryoneChat,
  forDevelopersChat,
  whoDevelopsOpenmatesChat,
  // Privacy, Terms, Imprint are NOT intro chats - they're accessed via /privacy, /terms, /imprint routes
].sort((a, b) => a.metadata.order - b.metadata.order);

// Legacy alias for backwards compatibility - prefer using INTRO_CHATS
export const DEMO_CHATS = INTRO_CHATS;

// Helper functions to find intro chats
export function getIntroChatBySlug(slug: string): DemoChat | undefined {
  return INTRO_CHATS.find((chat) => chat.slug === slug);
}

export function getIntroChatById(id: string): DemoChat | undefined {
  return INTRO_CHATS.find((chat) => chat.chat_id === id);
}

export function getFeaturedIntroChats(): DemoChat[] {
  return INTRO_CHATS.filter((chat) => chat.metadata.featured);
}

// Legacy aliases for backwards compatibility
export const getDemoChatBySlug = getIntroChatBySlug;
export const getDemoChatById = getIntroChatById;
export const getFeaturedDemoChats = getFeaturedIntroChats;

/**
 * Get a public chat (intro, legal, or newsletter) by ID.
 * Searches INTRO_CHATS, LEGAL_CHATS, and ALL_NEWSLETTER_CHATS.
 */
export function getPublicChatById(id: string): DemoChat | undefined {
  return (
    getIntroChatById(id) ||
    LEGAL_CHATS.find((chat) => chat.chat_id === id) ||
    _getNewsletterChatById(id)
  );
}

/**
 * Get all public chats (intro + legal + newsletter) combined
 * Useful for loading messages from static bundle
 */
export function getAllPublicChats(): DemoChat[] {
  return [...INTRO_CHATS, ...LEGAL_CHATS, ..._getAllActiveNewsletterChats()];
}
