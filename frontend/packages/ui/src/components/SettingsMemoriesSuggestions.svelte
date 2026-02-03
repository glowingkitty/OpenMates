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
   * Check if a similar entry already exists in the user's settings/memories
   * Compares by app_id, item_type, and case-insensitive title match
   */
  async function alreadyExists(
    suggestion: SuggestedSettingsMemoryEntry
  ): Promise<boolean> {
    // Get entries for the app, then filter by item_type (category)
    const appEntries = appSettingsMemoriesStore.getEntriesByApp(suggestion.app_id);
    if (!appEntries) return false;
    
    // The entries are grouped by settings_group (item_type)
    const categoryEntries = appEntries[suggestion.item_type];
    if (!categoryEntries || categoryEntries.length === 0) return false;

    const suggestedTitleLower = suggestion.suggested_title.toLowerCase();

    for (const entry of categoryEntries) {
      // Get the title field from the entry's item_value
      // The title field is marked with is_title: true in the schema
      const entryValue = entry.item_value as Record<string, unknown>;
      if (!entryValue) continue;

      // Check common title field names
      const titleFields = ["name", "title", "label", "destination", "language"];
      for (const field of titleFields) {
        const value = entryValue[field];
        if (
          typeof value === "string" &&
          value.toLowerCase() === suggestedTitleLower
        ) {
          return true;
        }
      }
    }

    return false;
  }

  /**
   * Filter suggestions to only show those that are:
   * 1. Not already rejected
   * 2. Don't already exist in user's data
   */
  let filteredSuggestions = $state<SuggestedSettingsMemoryEntry[]>([]);

  // Filter suggestions reactively
  $effect(() => {
    filterSuggestions();
  });

  async function filterSuggestions() {
    const filtered: SuggestedSettingsMemoryEntry[] = [];

    for (const suggestion of suggestions) {
      const rejected = await isRejected(suggestion);
      if (rejected) continue;

      const exists = await alreadyExists(suggestion);
      if (exists) continue;

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
    <div class="suggestions-header">
      <Icon name="lock" size="16px" />
      <span>{$text("chat.settings_memories_suggestions.header.text")}</span>
    </div>

    <div class="suggestions-scroll-container">
      <div
        class="suggestions-track"
        class:single={filteredSuggestions.length === 1}
      >
        {#each filteredSuggestions as suggestion (getSuggestionId(suggestion))}
          {@const isProcessing = processingIds.has(getSuggestionId(suggestion))}
          <div class="suggestion-card" class:processing={isProcessing}>
            <div class="card-content">
              <div class="app-icon-wrapper">
                <Icon name={suggestion.app_id} type="app" size="40px" />
              </div>
              <div class="suggestion-info">
                <span class="category-name"
                  >{getCategoryName(suggestion.app_id, suggestion.item_type)}</span
                >
                <span class="suggestion-title">{suggestion.suggested_title}</span>
              </div>
            </div>
            <div class="card-actions">
              <button
                class="action-btn reject-btn"
                onclick={() => handleReject(suggestion)}
                disabled={isProcessing}
                aria-label={$text("chat.settings_memories_suggestions.reject.text")}
              >
                <Icon name="x" size="16px" />
                <span>{$text("chat.settings_memories_suggestions.reject.text")}</span>
              </button>
              <button
                class="action-btn add-btn"
                onclick={() => handleAdd(suggestion)}
                disabled={isProcessing}
                aria-label={$text("chat.settings_memories_suggestions.add.text")}
              >
                <Icon name="plus" size="16px" />
                <span>{$text("chat.settings_memories_suggestions.add.text")}</span>
              </button>
            </div>
          </div>
        {/each}
      </div>
    </div>

    <div class="privacy-notice">
      <Icon name="shield" size="14px" />
      <span>{$text("chat.settings_memories_suggestions.privacy_notice.text")}</span>
    </div>
  </div>
{/if}

<style>
  .suggestions-block {
    margin: 16px 0;
    padding: 0 12px;
  }

  .suggestions-header {
    display: flex;
    align-items: center;
    gap: 8px;
    color: var(--color-grey-60);
    font-size: 14px;
    font-weight: 500;
    margin-bottom: 12px;
    padding-left: 4px;
  }

  .suggestions-scroll-container {
    overflow-x: auto;
    overflow-y: hidden;
    scrollbar-width: thin;
    scrollbar-color: var(--color-grey-30) transparent;
    margin: 0 -12px;
    padding: 0 12px;
    /* Smooth scroll on touch devices */
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

  .suggestions-track {
    display: flex;
    gap: 12px;
    padding: 4px 0;
    /* For multiple cards, start from left */
    justify-content: flex-start;
  }

  /* When single card, center it */
  .suggestions-track.single {
    justify-content: center;
  }

  .suggestion-card {
    flex: 0 0 auto;
    min-width: 280px;
    max-width: 320px;
    background: var(--color-grey-0);
    border-radius: 16px;
    padding: 16px;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
    transition: transform 0.2s ease, box-shadow 0.2s ease, opacity 0.2s ease;
  }

  .suggestion-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12);
  }

  .suggestion-card.processing {
    opacity: 0.6;
    pointer-events: none;
  }

  .card-content {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 12px;
  }

  .app-icon-wrapper {
    flex-shrink: 0;
    width: 48px;
    height: 48px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 12px;
    background: linear-gradient(135deg, var(--color-primary-light), var(--color-primary));
  }

  .suggestion-info {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }

  .category-name {
    font-size: 12px;
    color: var(--color-grey-50);
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }

  .suggestion-title {
    font-size: 16px;
    font-weight: 600;
    color: var(--color-grey-90);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .card-actions {
    display: flex;
    gap: 8px;
    border-top: 1px solid var(--color-grey-20);
    padding-top: 12px;
  }

  .action-btn {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    padding: 8px 12px;
    border-radius: 8px;
    font-size: 14px;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.15s ease;
    border: none;
    outline: none;
  }

  .reject-btn {
    background: var(--color-grey-10);
    color: var(--color-grey-60);
  }

  .reject-btn:hover:not(:disabled) {
    background: var(--color-grey-20);
    color: var(--color-grey-80);
  }

  .add-btn {
    background: var(--color-primary);
    color: white;
  }

  .add-btn:hover:not(:disabled) {
    background: var(--color-primary-dark);
  }

  .action-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .privacy-notice {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    margin-top: 12px;
    padding: 8px;
    color: var(--color-grey-50);
    font-size: 12px;
  }

  /* Responsive adjustments */
  @media (max-width: 600px) {
    .suggestion-card {
      min-width: 260px;
      max-width: 280px;
    }

    .suggestions-header {
      font-size: 13px;
    }

    .action-btn {
      padding: 6px 10px;
      font-size: 13px;
    }
  }
</style>
