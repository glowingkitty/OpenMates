// frontend/packages/ui/src/components/enter_message/services/mentionSearchService.ts
//
// Service for searching across all mentionable items in the @ dropdown.
// Provides unified search across AI models, mates, app skills, focus modes, and settings/memories.
//
// IMPORTANT: Search terms include translations for the current UI language, allowing users
// to search for mates/categories in their own language (e.g., searching "Gerd" in German
// will find the business_development mate whose German name is "Gerd").

import { modelsMetadata } from "../../../data/modelsMetadata";
import { matesMetadata } from "../../../data/matesMetadata";
import { getProviderIconUrl } from "../../../data/providerIcons";
import { appSkillsStore } from "../../../stores/appSkillsStore";
import { get } from "svelte/store";
import { appSettingsMemoriesStore } from "../../../stores/appSettingsMemoriesStore";
import { isProviderHealthy } from "../../../stores/appHealthStore";
import { text } from "../../../i18n/translations";
import { userProfile } from "../../../stores/userProfile";

/**
 * Types of mentionable items in the @ dropdown.
 */
export type MentionType =
  | "model"
  | "mate"
  | "skill"
  | "focus_mode"
  | "settings_memory"
  | "settings_memory_entry";

/**
 * Base interface for all mention search results.
 */
export interface MentionResult {
  /** Unique identifier for this result */
  id: string;
  /** Type of mentionable item */
  type: MentionType;
  /** Primary display text for dropdown (may be translation key) */
  displayName: string;
  /** Hyphenated display name for editor (e.g., '@Claude-4.5-Opus') */
  mentionDisplayName: string;
  /** Secondary display text (description or subtitle) */
  subtitle: string;
  /** Icon or image identifier for display */
  icon: string;
  /** Additional icon class or color gradient */
  iconStyle?: string;
  /** The mention syntax for backend (e.g., '@ai-model:claude-4-sonnet') */
  mentionSyntax: string;
  /** Search keywords for matching (lowercase) */
  searchTerms: string[];
  /** Match score for sorting results (higher = better match) */
  score?: number;
}

/**
 * Model mention result with additional model-specific data.
 */
export interface ModelMentionResult extends MentionResult {
  type: "model";
  /** Provider name for display */
  providerName: string;
  /** Model tier for styling */
  tier: "economy" | "standard" | "premium";
}

/**
 * Mate mention result with profile data.
 */
export interface MateMentionResult extends MentionResult {
  type: "mate";
  /** CSS class for profile image */
  profileClass: string;
  /** Translation key for name (needs to be resolved) */
  nameTranslationKey: string;
  /** Color gradient start for the mate */
  colorStart: string;
  /** Color gradient end for the mate */
  colorEnd: string;
}

/**
 * Skill mention result with app context.
 */
export interface SkillMentionResult extends MentionResult {
  type: "skill";
  /** App ID this skill belongs to */
  appId: string;
  /** App icon gradient or image */
  appIcon: string;
  /** Color gradient start from app config */
  colorStart?: string;
  /** Color gradient end from app config */
  colorEnd?: string;
}

/**
 * Focus mode mention result.
 */
export interface FocusModeMentionResult extends MentionResult {
  type: "focus_mode";
  /** App ID this focus mode belongs to */
  appId: string;
  /** App icon gradient or image */
  appIcon: string;
  /** Color gradient start from app config */
  colorStart?: string;
  /** Color gradient end from app config */
  colorEnd?: string;
}

/**
 * Settings/memory category mention result (selects the whole category).
 */
export interface SettingsMemoryMentionResult extends MentionResult {
  type: "settings_memory";
  /** App ID this setting belongs to */
  appId: string;
  /** App icon gradient or image */
  appIcon: string;
  /** Memory type (e.g., 'list', 'single') */
  memoryType: string;
  /** Memory category ID (e.g., 'preferred_technologies') */
  memoryCategoryId: string;
  /** Number of user entries in this category */
  entryCount: number;
  /** Color gradient start from app config */
  colorStart?: string;
  /** Color gradient end from app config */
  colorEnd?: string;
}

