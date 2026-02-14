<script lang="ts">
  /**
   * SettingsMemoriesSuggestions.svelte
   *
   * Displays suggested settings/memories entries generated during AI post-processing.
   * Shows as horizontally-scrollable cards below the AI response with:
   * - App icon with gradient background
   * - Category name (e.g., "Favorite tech")
   * - Suggested title (e.g., "Python")
   * - "Reject" and "Add" buttons
   *
   * Design: First card is centered, horizontal scroll for multiple cards.
   * Privacy: Uses SHA-256 hashes for rejection (zero-knowledge).
   */
  import { onMount } from "svelte";
  import { fade } from "svelte/transition";
  import { text } from "@repo/ui";
  import type { SuggestedSettingsMemoryEntry } from "../types/apps";
  import Icon from "./Icon.svelte";
  import { appSkillsStore } from "../stores/appSkillsStore";
  import { appSettingsMemoriesStore } from "../stores/appSettingsMemoriesStore";
  import { chatDB } from "../services/db";
  import { chatSyncService } from "../services/chatSyncService";

  interface Props {
    suggestions: SuggestedSettingsMemoryEntry[];
    chatId: string;
    rejectedHashes?: string[] | null;
    onSuggestionAdded?: (suggestion: SuggestedSettingsMemoryEntry) => void;
    onSuggestionRejected?: (suggestion: SuggestedSettingsMemoryEntry) => void;
  }

  let {
    suggestions,
    chatId,
    rejectedHashes = null,
    onSuggestionAdded,
    onSuggestionRejected,
  }: Props = $props();

  // Local state for tracking which suggestions are being processed
  let processingIds = $state<Set<string>>(new Set());

  // Get apps metadata for icons and names (reactive state from singleton store)
  let appsMetadata = $state(appSkillsStore.getState());

  /**
   * Compute SHA-256 hash for a suggestion (for rejection tracking)
   * Format: SHA256("app_id:item_type:title.toLowerCase()")
   */
  async function computeRejectionHash(
    suggestion: SuggestedSettingsMemoryEntry
  ): Promise<string> {
    const input = `${suggestion.app_id}:${suggestion.item_type}:${suggestion.suggested_title.toLowerCase()}`;
    const encoder = new TextEncoder();
    const data = encoder.encode(input);
    const hashBuffer = await crypto.subtle.digest("SHA-256", data);
    const hashArray = Array.from(new Uint8Array(hashBuffer));
    return hashArray.map((b) => b.toString(16).padStart(2, "0")).join("");
  }

  /**
   * Check if a suggestion has already been rejected (by hash)
   */
  async function isRejected(
    suggestion: SuggestedSettingsMemoryEntry
  ): Promise<boolean> {
    if (!rejectedHashes || rejectedHashes.length === 0) return false;
    const hash = await computeRejectionHash(suggestion);
    return rejectedHashes.includes(hash);
  }

  /**
   * Resolve the title field name for a given app category using is_title schema metadata.
   * Falls back to common field names if no is_title flag is found.
   */
  function getTitleFieldName(appId: string, itemType: string): string | null {
    const app = appsMetadata?.apps?.[appId];
    if (!app) return null;

    const category = app.settings_and_memories?.find(
      (sm) => sm.id === itemType
    );
    if (!category?.schema_definition?.properties) return null;

    // First: look for explicit is_title flag in schema
    for (const [fieldName, prop] of Object.entries(category.schema_definition.properties)) {
      if (prop.is_title) return fieldName;
    }

    // Fallback: look for common title field names
    const commonTitleFields = ["name", "title", "label"];
    for (const field of commonTitleFields) {
      if (category.schema_definition.properties[field]) return field;
    }

    return null;
  }

  /**
   * Check if a similar entry already exists in the user's settings/memories.
   * Compares by app_id, item_type, and case-insensitive title match using
   * the schema's is_title field to determine which field to compare.
   */
  function alreadyExists(
    suggestion: SuggestedSettingsMemoryEntry
  ): boolean {
    // Get entries for the app, then filter by item_type (category)
    const appEntries = appSettingsMemoriesStore.getEntriesByApp(suggestion.app_id);
    if (!appEntries) return false;
    
    // The entries are grouped by settings_group (item_type)
    const categoryEntries = appEntries[suggestion.item_type];
    if (!categoryEntries || categoryEntries.length === 0) return false;

    const suggestedTitleLower = suggestion.suggested_title.toLowerCase();

    // Resolve the title field from schema metadata (uses is_title flag)
    const titleField = getTitleFieldName(suggestion.app_id, suggestion.item_type);

    for (const entry of categoryEntries) {
      const entryValue = entry.item_value as Record<string, unknown>;
      if (!entryValue) continue;

      if (titleField) {
        // Use the schema-defined title field
        const value = entryValue[titleField];
        if (
          typeof value === "string" &&
          value.toLowerCase() === suggestedTitleLower
        ) {
          return true;
        }
      } else {
        // No schema title field found - check all string values as fallback
        for (const value of Object.values(entryValue)) {
          if (
            typeof value === "string" &&
            value.toLowerCase() === suggestedTitleLower
          ) {
            return true;
          }
        }
      }
    }

    return false;
  }

  /**
   * Filter suggestions to only show those that are:
   * 1. Not already rejected
   * 2. Don't already exist in user's data (case-insensitive title match)
   *
   * Uses a store version counter (incremented via onMount subscription) so
   * that the $effect re-runs when entries are loaded, added, or deleted.
   */
  let filteredSuggestions = $state<SuggestedSettingsMemoryEntry[]>([]);

  // Subscribe to store changes to get reactive updates when entries change.
  // CRITICAL: Use onMount instead of $effect for the subscription to avoid
  // an infinite loop. Subscribing inside $effect causes the callback to fire
  // immediately (standard Svelte store contract), which mutates storeVersion,
  // which re-triggers the effect, re-subscribes, fires again → infinite loop.
  let storeVersion = $state(0);
  onMount(() => {
    const unsubscribeStore = appSettingsMemoriesStore.subscribe(() => {
      storeVersion++;
    });
    return () => unsubscribeStore();
  });

  // Filter suggestions reactively (re-runs when suggestions, rejectedHashes, or store entries change)
  $effect(() => {
    // Track reactive dependencies: suggestions prop, rejectedHashes prop, and store version
    void storeVersion;
    void suggestions;
    void rejectedHashes;
    // CRITICAL: Wrap async filterSuggestions in a try-catch to prevent unhandled
    // promise rejections from crashing Svelte's reactive flush cycle
    filterSuggestions().catch((error) => {
      console.error("[SettingsMemoriesSuggestions] Error filtering suggestions:", error);
    });
  });

  async function filterSuggestions() {
    const filtered: SuggestedSettingsMemoryEntry[] = [];

    for (const suggestion of suggestions) {
      const rejected = await isRejected(suggestion);
      if (rejected) continue;

      const exists = alreadyExists(suggestion);
      if (exists) {
        console.debug(
          `[SettingsMemoriesSuggestions] Filtered out "${suggestion.suggested_title}" - already exists in ${suggestion.app_id}/${suggestion.item_type}`
        );
        continue;
      }

      filtered.push(suggestion);
    }

    filteredSuggestions = filtered;
  }

  /**
   * Get the display name for a category
   */
  function getCategoryName(
    appId: string,
    itemType: string
  ): string {
    const app = appsMetadata?.apps?.[appId];
    if (!app) return itemType;

    const category = app.settings_and_memories?.find(
      (sm) => sm.id === itemType
    );
    if (!category) return itemType;

    // Use translation key if available
    if (category.name_translation_key) {
      const translated = $text(category.name_translation_key);
      if (translated && translated !== category.name_translation_key) {
        return translated;
      }
    }

    return itemType;
  }

  /**
   * Get unique ID for a suggestion (for keying)
   */
  function getSuggestionId(suggestion: SuggestedSettingsMemoryEntry): string {
    return `${suggestion.app_id}:${suggestion.item_type}:${suggestion.suggested_title}`;
  }

  /**
   * Handle rejecting a suggestion
   */
  async function handleReject(suggestion: SuggestedSettingsMemoryEntry) {
    const id = getSuggestionId(suggestion);
    if (processingIds.has(id)) return;

    processingIds.add(id);
    processingIds = new Set(processingIds);

    try {
      // Compute rejection hash
      const hash = await computeRejectionHash(suggestion);

      // Update local chat record
      const chat = await chatDB.getChat(chatId);
      if (chat) {
        const existingHashes = chat.rejected_suggestion_hashes ?? [];
        if (!existingHashes.includes(hash)) {
          chat.rejected_suggestion_hashes = [...existingHashes, hash];
          await chatDB.updateChat(chat);
        }
      }

      // Send to server for cross-device sync
      const { sendRejectSettingsMemorySuggestionImpl } = await import(
        "../services/chatSyncServiceSenders"
      );
      await sendRejectSettingsMemorySuggestionImpl(chatSyncService, chatId, hash);

      // Remove from filtered list immediately
      filteredSuggestions = filteredSuggestions.filter(
        (s) => getSuggestionId(s) !== id
      );

      // Notify parent
      onSuggestionRejected?.(suggestion);

      console.debug(
        `[SettingsMemoriesSuggestions] Rejected suggestion: ${suggestion.suggested_title}`
      );
    } catch (error) {
      console.error(
        `[SettingsMemoriesSuggestions] Error rejecting suggestion:`,
        error
      );
    } finally {
      processingIds.delete(id);
      processingIds = new Set(processingIds);
    }
  }

  /**
   * Handle adding a suggestion to settings/memories
   */
  async function handleAdd(suggestion: SuggestedSettingsMemoryEntry) {
    const id = getSuggestionId(suggestion);
    if (processingIds.has(id)) return;

    processingIds.add(id);
    processingIds = new Set(processingIds);

    try {
      // Create the entry using the store
      // The createEntry method expects (appId, {item_key, item_value, settings_group})
      await appSettingsMemoriesStore.createEntry(
        suggestion.app_id,
        {
          item_key: suggestion.suggested_title,
          item_value: suggestion.item_value,
          settings_group: suggestion.item_type
        }
      );

      // Remove from filtered list immediately
      filteredSuggestions = filteredSuggestions.filter(
        (s) => getSuggestionId(s) !== id
      );

      // Notify parent
      onSuggestionAdded?.(suggestion);

      console.debug(
        `[SettingsMemoriesSuggestions] Added suggestion: ${suggestion.suggested_title}`
      );
    } catch (error) {
      console.error(
        `[SettingsMemoriesSuggestions] Error adding suggestion:`,
        error
      );
    } finally {
      processingIds.delete(id);
      processingIds = new Set(processingIds);
    }
  }
