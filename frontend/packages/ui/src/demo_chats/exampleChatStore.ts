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

// Import all example chats
import { giganticAirplanesChat } from "./data/example_chats/gigantic-airplanes";
import { artemisIIMissionChat } from "./data/example_chats/artemis-ii-mission";
import { beautifulSinglePageHtmlChat } from "./data/example_chats/beautiful-single-page-html";
import { flightsBerlinBangkokChat } from "./data/example_chats/flights-berlin-to-bangkok";
import { euChatControlLawChat } from "./data/example_chats/eu-chat-control-law-criticisms";
import { creativityDrawingMeetupsBerlinChat } from "./data/example_chats/creativity-drawing-meetups-berlin";
import { germanyHistoricFilmIndustryChat } from "./data/example_chats/germany-historic-film-industry";
import { buildingMaintenanceEmailChat } from "./data/example_chats/building-maintenance-email";
import { aiWorkshopsMeetupsBerlinChat } from "./data/example_chats/ai-workshops-meetups-berlin";
import { rightToRepairLawsEuUsChat } from "./data/example_chats/right-to-repair-laws-eu-us";
import { berlinWeatherBikeCommuteChat } from "./data/example_chats/berlin-weather-bike-commute";
import { quietCafesTempelhoferFeldChat } from "./data/example_chats/quiet-cafes-tempelhofer-feld";
import { ragExplainedVideosChat } from "./data/example_chats/rag-explained-videos";
import { mortgagePaymentCalculationChat } from "./data/example_chats/mortgage-payment-calculation";
import { rustVectorDatabaseReposChat } from "./data/example_chats/rust-vector-database-repos";
import { svelteRunesDocsChat } from "./data/example_chats/svelte-runes-docs";
import { familyStaysKyotoChat } from "./data/example_chats/family-stays-kyoto";
import { tedTalkTranscriptSummaryChat } from "./data/example_chats/ted-talk-transcript-summary";
import { balconyPlantReminderChat } from "./data/example_chats/balcony-plant-reminder";
import { buckConverters24v5vChat } from "./data/example_chats/buck-converters-24v-5v";
import { organicGroceriesBerlinChat } from "./data/example_chats/organic-groceries-berlin";
import { furnishedApartmentsBerlinChat } from "./data/example_chats/furnished-apartments-berlin";
import { sqliteStrictTablesSummaryChat } from "./data/example_chats/sqlite-strict-tables-summary";
import { privacyWebsiteHeroBackgroundChat } from "./data/example_chats/privacy-website-hero-background";
import { northstarMetricsSvgLogoChat } from "./data/example_chats/northstar-metrics-svg-logo";
import { pythonSquaresCodeRunChat } from "./data/example_chats/python-squares-code-run";
import { habitTrackerOnboardingDraftChat } from "./data/example_chats/habit-tracker-onboarding-draft";
import { chickpeaSpinachProteinDinnersChat } from "./data/example_chats/chickpea-spinach-protein-dinners";
import { openmatesAppSkillsEmbedsDocsChat } from "./data/example_chats/openmates-app-skills-embeds-docs";
import { openmatesAddAppSkillDocChat } from "./data/example_chats/openmates-add-app-skill-doc";
import { nonprofitEventPlanningUseCaseChat } from "./data/example_chats/nonprofit-event-planning-use-case";
import { lh400FlightStatusCheckChat } from "./data/example_chats/lh400-flight-status-check";
import { berlinDermatologyAppointmentsChat } from "./data/example_chats/berlin-dermatology-appointments";
import { productLaunchSynthLoopChat } from "./data/example_chats/product-launch-synth-loop";
import { privateWorkspaceDemoVideoChat } from "./data/example_chats/private-workspace-demo-video";
import { upcomingRemindersListChat } from "./data/example_chats/upcoming-reminders-list";
import { cancelTestReminderChat } from "./data/example_chats/cancel-test-reminder";
import { fediverseActivitypubSocialSearchChat } from "./data/example_chats/fediverse-activitypub-social-search";
import { mastodonAccountRecentPostsChat } from "./data/example_chats/mastodon-account-recent-posts";
import { habitGardenViteAppChat } from "./data/example_chats/habit-garden-vite-app";
import { pdfReadSecretWordChat } from "./data/example_chats/pdf-read-secret-word";
import { pdfViewPageLayoutChat } from "./data/example_chats/pdf-view-page-layout";
import { pdfSearchEncryptionChat } from "./data/example_chats/pdf-search-encryption";
import { imageVectorizeOpenmatesHeaderChat } from "./data/example_chats/image-vectorize-openmates-header";
import { audioTranscribeVoiceNoteChat } from "./data/example_chats/audio-transcribe-voice-note";
import { usEggPricesDeepResearchChat } from "./data/example_chats/us-egg-prices-deep-research";
import { frameworkStoreReputationCheckChat } from "./data/example_chats/framework-store-reputation-check";
import { frontendDeveloperCareerPivotChat } from "./data/example_chats/frontend-developer-career-pivot";
import { memoryAiCommunicationStyleChat } from "./data/example_chats/memory-ai-communication-style";
import { memoryAiLearningPreferencesChat } from "./data/example_chats/memory-ai-learning-preferences";
import { memoryBooksFavoriteBooksChat } from "./data/example_chats/memory-books-favorite-books";
import { memoryBooksCurrentlyReadingChat } from "./data/example_chats/memory-books-currently-reading";
import { memoryBooksToReadListChat } from "./data/example_chats/memory-books-to-read-list";
import { memoryCodePreferredTechChat } from "./data/example_chats/memory-code-preferred-tech";
import { memoryCodeProjectsChat } from "./data/example_chats/memory-code-projects";
import { memoryCodeWantToLearnChat } from "./data/example_chats/memory-code-want-to-learn";
import { memoryCodeCodingSetupChat } from "./data/example_chats/memory-code-coding-setup";
import { memoryDocsWritingStyleChat } from "./data/example_chats/memory-docs-writing-style";
import { memoryEventsSavedEventsChat } from "./data/example_chats/memory-events-saved-events";
import { memoryHealthAppointmentsChat } from "./data/example_chats/memory-health-appointments";
import { memoryHealthMedicalHistoryChat } from "./data/example_chats/memory-health-medical-history";
import { memoryHomeSavedListingsChat } from "./data/example_chats/memory-home-saved-listings";
import { memoryImagesPreferredStylesChat } from "./data/example_chats/memory-images-preferred-styles";
import { memoryMailWritingStylesChat } from "./data/example_chats/memory-mail-writing-styles";
import { memoryReminderDefaultsChat } from "./data/example_chats/memory-reminder-defaults";
import { memoryStudyLearningGoalsChat } from "./data/example_chats/memory-study-learning-goals";
import { memoryTravelSavedConnectionsChat } from "./data/example_chats/memory-travel-saved-connections";
import { memoryTravelSavedStaysChat } from "./data/example_chats/memory-travel-saved-stays";
import { memoryTravelTripsChat } from "./data/example_chats/memory-travel-trips";
import { memoryTravelPreferredAirlinesChat } from "./data/example_chats/memory-travel-preferred-airlines";
import { memoryTravelPreferredTransportChat } from "./data/example_chats/memory-travel-preferred-transport";
import { memoryTravelPreferredActivitiesChat } from "./data/example_chats/memory-travel-preferred-activities";
import { memoryTvWatchedMoviesChat } from "./data/example_chats/memory-tv-watched-movies";
import { memoryTvWatchedShowsChat } from "./data/example_chats/memory-tv-watched-shows";
import { memoryTvToWatchListChat } from "./data/example_chats/memory-tv-to-watch-list";
import { memoryVideosToWatchListChat } from "./data/example_chats/memory-videos-to-watch-list";
import { memoryWebBookmarksChat } from "./data/example_chats/memory-web-bookmarks";
import { memoryWebReadLaterChat } from "./data/example_chats/memory-web-read-later";