/**
 * Individual settings/memory entry mention result.
 * Selects a single entry within a category (e.g., one specific technology).
 */
export interface SettingsMemoryEntryMentionResult extends MentionResult {
  type: "settings_memory_entry";
  /** App ID this entry belongs to */
  appId: string;
  /** App icon gradient or image */
  appIcon: string;
  /** Memory category ID (e.g., 'preferred_technologies') */
  memoryCategoryId: string;
  /** The unique entry ID */
  entryId: string;
  /** Title field from the entry (e.g., "React") */
  entryTitle: string;
  /** Subtitle field from the entry (e.g., "Expert") */
  entrySubtitle?: string;
  /** Color gradient start from app config */
  colorStart?: string;
  /** Color gradient end from app config */
  colorEnd?: string;
}

/**
 * Union type for all mention results.
 */
export type AnyMentionResult =
  | ModelMentionResult
  | MateMentionResult
  | SkillMentionResult
  | FocusModeMentionResult
  | SettingsMemoryMentionResult
  | SettingsMemoryEntryMentionResult;

/**
 * Convert a name to hyphenated format for mention display.
 * e.g., "Claude 4.5 Opus" -> "Claude-4.5-Opus"
 * e.g., "Get Docs" -> "Get-Docs"
 */
function toHyphenatedName(name: string): string {
  return name.replace(/\s+/g, "-");
}

/**
 * Capitalize first letter of each word for display.
 * e.g., "get-docs" -> "Get-Docs"
 */
function capitalizeWords(str: string): string {
  return str
    .split("-")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join("-");
}

/**
 * Build search terms from a string by extracting words and variations.
 */
function buildSearchTerms(...strings: (string | undefined)[]): string[] {
  const terms: string[] = [];
  for (const str of strings) {
    if (!str) continue;
    const lower = str.toLowerCase();
    terms.push(lower);
    // Add individual words
    const words = lower.split(/[\s\-_]+/).filter((w) => w.length > 1);
    terms.push(...words);
  }
  return Array.from(new Set(terms)); // Remove duplicates
}

/** Score boost for settings/memory categories and entries when the query matches (so they can appear in results). */
const SETTINGS_MEMORY_SCORE_BOOST = 30;

/**
 * Calculate match score for a search query against terms.
 * Higher score = better match.
 * Settings/memory results get a small boost when they match so they can compete with models/skills.
 */
function calculateMatchScore(
  query: string,
  terms: string[],
  type?: MentionType,
): number {
  if (!query) return 1; // No query = all results are equal

  const queryLower = query.toLowerCase();
  let score = 0;

  for (const term of terms) {
    if (term === queryLower) {
      score += 100; // Exact match
    } else if (term.startsWith(queryLower)) {
      score += 50; // Prefix match
    } else if (term.includes(queryLower)) {
      score += 25; // Contains match
    }
  }

  // Boost settings/memory types when they match so they can appear and be selected
  if (
    score > 0 &&
    (type === "settings_memory" || type === "settings_memory_entry")
  ) {
    score += SETTINGS_MEMORY_SCORE_BOOST;
  }

  return score;
}

/**
 * Convert AI model metadata to mention results.
 * Filters to only include models for the "ai.ask" skill (text generation models).
 * Also filters out models whose provider is unhealthy (if health data is available).
 * Additionally filters out models that the user has disabled in their settings.
 *
 * **Offline-First**: If health data is unavailable (server unreachable), all models are shown.
 */
