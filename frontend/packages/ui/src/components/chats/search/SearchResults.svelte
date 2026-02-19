<!--
  SearchResults.svelte
  Displays search results across all categories: settings, then chat results grouped by time.
  
  Layout (matching Figma design):
  1. Settings section — icon + label rows (only shown when settings match)
  2. Chat results — grouped by time period (Today, Yesterday, etc.)
     - Each chat shows its normal Chat component
     - Below matching chats: message match snippets with highlighted text
-->
<script lang="ts">
  import { text } from '@repo/ui';
  import ChatComponent from '../Chat.svelte';
  import { groupChats, getLocalizedGroupTitle } from '../utils/chatGroupUtils';
  import type { ChatSearchResult, SearchResults as SearchResultsType } from '../../../services/searchService';
  import type { Chat as ChatType } from '../../../types/chat';

  // Props using Svelte 5 runes
  interface Props {
    /** The complete search results from the search service */
    results: SearchResultsType;
    /** The current search query (for highlighting) */
    query: string;
    /** The currently selected (active) chat ID */
    activeChatId: string | null;
    /** Called when a chat result is clicked */
    onChatClick: (chat: ChatType, messageId?: string) => void;
    /** Called when a settings result is clicked */
    onSettingsClick: (path: string, title: string, icon?: string, translationKey?: string) => void;
  }

  let { results, query, activeChatId, onChatClick, onSettingsClick }: Props = $props();

  // Group chat results by time period (reusing existing grouping logic)
  let groupedChatResults = $derived((() => {
    if (!results.chats || results.chats.length === 0) return [];

    // Extract the Chat objects for grouping
    const chats = results.chats.map(r => r.chat);
    const grouped = groupChats(chats);

    // Build ordered entries with their associated search result data
    const timeGroups = ['today', 'yesterday', 'previous_7_days', 'previous_30_days'];
    const staticGroups = ['shared_by_others', 'intro', 'examples', 'legal'];
    const orderedEntries: Array<{ groupKey: string; items: ChatSearchResult[] }> = [];

    // Helper: find the ChatSearchResult for a given chat
    const resultMap = new Map(results.chats.map(r => [r.chat.chat_id, r]));

    // Add time groups first
    for (const groupKey of timeGroups) {
      const groupChatsArr = grouped[groupKey];
      if (groupChatsArr && groupChatsArr.length > 0) {
        const items = groupChatsArr
          .map(c => resultMap.get(c.chat_id))
          .filter((r): r is ChatSearchResult => !!r);
        if (items.length > 0) {
          orderedEntries.push({ groupKey, items });
        }
      }
    }

    // Add remaining non-static groups (month groups, etc.)
    for (const [groupKey, groupChatsArr] of Object.entries(grouped)) {
      if (!timeGroups.includes(groupKey) && !staticGroups.includes(groupKey) && groupChatsArr.length > 0) {
        const items = groupChatsArr
          .map(c => resultMap.get(c.chat_id))
          .filter((r): r is ChatSearchResult => !!r);
        if (items.length > 0) {
          orderedEntries.push({ groupKey, items });
        }
      }
    }

    // Add static groups
    for (const groupKey of staticGroups) {
      const groupChatsArr = grouped[groupKey];
      if (groupChatsArr && groupChatsArr.length > 0) {
        const items = groupChatsArr
          .map(c => resultMap.get(c.chat_id))
          .filter((r): r is ChatSearchResult => !!r);
        if (items.length > 0) {
          orderedEntries.push({ groupKey, items });
        }
      }
    }

    return orderedEntries;
  })());

  /**
   * Build highlighted HTML for a text with match ranges.
   * Uses <mark> tags for highlighted portions.
   */
  function highlightText(fullText: string, searchQuery: string): string {
    if (!searchQuery || !fullText) return escapeHtml(fullText);

    const lowerText = fullText.toLowerCase();
    const lowerQuery = searchQuery.toLowerCase();
    const parts: string[] = [];
    let lastIndex = 0;

    let searchFrom = 0;
    while (searchFrom < lowerText.length) {
      const idx = lowerText.indexOf(lowerQuery, searchFrom);
      if (idx === -1) break;

      // Add text before match
      if (idx > lastIndex) {
        parts.push(escapeHtml(fullText.slice(lastIndex, idx)));
      }
      // Add highlighted match
      parts.push(`<mark>${escapeHtml(fullText.slice(idx, idx + searchQuery.length))}</mark>`);
      lastIndex = idx + searchQuery.length;
      searchFrom = lastIndex;
    }

    // Add remaining text after last match
    if (lastIndex < fullText.length) {
      parts.push(escapeHtml(fullText.slice(lastIndex)));
    }

    return parts.join('');
  }

  /** Escape HTML special characters to prevent XSS */
  function escapeHtml(text: string): string {
    return text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
</script>

<div class="search-results">
  <!-- Settings Results Section -->
  {#if results.settings.length > 0}
    <div class="search-section">
      <h3 class="search-section-title">{$text('chats.search.settings')}</h3>
      {#each results.settings as settingResult}
        <button
          class="search-setting-item"
          onclick={() => onSettingsClick(
            settingResult.entry.path,
            settingResult.label,
            settingResult.icon || undefined,
            settingResult.entry.translationKey,
          )}
        >
          {#if settingResult.icon}
            <span class="setting-icon clickable-icon {settingResult.icon}"></span>
          {/if}
          <span class="setting-label">{settingResult.label}</span>
        </button>
      {/each}
    </div>
  {/if}

  <!-- Chat Results Section (grouped by time period) -->
  {#each groupedChatResults as group (group.groupKey)}
    <div class="search-section">
      <h3 class="search-section-title">{getLocalizedGroupTitle(group.groupKey, $text)}</h3>
      {#each group.items as chatResult (chatResult.chat.chat_id)}
        <!-- Chat entry (clickable) -->
        <div
          role="button"
          tabindex="0"
          class="search-chat-item"
          class:active={activeChatId === chatResult.chat.chat_id}
          onclick={() => onChatClick(chatResult.chat)}
          onkeydown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              onChatClick(chatResult.chat);
            }
          }}
        >
          <ChatComponent
            chat={chatResult.chat}
            activeChatId={activeChatId || undefined}
          />
        </div>

        <!-- Message match snippets (shown below the chat entry) -->
        {#if chatResult.messageSnippets.length > 0}
          <div class="message-snippets">
            {#each chatResult.messageSnippets as snippet}
              <button
                class="message-snippet"
                onclick={() => onChatClick(chatResult.chat, snippet.messageId)}
              >
                <!-- eslint-disable-next-line svelte/no-at-html-tags -->
                {@html highlightText(snippet.snippet, query)}
              </button>
            {/each}
          </div>
        {/if}
      {/each}
    </div>
  {/each}

  <!-- No Results Message -->
  {#if results.totalCount === 0 && query.trim().length > 0}
    <div class="no-results">
      <p class="no-results-text">{$text('chats.search.no_results')}</p>
    </div>
  {/if}

  <!-- Warming Up Indicator -->
  {#if results.isWarmingUp}
    <div class="warming-up">
      <span class="clickable-icon icon_reload syncing-icon"></span>
      <span class="warming-up-text">{$text('chats.search.indexing')}</span>
    </div>
  {/if}
</div>

<style>
  .search-results {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 0;
  }

  /* Section title (e.g., "Settings", "Today", "Yesterday") */
  .search-section {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .search-section-title {
    font-size: 0.85em;
    color: var(--color-grey-60);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    font-weight: 500;
    padding: 15px 15px 4px 15px;
    margin: 0;
  }

  /* Settings result item */
  .search-setting-item {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 15px;
    cursor: pointer;
    border: none;
    background: transparent;
    width: 100%;
    text-align: left;
    border-radius: 8px;
    transition: background-color 0.15s ease;
    color: var(--color-font-primary);
  }

  @media (hover: hover) {
    .search-setting-item:hover {
      background-color: var(--color-grey-25);
    }
  }

  .setting-icon {
    flex-shrink: 0;
    width: 24px;
    height: 24px;
  }

  .setting-label {
    font-size: 15px;
    font-weight: 500;
    color: var(--color-font-primary);
  }

  /* Chat result item (wraps the ChatComponent) */
  .search-chat-item {
    border-radius: 8px;
    cursor: pointer;
    transition: background-color 0.15s ease;
  }

  @media (hover: hover) {
    .search-chat-item:hover {
      background-color: var(--color-grey-25);
    }
  }

  .search-chat-item.active {
    background-color: var(--color-grey-30);
  }

  /* Message snippet rows (shown under matching chats) */
  .message-snippets {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding-left: 52px; /* Align with chat content (after the category circle) */
    padding-right: 15px;
    padding-bottom: 4px;
  }

  .message-snippet {
    display: block;
    font-size: 13px;
    color: var(--color-font-tertiary);
    line-height: 1.4;
    cursor: pointer;
    border: none;
    background: transparent;
    padding: 2px 4px;
    border-radius: 4px;
    text-align: left;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    width: 100%;
    transition: background-color 0.15s ease;
  }

  @media (hover: hover) {
    .message-snippet:hover {
      background-color: var(--color-grey-25);
    }
  }

  /* Highlight styling for matched text within snippets */
  .message-snippet :global(mark) {
    background-color: transparent;
    color: var(--color-primary-start);
    font-weight: 600;
  }

  /* No results message */
  .no-results {
    display: flex;
    justify-content: center;
    padding: 40px 20px;
  }

  .no-results-text {
    font-size: 14px;
    color: var(--color-font-secondary);
    text-align: center;
  }

  /* Warming up / indexing indicator */
  .warming-up {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 12px 15px;
    justify-content: center;
  }

  .warming-up-text {
    font-size: 13px;
    color: var(--color-font-secondary);
  }

  /* Syncing icon animation (reused from Chats.svelte) */
  .syncing-icon {
    animation: spin 1s linear infinite;
    width: 16px;
    height: 16px;
  }

  @keyframes spin {
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
  }
</style>
