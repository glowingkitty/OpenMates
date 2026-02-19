<!--
  SearchResults.svelte
  Displays search results across all categories: settings, app catalog, then chat results by time group.
  
  Layout (matching Figma design):
  1. Settings section — icon + label rows (only when settings match)
  2. Apps / Skills / Focus Modes / Memories section (only when app catalog matches)
  3. Chat results — grouped by time period (Today, Yesterday, etc.)
     - Each chat shows its title with highlighted matched words
     - Below each matching chat: message match snippets with highlighted text
  
  Behavior:
  - Clicking a settings or app result closes search and navigates deep-link.
  - Clicking a chat title result closes search and opens the chat.
  - Clicking a message snippet keeps search OPEN, opens the chat, and scrolls the
    matched message into view with a brief blink animation.
  - Arrow Up/Down keyboard navigation moves focus between results.
  - Enter activates the focused result.
-->
<script lang="ts">
  import { text } from '@repo/ui';
  import ChatComponent from '../Chat.svelte';
  import { groupChats, getLocalizedGroupTitle } from '../utils/chatGroupUtils';
  import type { ChatSearchResult, AppCatalogSearchResult, SearchResults as SearchResultsType } from '../../../services/searchService';
  import type { Chat as ChatType } from '../../../types/chat';

  // Props using Svelte 5 runes
  interface Props {
    /** The complete search results from the search service */
    results: SearchResultsType;
    /** The current search query (for highlighting) */
    query: string;
    /** The currently selected (active) chat ID */
    activeChatId: string | null;
    /** Called when a chat title result is clicked (closes search, opens chat) */
    onChatClick: (chat: ChatType) => void;
    /**
     * Called when a message snippet is clicked.
     * Does NOT close search — keeps it open so user can continue browsing matches.
     * The parent navigates to the chat and triggers scroll-to-message.
     */
    onMessageSnippetClick: (chat: ChatType, messageId: string) => void;
    /** Called when a settings result is clicked */
    onSettingsClick: (path: string, title: string, icon?: string, translationKey?: string) => void;
    /** Called when an app catalog result is clicked */
    onAppCatalogClick: (path: string, title: string) => void;
  }

  let {
    results,
    query,
    activeChatId,
    onChatClick,
    onMessageSnippetClick,
    onSettingsClick,
    onAppCatalogClick,
  }: Props = $props();

  // Group chat results by time period (reusing existing grouping logic)
  let groupedChatResults = $derived((() => {
    if (!results.chats || results.chats.length === 0) return [];

    const chats = results.chats.map(r => r.chat);
    const grouped = groupChats(chats);

    const timeGroups = ['today', 'yesterday', 'previous_7_days', 'previous_30_days'];
    const staticGroups = ['shared_by_others', 'intro', 'examples', 'legal'];
    const orderedEntries: Array<{ groupKey: string; items: ChatSearchResult[] }> = [];

    const resultMap = new Map(results.chats.map(r => [r.chat.chat_id, r]));

    // Time groups first
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

    // Non-static, non-time groups (month groups etc.)
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

    // Static groups last
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

  // Group app catalog results by type for display
  let appsByType = $derived((() => {
    if (!results.appCatalog || results.appCatalog.length === 0) return null;
    const apps = results.appCatalog.filter(r => r.entryType === 'app');
    const skills = results.appCatalog.filter(r => r.entryType === 'skill');
    const focusModes = results.appCatalog.filter(r => r.entryType === 'focus_mode');
    const memories = results.appCatalog.filter(r => r.entryType === 'memory');
    return { apps, skills, focusModes, memories };
  })());

  // Track focused result index for keyboard navigation.
  // We flatten all results into a single navigable list.
  let focusedIndex = $state(-1);

  // Build a flat list of all focusable items for keyboard navigation
  let allFocusableItems = $derived((() => {
    const items: Array<{ type: 'settings' | 'app' | 'chat' | 'snippet'; id: string }> = [];

    for (const s of results.settings) {
      items.push({ type: 'settings', id: s.entry.path });
    }
    for (const a of results.appCatalog) {
      items.push({ type: 'app', id: a.entry.path });
    }
    for (const group of groupedChatResults) {
      for (const chatResult of group.items) {
        items.push({ type: 'chat', id: chatResult.chat.chat_id });
        for (const snippet of chatResult.messageSnippets) {
          items.push({ type: 'snippet', id: snippet.messageId });
        }
      }
    }
    return items;
  })());

  /**
   * Build highlighted HTML for a text with match ranges.
   * Wraps each matching segment in <mark> tags.
   * Safe against XSS: all text is HTML-escaped before being wrapped.
   */
  function highlightText(fullText: string, searchQuery: string): string {
    if (!searchQuery || !fullText) return escapeHtml(fullText || '');

    const lowerText = fullText.toLowerCase();
    const lowerQuery = searchQuery.toLowerCase().trim();
    if (!lowerQuery) return escapeHtml(fullText);

    const parts: string[] = [];
    let lastIndex = 0;
    let searchFrom = 0;

    while (searchFrom < lowerText.length) {
      const idx = lowerText.indexOf(lowerQuery, searchFrom);
      if (idx === -1) break;

      if (idx > lastIndex) {
        parts.push(escapeHtml(fullText.slice(lastIndex, idx)));
      }
      parts.push(`<mark>${escapeHtml(fullText.slice(idx, idx + lowerQuery.length))}</mark>`);
      lastIndex = idx + lowerQuery.length;
      searchFrom = lastIndex;
    }

    if (lastIndex < fullText.length) {
      parts.push(escapeHtml(fullText.slice(lastIndex)));
    }

    return parts.join('');
  }

  /** Escape HTML special characters to prevent XSS */
  function escapeHtml(str: string): string {
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  /** Get the display label for an app catalog entry type */
  function getAppEntryTypeLabel(entryType: AppCatalogSearchResult['entryType']): string {
    switch (entryType) {
      case 'skill': return $text('chats.search.app_skill');
      case 'focus_mode': return $text('chats.search.app_focus_mode');
      case 'memory': return $text('chats.search.app_memory');
      default: return $text('chats.search.app_app');
    }
  }

  /**
   * Handle keyboard navigation (Arrow Up/Down, Enter) within results.
   * Called from the container div's keydown handler.
   */
  function handleContainerKeyDown(event: KeyboardEvent): void {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      focusedIndex = Math.min(focusedIndex + 1, allFocusableItems.length - 1);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      focusedIndex = Math.max(focusedIndex - 1, 0);
    }
    // Enter is handled by individual item click handlers
  }
</script>

<div
  class="search-results"
  role="listbox"
  tabindex="-1"
  aria-label={$text('chats.search.results_label')}
  onkeydown={handleContainerKeyDown}
>
  <!-- Settings Results Section -->
  {#if results.settings.length > 0}
    <div class="search-section">
      <h3 class="search-section-title">{$text('chats.search.settings')}</h3>
      {#each results.settings as settingResult, i}
        <button
          class="search-setting-item"
          class:focused={focusedIndex === i}
          onclick={() => onSettingsClick(
            settingResult.entry.path,
            settingResult.label,
            settingResult.icon || undefined,
            settingResult.entry.translationKey,
          )}
        >
          {#if settingResult.icon}
            <span class="item-icon clickable-icon {settingResult.icon}"></span>
          {/if}
          <span class="item-label">
            <!-- eslint-disable-next-line svelte/no-at-html-tags -->
            {@html highlightText(settingResult.label, query)}
          </span>
        </button>
      {/each}
    </div>
  {/if}

  <!-- App Catalog Results Section -->
  {#if results.appCatalog.length > 0 && appsByType}
    <div class="search-section">
      <h3 class="search-section-title">{$text('chats.search.apps')}</h3>
      {#each results.appCatalog as appResult, i}
        {@const globalIdx = results.settings.length + i}
        <button
          class="search-setting-item"
          class:focused={focusedIndex === globalIdx}
          onclick={() => onAppCatalogClick(appResult.entry.path, appResult.label)}
        >
          <span class="item-type-badge">{getAppEntryTypeLabel(appResult.entryType)}</span>
          <span class="item-label">
            <!-- eslint-disable-next-line svelte/no-at-html-tags -->
            {@html highlightText(appResult.label, query)}
          </span>
        </button>
      {/each}
    </div>
  {/if}

  <!-- Chat Results Section (grouped by time period) -->
  {#each groupedChatResults as group (group.groupKey)}
    <div class="search-section">
      <h3 class="search-section-title">{getLocalizedGroupTitle(group.groupKey, $text)}</h3>
      {#each group.items as chatResult (chatResult.chat.chat_id)}
        <!-- Chat title entry (clicking this closes search and opens the chat) -->
        <div
          role="option"
          tabindex="0"
          aria-selected={activeChatId === chatResult.chat.chat_id}
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
            highlightedTitle={chatResult.decryptedTitle
              ? highlightText(chatResult.decryptedTitle, query)
              : null}
          />
        </div>

        <!-- Message match snippets (clicking these keeps search open and scrolls to message) -->
        {#if chatResult.messageSnippets.length > 0}
          <div class="message-snippets">
            {#each chatResult.messageSnippets as snippet}
              <button
                class="message-snippet"
                title={$text('chats.search.go_to_message')}
                onclick={() => onMessageSnippetClick(chatResult.chat, snippet.messageId)}
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

  /* Section container */
  .search-section {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  /* Section header text (e.g., "Settings", "Apps", "Today", "Yesterday") */
  .search-section-title {
    font-size: 0.72em;
    color: var(--color-font-tertiary);
    text-transform: uppercase;
    letter-spacing: 0.8px;
    font-weight: 600;
    padding: 14px 15px 4px 15px;
    margin: 0;
  }

  /* Settings / app catalog result item */
  .search-setting-item {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 9px 15px;
    cursor: pointer;
    border: none;
    background: transparent;
    width: 100%;
    text-align: left;
    border-radius: 8px;
    transition: background-color 0.12s ease;
    color: var(--color-font-primary);
  }

  @media (hover: hover) {
    .search-setting-item:hover {
      background-color: var(--color-grey-25);
    }
  }

  .search-setting-item.focused {
    background-color: var(--color-grey-25);
    outline: none;
  }

  .item-icon {
    flex-shrink: 0;
    width: 20px;
    height: 20px;
    opacity: 0.75;
  }

  .item-label {
    font-size: 14px;
    font-weight: 500;
    color: var(--color-font-primary);
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  /* App entry type badge (e.g., "Skill", "Focus Mode") */
  .item-type-badge {
    font-size: 10px;
    font-weight: 600;
    color: var(--color-font-tertiary);
    background-color: var(--color-grey-30);
    border-radius: 4px;
    padding: 2px 5px;
    flex-shrink: 0;
    text-transform: uppercase;
    letter-spacing: 0.3px;
  }

  /* Chat result item wrapper */
  .search-chat-item {
    border-radius: 8px;
    cursor: pointer;
    transition: background-color 0.12s ease;
  }

  @media (hover: hover) {
    .search-chat-item:hover {
      background-color: var(--color-grey-25);
    }
  }

  .search-chat-item.active {
    background-color: var(--color-grey-30);
  }

  /* Message snippet rows shown under matching chats */
  .message-snippets {
    display: flex;
    flex-direction: column;
    gap: 1px;
    padding: 2px 15px 6px 54px; /* Align with chat content area (past avatar) */
  }

  .message-snippet {
    display: block;
    font-size: 13px;
    color: var(--color-font-secondary);
    line-height: 1.45;
    cursor: pointer;
    border: none;
    background: transparent;
    padding: 3px 6px;
    border-radius: 4px;
    text-align: left;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    width: 100%;
    transition: background-color 0.12s ease;
  }

  @media (hover: hover) {
    .message-snippet:hover {
      background-color: var(--color-grey-25);
      color: var(--color-font-primary);
    }
  }

  /* <mark> inside snippets — highlight color matching Figma (primary accent) */
  .message-snippet :global(mark) {
    background-color: transparent;
    color: var(--color-primary-start);
    font-weight: 600;
  }

  /* <mark> inside setting/app labels */
  .item-label :global(mark) {
    background-color: transparent;
    color: var(--color-primary-start);
    font-weight: 700;
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