function getModelMentionResults(): ModelMentionResult[] {
  // Get the provider health checker function
  const checkProviderHealthy = get(isProviderHealthy);

  // Get user's disabled models list (defaults to empty array if not set)
  const profile = get(userProfile);
  const disabledModels = profile.disabled_ai_models || [];

  return (
    modelsMetadata
      // Filter to only include models for the "ai.ask" skill (excludes image generation models)
      .filter((model) => model.for_app_skill === "ai.ask")
      // Filter by provider health (offline-first: shows all if health data unavailable)
      .filter((model) => checkProviderHealthy(model.provider_id))
      // Filter out models that user has disabled in settings
      .filter((model) => !disabledModels.includes(model.id))
      .map((model) => ({
        id: model.id,
        type: "model" as const,
        displayName: model.name,
        // Hyphenated for editor display: "Claude 4.5 Opus" -> "Claude-4.5-Opus"
        mentionDisplayName: toHyphenatedName(model.name),
        subtitle: model.provider_name,
        icon: getProviderIconUrl(model.logo_svg),
        // Backend syntax for processing - the actual text stored/sent
        mentionSyntax: `@ai-model:${model.id}`,
        searchTerms: buildSearchTerms(
          model.name,
          model.provider_name,
          model.description,
          model.id,
          // Include search aliases (e.g., "chatgpt" for OpenAI models)
          ...(model.search_aliases || []),
        ),
        providerName: model.provider_name,
        tier: model.tier,
      }))
  );
}

/**
 * Convert mate metadata to mention results.
 * Includes translated names and descriptions in search terms so users can search
 * in their current UI language (e.g., "Gerd" finds business_development in German).
 */
function getMateMentionResults(): MateMentionResult[] {
  // Get the current translation function from the text store
  const $text = get(text);

  return matesMetadata.map((mate) => {
    // Resolve translated name and description for search indexing
    // This allows searching by the mate's name in the current UI language
    const translatedName = $text(mate.name_translation_key);
    const translatedDescription = $text(mate.description_translation_key);

    // Build search terms including both English keywords and translated values
    const searchTerms = buildSearchTerms(
      mate.id,
      mate.profile_class,
      // Include all search names (English name + expertise keywords)
      ...mate.search_names,
      // Include translated name (e.g., "Gerd" for business_development in German)
      translatedName,
      // Include translated description for expertise searches
      // (e.g., "Geschäftsentwicklung" for business development in German)
      translatedDescription,
    );

    return {
      id: mate.id,
      type: "mate" as const,
      displayName: mate.name_translation_key, // Will be resolved by component
      // Use translated name for display in the mention editor
      mentionDisplayName: capitalizeWords(
        translatedName || mate.search_names[0] || mate.id,
      ),
      subtitle: mate.description_translation_key,
      icon: "mate-profile",
      iconStyle: mate.profile_class,
      mentionSyntax: `@mate:${mate.id}`,
      searchTerms,
      profileClass: mate.profile_class,
      nameTranslationKey: mate.name_translation_key,
      colorStart: mate.color_start,
      colorEnd: mate.color_end,
    };
  });
}

/**
 * Convert app skills to mention results.
 * Includes translated names in search terms for localized search.
 */
function getSkillMentionResults(): SkillMentionResult[] {
  const results: SkillMentionResult[] = [];
  const apps = appSkillsStore.apps;
  const $text = get(text);

  for (const [appId, app] of Object.entries(apps)) {
    const appIcon = app.icon_image || "default-app.svg";
    // Capitalize app name: "code" -> "Code"
    const appDisplayName = capitalizeWords(appId);

    for (const skill of app.skills) {
      // Hyphenated: "Code-Get-Docs" (app name + skill id with hyphens)
      const skillDisplayName = capitalizeWords(skill.id.replace(/_/g, "-"));

      // Resolve translated name and description for search indexing
      const translatedName = $text(skill.name_translation_key);
      const translatedDescription = $text(skill.description_translation_key);

      results.push({
        id: `${appId}:${skill.id}`,
        type: "skill" as const,
        displayName: skill.name_translation_key,
        // Format: "App-Skill-Name" e.g., "Code-Get-Docs"
        mentionDisplayName: `${appDisplayName}-${skillDisplayName}`,
        subtitle: skill.description_translation_key,
        icon: appIcon,
        iconStyle: app.icon_colorgradient
          ? `linear-gradient(135deg, ${app.icon_colorgradient.start} 9.04%, ${app.icon_colorgradient.end} 90.06%)`
          : undefined,
        mentionSyntax: `@skill:${appId}:${skill.id}`,
        searchTerms: buildSearchTerms(
          skill.id,
          appId,
          app.name,
          // Include translated names for localized search
          translatedName,
          translatedDescription,
        ),
        appId,
        appIcon,
        colorStart: app.icon_colorgradient?.start,
        colorEnd: app.icon_colorgradient?.end,
      });
    }
  }

  return results;
}