</script>

{#if filteredSuggestions.length > 0}
  <div class="suggestions-block" transition:fade={{ duration: 200 }}>
    <!-- Header text with lock icon -->
    <div class="suggestions-header">
      <Icon name="lock" size="18px" />
      <span>{$text("chat.settings_memories_suggestions.header")}</span>
    </div>

    <!-- Outer container panel wrapping all cards -->
    <div class="suggestions-panel">
      <div class="suggestions-scroll-container">
        <div
          class="suggestions-track"
          class:single={filteredSuggestions.length === 1}
        >
          {#each filteredSuggestions as suggestion (getSuggestionId(suggestion))}
            {@const isProcessing = processingIds.has(getSuggestionId(suggestion))}
            <div class="suggestion-card" class:processing={isProcessing}>
              <!-- Top section: app icon + heart icon + category/title text -->
              <div class="card-top">
                <div class="card-icons">
                  <div class="app-icon-circle">
                    <Icon name={suggestion.app_id} type="app" size="61px" />
                  </div>
                  <div class="settings-memories-icon">
                    <Icon name="heart" size="26px" />
                  </div>
                </div>
                <div class="suggestion-info">
                  <span class="category-name">{getCategoryName(suggestion.app_id, suggestion.item_type)}</span>
                  <span class="suggestion-title">{suggestion.suggested_title}</span>
                </div>
              </div>
              <!-- Bottom section: reject and add action buttons -->
              <div class="card-bottom">
                <button
                  class="action-btn reject-btn"
                  onclick={() => handleReject(suggestion)}
                  disabled={isProcessing}
                  aria-label={$text("chat.settings_memories_suggestions.reject")}
                >
                  <Icon name="close" size="17px" />
                  <span>{$text("chat.settings_memories_suggestions.reject")}</span>
                </button>
                <button
                  class="action-btn add-btn"
                  onclick={() => handleAdd(suggestion)}
                  disabled={isProcessing}
                  aria-label={$text("chat.settings_memories_suggestions.add")}
                >
                  <Icon name="create" size="17px" />
                  <span>{$text("chat.settings_memories_suggestions.add")}</span>
                </button>
              </div>
            </div>
          {/each}
        </div>
      </div>
    </div>

    <!-- Privacy notice with lock icon -->
    <div class="privacy-notice">
      <Icon name="lock" size="20px" />
      <span>{$text("chat.settings_memories_suggestions.privacy_notice")}</span>
    </div>
  </div>
{/if}

<style>
  /* ===== Suggestions block container ===== */
  .suggestions-block {
    margin: 16px 0;
    padding: 0 12px;
  }

  /* ===== Header: lock icon + question text ===== */
  .suggestions-header {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    color: var(--color-grey-60);
    font-size: 16px;
    font-weight: 700;
    margin-bottom: 12px;
  }

  /* ===== Outer panel wrapping cards (rounded container with shadow) ===== */
  .suggestions-panel {
    background: var(--color-grey-0);
    border-radius: 23px;
    box-shadow: 0 4px 4px rgba(0, 0, 0, 0.25);
    overflow: hidden;
  }

  /* ===== Horizontal scroll container for cards ===== */
  .suggestions-scroll-container {
    overflow-x: auto;
    overflow-y: hidden;
    scrollbar-width: thin;
    scrollbar-color: var(--color-grey-30) transparent;
    -webkit-overflow-scrolling: touch;
  }

  .suggestions-scroll-container::-webkit-scrollbar {
    height: 6px;
  }

  .suggestions-scroll-container::-webkit-scrollbar-track {
    background: transparent;
  }

  .suggestions-scroll-container::-webkit-scrollbar-thumb {
    background: var(--color-grey-30);
    border-radius: 3px;
  }

  /* ===== Cards track (flex row) ===== */
  .suggestions-track {
    display: flex;
    gap: 16px;
    padding: 16px;
    justify-content: flex-start;
  }

  .suggestions-track.single {
    justify-content: center;
  }

  /* ===== Individual suggestion card ===== */
  .suggestion-card {
    flex: 0 0 auto;
    width: 300px;
    transition: opacity 0.2s ease;
  }

  .suggestion-card.processing {
    opacity: 0.6;
    pointer-events: none;
  }

  /* ===== Card top section: icon area + text ===== */
  .card-top {
    display: flex;
    align-items: center;
    gap: 12px;
    background: var(--color-grey-10);
    border-radius: 30px;
    padding: 0;
    box-shadow: 0 4px 4px rgba(0, 0, 0, 0.25);
    height: 61px;
    position: relative;
  }

  /* ===== Icon area within top section ===== */
  .card-icons {
    display: flex;
    align-items: center;
    gap: 0;
    flex-shrink: 0;
    position: relative;
  }

  /* App icon circle (61px, uses the app's own gradient via Icon component) */
  .app-icon-circle {
    flex-shrink: 0;
    width: 61px;
    height: 61px;
    border-radius: 50%;
    overflow: hidden;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  /* Override Icon component border-radius to be circular within app-icon-circle */
  .app-icon-circle :global(.icon) {
    border-radius: 50% !important;
  }

  /* Settings/memories heart icon (pink/magenta gradient) */
  .settings-memories-icon {
    width: 26px;
    height: 26px;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    margin-left: 4px;
  }

  /* Apply the SettingsMemories pink gradient to the heart icon */
  .settings-memories-icon :global(.icon) {
    background: linear-gradient(180deg, #DD03B5 0%, #CB00A5 100%) !important;
    background-clip: text !important;
    -webkit-background-clip: text !important;
    -webkit-text-fill-color: transparent !important;
    border: none !important;
    width: 26px !important;
    height: 26px !important;
    min-width: 26px !important;
    min-height: 26px !important;
  }

  /* ===== Suggestion text (category name + title) ===== */
  .suggestion-info {
    display: flex;
    flex-direction: column;
    gap: 0;
    min-width: 0;
    flex: 1;
  }

  .category-name {
    font-size: 16px;
    font-weight: 700;
    color: var(--color-grey-50);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    line-height: 1.25;
  }

  .suggestion-title {
    font-size: 16px;
    font-weight: 700;
    color: var(--color-grey-50);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    line-height: 1.25;
  }

  /* ===== Card bottom section: action buttons on gray bar ===== */
  .card-bottom {
    display: flex;
    align-items: center;
    background: var(--color-grey-25);
    border-radius: 0 0 33px 33px;
    padding: 14px 20px;
    margin-top: 0;
    box-shadow: 0 4px 4px rgba(0, 0, 0, 0.25);
  }

  /* ===== Action buttons (text-only, no background fill) ===== */
  .action-btn {
    display: flex;
    align-items: center;
    gap: 6px;
    background: none;
    border: none;
    outline: none;
    padding: 4px 8px;
    font-size: 17px;
    font-weight: 700;
    cursor: pointer;
    transition: opacity 0.15s ease;
    line-height: 1.25;
  }

  .action-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  /* Reject button: grey text, positioned on the left */
  .reject-btn {
    color: var(--color-grey-50);
    margin-right: auto;
  }

  .reject-btn:hover:not(:disabled) {
    color: var(--color-grey-70);
  }

  /* Add button: blue gradient text, positioned on the right */
  .add-btn {
    color: var(--color-primary-start);
    margin-left: auto;
  }

  .add-btn:hover:not(:disabled) {
    opacity: 0.8;
  }

  /* ===== Privacy notice footer ===== */
  .privacy-notice {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    margin-top: 16px;
    padding: 8px;
    color: var(--color-grey-60);
    font-size: 14px;
    font-weight: 700;
    line-height: 1.25;
  }

  /* ===== Responsive adjustments ===== */
  @media (max-width: 600px) {
    .suggestion-card {
      width: 260px;
    }

    .card-top {
      height: 52px;
    }

    .app-icon-circle {
      width: 52px;
      height: 52px;
    }

    .category-name,
    .suggestion-title {
      font-size: 14px;
    }

    .action-btn {
      font-size: 15px;
    }

    .suggestions-header {
      font-size: 14px;
    }
  }
</style>
