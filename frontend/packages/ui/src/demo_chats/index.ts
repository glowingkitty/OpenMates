import type { DemoChat } from "./types";
import { forEveryoneChat } from "./data/for_everyone";
import { forDevelopersChat } from "./data/for_developers";
import { whoDevelopsOpenmatesChat } from "./data/who_develops_openmates";
import { LEGAL_CHATS } from "../legal";

// Export types
export type { DemoChat, DemoMessage } from "./types";

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

// Export community demo store for in-memory storage of server-fetched demo chats
// ARCHITECTURE: Community demos are stored in-memory AND IndexedDB for offline support
export {
  communityDemoStore,
  addCommunityDemo,
  getCommunityDemoChat,
  getCommunityDemoMessages,
  getCommunityDemoEmbeds,
  getCommunityDemoEmbed,
  getAllCommunityDemoChats,
  isCommunityDemo,
  clearCommunityDemos,
  getLocalContentHashes,
} from "./communityDemoStore";

/**
 * Intro chats shown in sidebar for new/non-authenticated users
 * (excluding legal docs - they're accessed via dedicated routes)
 *
 * NAMING CONVENTION:
 * - INTRO_CHATS: Static intro chats bundled with the app (welcome, what-makes-different, etc.)
 * - Community demos: Dynamic demo chats fetched from server, stored in communityDemoStore
 *
 * IMPORTANT: ALL intro chats use translation keys from i18n/locales/{locale}.json
 * You MUST use translateDemoChat() or translateDemoChats() to resolve translations at runtime.
 */
export const INTRO_CHATS: DemoChat[] = [
  forEveryoneChat,
  forDevelopersChat,
  whoDevelopsOpenmatesChat,
  // Privacy, Terms, Imprint are NOT intro chats - they're accessed via /privacy, /terms, /imprint routes
  // More will be added: october-2025-updates, example-learn-something, stay-up-to-date
  // Apps feature: example-power-of-apps (coming soon when Apps are implemented)
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
 * Get a public chat (intro or legal) by ID
 * Searches both INTRO_CHATS and LEGAL_CHATS
 */
export function getPublicChatById(id: string): DemoChat | undefined {
  return (
    getIntroChatById(id) || LEGAL_CHATS.find((chat) => chat.chat_id === id)
  );
}

/**
 * Get all public chats (intro + legal) combined
 * Useful for loading messages from static bundle
 */
export function getAllPublicChats(): DemoChat[] {
  return [...INTRO_CHATS, ...LEGAL_CHATS];
}