/**
 * Convert focus modes to mention results.
 * Includes translated names in search terms for localized search.
 */
function getFocusModeMentionResults(): FocusModeMentionResult[] {
  const results: FocusModeMentionResult[] = [];
  const apps = appSkillsStore.apps;
  const $text = get(text);

  for (const [appId, app] of Object.entries(apps)) {
    const appIcon = app.icon_image || "default-app.svg";
    // Capitalize app name: "web" -> "Web"
    const appDisplayName = capitalizeWords(appId);

    for (const focusMode of app.focus_modes) {
      // Hyphenated: "Web-Research" (app name + focus mode id with hyphens)
      const focusDisplayName = capitalizeWords(focusMode.id.replace(/_/g, "-"));

      // Resolve translated name and description for search indexing
      const translatedName = $text(focusMode.name_translation_key);
      const translatedDescription = $text(
        focusMode.description_translation_key,
      );

      results.push({
        id: `${appId}:${focusMode.id}`,
        type: "focus_mode" as const,
        displayName: focusMode.name_translation_key,
        // Format: "App-FocusMode" e.g., "Web-Research"
        mentionDisplayName: `${appDisplayName}-${focusDisplayName}`,
        subtitle: focusMode.description_translation_key,
        icon: appIcon,
        iconStyle: app.icon_colorgradient
          ? `linear-gradient(135deg, ${app.icon_colorgradient.start} 9.04%, ${app.icon_colorgradient.end} 90.06%)`
          : undefined,
        mentionSyntax: `@focus:${appId}:${focusMode.id}`,
        searchTerms: buildSearchTerms(
          focusMode.id,
          appId,
          app.name,
          // Include translated names for localized search
          translatedName,
          translatedDescription,
        ),
        appId,
        appIcon,
        colorStart: app.icon_colorgradient?.start,
        colorEnd: app.icon_colorgradient?.end,
      });
    }
  }

  return results;
}

/**
 * Convert settings/memories metadata to mention results.
 * Only includes memory types that the user has entries for.
 * Includes translated names in search terms for localized search.
 */
function getSettingsMemoryMentionResults(): SettingsMemoryMentionResult[] {
  const results: SettingsMemoryMentionResult[] = [];
  const apps = appSkillsStore.apps;
  const $text = get(text);

  // Get user's settings/memories entries grouped by app
  const storeState = get(appSettingsMemoriesStore);
  
  // Count entries per app:item_type for entry counts
  const entryCountMap = new Map<string, number>();
  storeState.entries.forEach((entry: { app_id: string; item_type: string }) => {
    const key = `${entry.app_id}:${entry.item_type}`;
    entryCountMap.set(key, (entryCountMap.get(key) || 0) + 1);
  });

  for (const [appId, app] of Object.entries(apps)) {
    const appIcon = app.icon_image || "default-app.svg";
    // Capitalize app name: "code" -> "Code"
    const appDisplayName = capitalizeWords(appId);

    for (const memory of app.settings_and_memories) {
      // Only include if user has entries for this memory type
      const categoryKey = `${appId}:${memory.id}`;
      const entryCount = entryCountMap.get(categoryKey) || 0;
      if (entryCount === 0) continue;

      // Hyphenated: "Code-Projects" (app name + memory id with hyphens)
      const memoryDisplayName = capitalizeWords(memory.id.replace(/_/g, "-"));

      // Resolve translated name and description for search indexing
      const translatedName = $text(memory.name_translation_key);
      const translatedDescription = $text(memory.description_translation_key);

      results.push({
        id: `${appId}:${memory.id}`,
        type: "settings_memory" as const,
        displayName: memory.name_translation_key,
        // Format: "App-MemoryName" e.g., "Code-Projects"
        mentionDisplayName: `${appDisplayName}-${memoryDisplayName}`,
        subtitle: memory.description_translation_key,
        icon: appIcon,
        iconStyle: app.icon_colorgradient
          ? `linear-gradient(135deg, ${app.icon_colorgradient.start} 9.04%, ${app.icon_colorgradient.end} 90.06%)`
          : undefined,
        // Include memory type in syntax so backend knows the specific type
        // Format: @memory:app_id:memory_id:memory_type
        mentionSyntax: `@memory:${appId}:${memory.id}:${memory.type}`,
        searchTerms: buildSearchTerms(
          memory.id,
          appId,
          app.name,
          // Include translated names for localized search
          translatedName,
          translatedDescription,
        ),
        appId,
        appIcon,
        memoryCategoryId: memory.id,
        memoryType: memory.type,
        entryCount,
        colorStart: app.icon_colorgradient?.start,
        colorEnd: app.icon_colorgradient?.end,
      });
    }
  }

  return results;
}