// ============================================================================
// ALL EXAMPLE CHATS — add new chats here
// ============================================================================

const ALL_EXAMPLE_CHATS: ExampleChat[] = [
  giganticAirplanesChat,
  artemisIIMissionChat,
  beautifulSinglePageHtmlChat,
  flightsBerlinBangkokChat,
  euChatControlLawChat,
  creativityDrawingMeetupsBerlinChat,
  germanyHistoricFilmIndustryChat,
  buildingMaintenanceEmailChat,
  aiWorkshopsMeetupsBerlinChat,
  rightToRepairLawsEuUsChat,
  berlinWeatherBikeCommuteChat,
  quietCafesTempelhoferFeldChat,
  ragExplainedVideosChat,
  mortgagePaymentCalculationChat,
  rustVectorDatabaseReposChat,
  svelteRunesDocsChat,
  familyStaysKyotoChat,
  tedTalkTranscriptSummaryChat,
  balconyPlantReminderChat,
  buckConverters24v5vChat,
  organicGroceriesBerlinChat,
  furnishedApartmentsBerlinChat,
  sqliteStrictTablesSummaryChat,
  privacyWebsiteHeroBackgroundChat,
  northstarMetricsSvgLogoChat,
  pythonSquaresCodeRunChat,
  habitTrackerOnboardingDraftChat,
  chickpeaSpinachProteinDinnersChat,
  openmatesAppSkillsEmbedsDocsChat,
  openmatesAddAppSkillDocChat,
  nonprofitEventPlanningUseCaseChat,
  lh400FlightStatusCheckChat,
  berlinDermatologyAppointmentsChat,
  productLaunchSynthLoopChat,
  privateWorkspaceDemoVideoChat,
  upcomingRemindersListChat,
  cancelTestReminderChat,
  fediverseActivitypubSocialSearchChat,
  mastodonAccountRecentPostsChat,
  habitGardenViteAppChat,
  pdfReadSecretWordChat,
  pdfViewPageLayoutChat,
  pdfSearchEncryptionChat,
  imageVectorizeOpenmatesHeaderChat,
  audioTranscribeVoiceNoteChat,
  usEggPricesDeepResearchChat,
  frameworkStoreReputationCheckChat,
  frontendDeveloperCareerPivotChat,
  memoryAiCommunicationStyleChat,
  memoryAiLearningPreferencesChat,
  memoryBooksFavoriteBooksChat,
  memoryBooksCurrentlyReadingChat,
  memoryBooksToReadListChat,
  memoryCodePreferredTechChat,
  memoryCodeProjectsChat,
  memoryCodeWantToLearnChat,
  memoryCodeCodingSetupChat,
  memoryDocsWritingStyleChat,
  memoryEventsSavedEventsChat,
  memoryHealthAppointmentsChat,
  memoryHealthMedicalHistoryChat,
  memoryHomeSavedListingsChat,
  memoryImagesPreferredStylesChat,
  memoryMailWritingStylesChat,
  memoryReminderDefaultsChat,
  memoryStudyLearningGoalsChat,
  memoryTravelSavedConnectionsChat,
  memoryTravelSavedStaysChat,
  memoryTravelTripsChat,
  memoryTravelPreferredAirlinesChat,
  memoryTravelPreferredTransportChat,
  memoryTravelPreferredActivitiesChat,
  memoryTvWatchedMoviesChat,
  memoryTvWatchedShowsChat,
  memoryTvToWatchListChat,
  memoryVideosToWatchListChat,
  memoryWebBookmarksChat,
  memoryWebReadLaterChat,
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
  return example.messages.map((msg) => ({
    message_id: msg.id,
    chat_id: example.chat_id,
    role: msg.role as "user" | "assistant",
    content: translate(msg.content),
    category: msg.category,
    model_name: msg.model_name,
    pii_mappings: msg.pii_mappings,
    created_at: msg.created_at,
    status: "synced" as const,
  }));
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