/**
 * Get individual entry mention results for a specific settings/memory category.
 * Returns decrypted entries with their title/subtitle fields extracted from schema.
 * Used by the dropdown to show expandable entries under a category.
 *
 * @param appId - App ID (e.g., "code")
 * @param memoryCategoryId - Category ID (e.g., "preferred_technologies")
 * @param limit - Maximum entries to return (default 5)
 */
export function getSettingsMemoryEntryResults(
  appId: string,
  memoryCategoryId: string,
  limit: number = 5,
): { entries: SettingsMemoryEntryMentionResult[]; totalCount: number } {
  const storeState = get(appSettingsMemoriesStore);
  const apps = appSkillsStore.apps;
  const app = apps[appId];
  if (!app) return { entries: [], totalCount: 0 };

  const appIcon = app.icon_image || "default-app.svg";
  const appDisplayName = capitalizeWords(appId);

  // Find the memory field metadata to get schema (for title/subtitle fields)
  const memoryMeta = app.settings_and_memories.find(
    (m) => m.id === memoryCategoryId,
  );
  const schema = memoryMeta?.schema_definition;

  // Identify which properties are is_title and is_subtitle
  let titleField: string | null = null;
  let subtitleField: string | null = null;
  if (schema?.properties) {
    for (const [key, prop] of Object.entries(schema.properties)) {
      if (prop.is_title) titleField = key;
      if (prop.is_subtitle) subtitleField = key;
    }
  }

  // Get decrypted entries for this app + category
  const allDecryptedEntries = Array.from(storeState.decryptedEntries.values());
  const categoryEntries = allDecryptedEntries.filter(
    (entry) =>
      entry.app_id === appId && entry.settings_group === memoryCategoryId,
  );

  const totalCount = categoryEntries.length;
  const limitedEntries = categoryEntries.slice(0, limit);

  const results: SettingsMemoryEntryMentionResult[] = limitedEntries.map(
    (entry) => {
      // Extract title and subtitle from item_value based on schema
      const entryTitle = titleField
        ? String(entry.item_value[titleField] || entry.item_key)
        : entry.item_key;
      const entrySubtitle = subtitleField
        ? String(entry.item_value[subtitleField] || "")
        : undefined;

      const entryDisplayName = capitalizeWords(
        entryTitle.replace(/\s+/g, "-"),
      );

      return {
        id: `${appId}:${memoryCategoryId}:${entry.id}`,
        type: "settings_memory_entry" as const,
        displayName: entryTitle,
        mentionDisplayName: `${appDisplayName}-${entryDisplayName}`,
        subtitle: entrySubtitle || "",
        icon: appIcon,
        iconStyle: app.icon_colorgradient
          ? `linear-gradient(135deg, ${app.icon_colorgradient.start} 9.04%, ${app.icon_colorgradient.end} 90.06%)`
          : undefined,
        // Individual entry syntax: @memory-entry:app_id:category_id:entry_id
        mentionSyntax: `@memory-entry:${appId}:${memoryCategoryId}:${entry.id}`,
        searchTerms: buildSearchTerms(entryTitle, entrySubtitle),
        appId,
        appIcon,
        memoryCategoryId,
        entryId: entry.id,
        entryTitle,
        entrySubtitle: entrySubtitle || undefined,
        colorStart: app.icon_colorgradient?.start,
        colorEnd: app.icon_colorgradient?.end,
      };
    },
  );

  return { entries: results, totalCount };
}

/**
 * Get all individual settings/memory entry mention results across all categories.
 * Used by the search function so users can find individual entries by name (e.g., "@react").
 */
function getAllSettingsMemoryEntryResults(): SettingsMemoryEntryMentionResult[] {
  const categories = getSettingsMemoryMentionResults();
  const allEntries: SettingsMemoryEntryMentionResult[] = [];
  for (const category of categories) {
    const { entries } = getSettingsMemoryEntryResults(
      category.appId,
      category.memoryCategoryId,
      100, // Get all entries for search indexing
    );
    allEntries.push(...entries);
  }
  return allEntries;
}

/**
 * Get all mention results across all types (including individual entries).
 */
export function getAllMentionResults(): AnyMentionResult[] {
  return [
    ...getModelMentionResults(),
    ...getMateMentionResults(),
    ...getSkillMentionResults(),
    ...getFocusModeMentionResults(),
    ...getSettingsMemoryMentionResults(),
    ...getAllSettingsMemoryEntryResults(),
  ];
}

/**
 * Get default mention results to show when @ is typed without any search query.
 * Shows top 4 most popular AI models (the most common use case).
 */
export function getDefaultMentionResults(): AnyMentionResult[] {
  return getModelMentionResults().slice(0, 4);
}

/** Larger limit when user is searching so settings/memories and entries can appear. */
const SEARCH_RESULT_LIMIT = 8;

/**
 * Search mention results by query string.
 * Returns results sorted by match score (best matches first).
 * Default selection is unchanged (4 models when query is empty).
 * When the user types a query, a larger limit and score boost for settings/memories
 * ensure categories and individual entries can be found and selected.
 *
 * @param query - Search query string (text after @)
 * @param limit - Maximum number of results when query is non-empty (default: 8); ignored when query is empty
 */
export function searchMentions(
  query: string,
  limit: number = SEARCH_RESULT_LIMIT,
): AnyMentionResult[] {
  if (!query || query.trim() === "") {
    return getDefaultMentionResults();
  }

  const allResults = getAllMentionResults();

  // Score and filter results (settings_memory / settings_memory_entry get a boost when they match)
  const scoredResults = allResults
    .map((result) => ({
      ...result,
      score: calculateMatchScore(
        query,
        result.searchTerms,
        result.type,
      ),
    }))
    .filter((result) => result.score > 0)
    .sort((a, b) => (b.score || 0) - (a.score || 0));

  return scoredResults.slice(0, limit);
}

/**
 * Parse the mention text after @ to extract the query.
 * Returns null if not in mention mode.
 *
 * @param text - Full text content
 * @param cursorPosition - Current cursor position
 */
export function extractMentionQuery(
  text: string,
  cursorPosition: number,
): string | null {
  // Find the last @ before cursor
  const beforeCursor = text.substring(0, cursorPosition);
  const lastAtIndex = beforeCursor.lastIndexOf("@");

  if (lastAtIndex === -1) return null;

  // Check that @ is at start of word (preceded by space, newline, or start of text)
  if (lastAtIndex > 0) {
    const charBefore = beforeCursor[lastAtIndex - 1];
    if (charBefore !== " " && charBefore !== "\n" && charBefore !== "\t") {
      return null;
    }
  }

  // Extract query from @ to cursor
  const query = beforeCursor.substring(lastAtIndex + 1);

  // Query should not contain spaces (space ends mention mode)
  if (query.includes(" ")) return null;

  return query;
}
