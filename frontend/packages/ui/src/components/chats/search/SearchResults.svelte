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
  - Clicking a settings or app result closes search, navigates deep-link, and closes panel on mobile.
  - Clicking a chat title result keeps search OPEN and opens the chat.
    On mobile: closes the Chats panel so the active chat is visible; search is restored on panel reopen.
  - Clicking a message snippet keeps search OPEN, opens the chat, and scrolls the
    matched message into view with a brief blink animation.
    On mobile: closes the Chats panel so the highlighted message is visible; search is restored on panel reopen.
  - Arrow Up/Down (from SearchBar) moves the focused highlight between results.
  - Enter activates the focused result.
  - The parent (Chats.svelte) exposes focusNext()/focusPrevious() via bind:this for arrow key delegation.
-->
<script lang="ts">
  import { text } from '@repo/ui';
  import { tick } from 'svelte';
  import ChatComponent from '../Chat.svelte';
  import Icon from '../../Icon.svelte';
  import { groupChats, getLocalizedGroupTitle } from '../utils/chatGroupUtils';
  import type { ChatSearchResult, AppCatalogSearchResult, SearchResults as SearchResultsType } from '../../../services/searchService';
  import type { Chat as ChatType } from '../../../types/chat';
  import { appSkillsStore } from '../../../stores/appSkillsStore';

  // Props using Svelte 5 runes
  interface Props {
    /** The complete search results from the search service */
    results: SearchResultsType;
    /** The current search query (for highlighting) */
    query: string;
    /** The currently selected (active) chat ID */
    activeChatId: string | null;
    /** Called when a chat title result is clicked (keeps search open, opens chat) */
    onChatClick: (chat: ChatType) => void;
    /**
     * Called when a message snippet is clicked.
     * Does NOT close search — keeps it open so user can continue browsing matches.
     * The parent navigates to the chat and triggers scroll-to-message.
     * When the snippet comes from an embed, embedId and embedType are provided so
     * the parent can open the embed fullscreen view after navigating to the message.
     */
    onMessageSnippetClick: (chat: ChatType, messageId: string, embedId?: string, embedType?: string) => void;
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

  let settingsByType = $derived((() => {
    const myEmbeds: typeof results.settings = [];
    const regularSettings: typeof results.settings = [];

    for (const settingResult of results.settings) {
      const path = settingResult.entry.path;
      const isMyEmbedEntry = /^app_store\/[^/]+\/settings_memories\/[^/]+\/entry\/[^/]+$/.test(path);
      if (isMyEmbedEntry) {
        myEmbeds.push(settingResult);
      } else {
        regularSettings.push(settingResult);
      }
    }

    return { myEmbeds, regularSettings };
  })());

  // Track focused result index for keyboard navigation.
  // We flatten all results into a single navigable list.
  let focusedIndex = $state(-1);

  // Reference to the container element for querying focusable children
  let containerEl: HTMLDivElement | null = $state(null);

  // Auto-open timer: after user stops navigating with arrow keys for this many ms,
  // automatically activate (open) the focused result. Only fires for 'chat' and 'snippet'
  // type items — settings/apps are opened on Enter only to avoid unintended navigation.
  const AUTO_OPEN_DELAY_MS = 300;
  let autoOpenTimer: ReturnType<typeof setTimeout> | null = null;

  // Build a flat list of all focusable items for keyboard navigation
  let allFocusableItems = $derived((() => {
    const items: Array<{ type: 'settings' | 'app' | 'chat' | 'snippet'; id: string }> = [];

    for (const s of settingsByType.regularSettings) {
      items.push({ type: 'settings', id: s.entry.path });
    }
    for (const s of settingsByType.myEmbeds) {
      items.push({ type: 'settings', id: s.entry.path });
    }
    if (appsByType) {
      for (const a of appsByType.apps) {
        items.push({ type: 'app', id: a.entry.path });
      }
      for (const a of appsByType.skills) {
        items.push({ type: 'app', id: a.entry.path });
      }
      for (const a of appsByType.focusModes) {
        items.push({ type: 'app', id: a.entry.path });
      }
      for (const a of appsByType.memories) {
        items.push({ type: 'app', id: a.entry.path });
      }
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
   * Schedule an auto-open of the currently focused result after the user stops navigating.
   * Auto-opens all result types: 'chat', 'snippet', 'settings', and 'app'.
   * Resets the timer on every navigation key so it only fires when the user pauses.
   */
  function scheduleAutoOpen(): void {
    if (autoOpenTimer !== null) {
      clearTimeout(autoOpenTimer);
    }
    if (focusedIndex < 0 || focusedIndex >= allFocusableItems.length) return;
    autoOpenTimer = setTimeout(() => {
      autoOpenTimer = null;
      activateFocused();
    }, AUTO_OPEN_DELAY_MS);
  }

  /**
   * Move focus to the next result (called from SearchBar ArrowDown).
   * Finds all keyboard-focusable elements inside the container and focuses the next one.
   * Exposed as a named export so the parent can call it via bind:this reference.
   */
  export function focusNext(): void {
    focusedIndex = Math.min(focusedIndex + 1, allFocusableItems.length - 1);
    scrollFocusedItemIntoView();
    scheduleAutoOpen();
  }

  /**
   * Move focus to the previous result (called from SearchBar ArrowUp).
   */
  export function focusPrevious(): void {
    focusedIndex = Math.max(focusedIndex - 1, 0);
    scrollFocusedItemIntoView();
    scheduleAutoOpen();
  }

  /**
   * Activate the currently focused item (Enter key from SearchBar).
   * The first result is selected by default when results load, so this always has
   * something to activate as long as results exist.
   */
  export function activateFocused(): void {
    if (focusedIndex < 0 || !containerEl) return;
    const focusableEls = getFocusableElements();
    const el = focusableEls[focusedIndex];
    if (el) {
      (el as HTMLElement).click();
    }
  }

  /**
   * Get all keyboard-focusable interactive elements inside the container,
   * in DOM order (which matches our allFocusableItems ordering).
   */
  function getFocusableElements(): Element[] {
    if (!containerEl) return [];
    return Array.from(
      containerEl.querySelectorAll('button, [role="option"], [tabindex="0"]')
    );
  }

  /**
   * Scroll the currently focused item into view and visually focus it.
   */
  async function scrollFocusedItemIntoView(): Promise<void> {
    await tick(); // Wait for Svelte to update .focused class
    if (!containerEl || focusedIndex < 0) return;
    const focusableEls = getFocusableElements();
    const el = focusableEls[focusedIndex] as HTMLElement | undefined;
    if (el) {
      el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
  }

  // When results change (new query), select the first result by default and cancel any
  // pending auto-open. Selecting index 0 immediately makes it clear to the user what
  // Enter will open, and provides a starting point for arrow-key navigation.
  $effect(() => {
    const items = allFocusableItems; // React to items changing
    focusedIndex = items.length > 0 ? 0 : -1;
    if (autoOpenTimer !== null) {
      clearTimeout(autoOpenTimer);
      autoOpenTimer = null;
    }
  });

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

  function normalizeIconName(iconImage: string | undefined, fallback: string): string {
    const raw = iconImage ? iconImage.replace(/\.svg$/, '').trim() : fallback;
    if (raw === 'email') return 'mail';
    if (raw === 'coding') return 'code';
    if (raw === 'heart') return 'health';
    return raw;
  }

  function getAppCatalogIcons(appResult: AppCatalogSearchResult): {
    appIconName: string;
    itemIconName: string | null;
    itemIconType: 'skill' | 'focus' | 'memory' | null;
  } {
    const appMeta = appSkillsStore.getState().apps[appResult.entry.appId];
    const appIconName = normalizeIconName(appMeta?.icon_image, appResult.entry.appId);

    if (appResult.entryType === 'app' || !appMeta) {
      return { appIconName, itemIconName: null, itemIconType: null };
    }

    const pathParts = appResult.entry.path.split('/');

    if (appResult.entryType === 'skill') {
      const skillId = pathParts[3] || '';
      const skill = appMeta.skills.find(s => s.id === skillId);
      const itemIconName = normalizeIconName(skill?.icon_image || appMeta.icon_image, appResult.entry.appId);
      return { appIconName, itemIconName, itemIconType: 'skill' };
    }

    if (appResult.entryType === 'focus_mode') {
      const focusId = pathParts[3] || '';
      const focusMode = appMeta.focus_modes.find(f => f.id === focusId);
      const itemIconName = normalizeIconName(focusMode?.icon_image || appMeta.icon_image, appResult.entry.appId);
      return { appIconName, itemIconName, itemIconType: 'focus' };
    }

    const memoryId = pathParts[3] || '';
    const memory = appMeta.settings_and_memories.find(m => m.id === memoryId);
    const itemIconName = normalizeIconName(memory?.icon_image || appMeta.icon_image, appResult.entry.appId);
    return { appIconName, itemIconName, itemIconType: 'memory' };
  }

  function getMyEmbedIcons(path: string): {
    appIconName: string;
    memoryIconName: string;
  } {
    const pathParts = path.split('/');
    const appId = pathParts[1] || '';
    const categoryId = pathParts[3] || '';
    const appMeta = appSkillsStore.getState().apps[appId];

    const appIconName = normalizeIconName(appMeta?.icon_image, appId || 'app');
    const memoryMeta = appMeta?.settings_and_memories.find((m) => m.id === categoryId);
    const memoryIconName = normalizeIconName(memoryMeta?.icon_image || appMeta?.icon_image, appId || 'app');

    return { appIconName, memoryIconName };
  }

  function resolveTranslatedLabel(value: string): string {
    const translated = $text(value);
    return translated.startsWith('[T:') ? value : translated;
  }

  function humanizeFocusId(focusId: string): string {
    const relevantPart = focusId.includes('-') ? focusId.split('-').slice(1).join('-') : focusId;
    return relevantPart
      .replace(/[_-]/g, ' ')
      .replace(/\b\w/g, (char: string) => char.toUpperCase())
      .trim();
  }

  function getFocusSnippetDisplay(snippet: ChatSearchResult['messageSnippets'][number]): {
    title: string;
    status: string;
  } {
    const appId = snippet.embedAppId || '';
    const appMeta = appId ? appSkillsStore.getState().apps[appId] : undefined;
    const focusId = snippet.embedFocusId || '';
    const shortFocusId = appId && focusId.startsWith(`${appId}-`) ? focusId.slice(appId.length + 1) : focusId;

    const focusMeta = appMeta?.focus_modes.find((focus) => focus.id === shortFocusId || focus.id === focusId);

    let title = '';
    if (snippet.embedFocusModeName) {
      title = resolveTranslatedLabel(snippet.embedFocusModeName);
    }
    if (!title && focusMeta?.name_translation_key) {
      title = resolveTranslatedLabel(focusMeta.name_translation_key);
    }
    if (!title && focusId) {
      title = humanizeFocusId(focusId);
    }
    if (!title) {
      title = $text('chats.search.app_focus_mode');
    }

    const status = snippet.embedFocusIsActive
      ? $text('chats.search.focus_mode_status_activated')
      : $text('chats.search.focus_mode_status_deactivated');

    return { title, status };
  }

  function getEmbedSnippetIcons(snippet: ChatSearchResult['messageSnippets'][number]): {
    appIconName: string | null;
    itemIconName: string | null;
    itemIconType: 'skill' | 'focus' | null;
  } {
    const appId = snippet.embedAppId;
    if (!appId) {
      return { appIconName: null, itemIconName: null, itemIconType: null };
    }

    const appMeta = appSkillsStore.getState().apps[appId];
    const appIconName = normalizeIconName(appMeta?.icon_image, appId);

    if (snippet.embedType === 'focus-mode-activation') {
      const focusId = snippet.embedFocusId || '';
      const shortFocusId = focusId.startsWith(`${appId}-`) ? focusId.slice(appId.length + 1) : focusId;
      const focusMeta = appMeta?.focus_modes.find((focus) => focus.id === shortFocusId || focus.id === focusId);
      const focusIconName = normalizeIconName(focusMeta?.icon_image || appMeta?.icon_image, appId);
      return { appIconName, itemIconName: focusIconName, itemIconType: 'focus' };
    }

    if (snippet.embedSkillId) {
      const skillMeta = appMeta?.skills.find((skill) => skill.id === snippet.embedSkillId);
      const skillIconName = normalizeIconName(skillMeta?.icon_image || appMeta?.icon_image, appId);
      return { appIconName, itemIconName: skillIconName, itemIconType: 'skill' };
    }

    return { appIconName, itemIconName: null, itemIconType: null };
  }

  function getEmbedSnippetContextLabel(snippet: ChatSearchResult['messageSnippets'][number]): string | null {
    const appId = snippet.embedAppId;
    if (!appId) {
      return snippet.embedSourceLabel || null;
    }

    const appMeta = appSkillsStore.getState().apps[appId];
    const appName = appMeta?.name_translation_key ? resolveTranslatedLabel(appMeta.name_translation_key) : appId;

    if (snippet.embedType === 'focus-mode-activation') {
      return null;
    }

    if (snippet.embedSkillId) {
      const skillMeta = appMeta?.skills.find((skill) => skill.id === snippet.embedSkillId);
      if (skillMeta?.name_translation_key) {
        return `${appName} · ${resolveTranslatedLabel(skillMeta.name_translation_key)}`;
      }
    }

    return appName;
  }

  /**
   * Handle keyboard navigation (Arrow Up/Down, Enter) within results.
   * Called from the container div's keydown handler (when user tabs into results).
   * Primary navigation (from SearchBar input) uses focusNext/focusPrevious exports.
   */
  function handleContainerKeyDown(event: KeyboardEvent): void {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      focusNext();
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      focusPrevious();
    } else if (event.key === 'Enter') {
      event.preventDefault();
      activateFocused();
    }
  }
</script>

<div
  bind:this={containerEl}
  class="search-results"
  data-testid="search-results"
  role="listbox"
  tabindex="-1"
  aria-label={$text('chats.search.results_label')}
  onkeydown={handleContainerKeyDown}
>
  <!-- Settings Results Section -->
  {#if settingsByType.regularSettings.length > 0}
    <div class="search-section">
      <h3 class="search-section-title">{$text('common.settings')}</h3>
      {#each settingsByType.regularSettings as settingResult}
        {@const itemId = settingResult.entry.path}
        {@const isFocused = allFocusableItems[focusedIndex]?.id === itemId}
        <button
          class="search-setting-item"
          class:focused={isFocused}
          data-testid="search-setting-item"
          data-result-id={itemId}
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

  {#if settingsByType.myEmbeds.length > 0}
    <div class="search-section">
      <h3 class="search-section-title">{$text('settings.app_settings_memories.my_settings_and_memories')}</h3>
      {#each settingsByType.myEmbeds as settingResult}
        {@const itemId = settingResult.entry.path}
        {@const isFocused = allFocusableItems[focusedIndex]?.id === itemId}
        {@const myEmbedIcons = getMyEmbedIcons(settingResult.entry.path)}
        <button
          class="search-setting-item"
          class:focused={isFocused}
          data-testid="search-setting-item"
          data-result-id={itemId}
          onclick={() => onSettingsClick(
            settingResult.entry.path,
            settingResult.label,
            settingResult.icon || undefined,
            settingResult.entry.translationKey,
          )}
        >
          <span class="app-result-icons" aria-hidden="true">
            <Icon
              name={myEmbedIcons.appIconName}
              type="app"
              size="22px"
              noAnimation={true}
            />
            <Icon
              name={myEmbedIcons.memoryIconName}
              type="memory"
              size="22px"
              noAnimation={true}
            />
          </span>
          <span class="item-label">
            <!-- eslint-disable-next-line svelte/no-at-html-tags -->
            {@html highlightText(settingResult.label, query)}
          </span>
        </button>
      {/each}
    </div>
  {/if}

  <!-- App Catalog Results Sections -->
  {#if appsByType && appsByType.apps.length > 0}
    <div class="search-section">
      <h3 class="search-section-title">{$text('common.apps')}</h3>
      {#each appsByType.apps as appResult}
        {@const itemId = appResult.entry.path}
        {@const isFocused = allFocusableItems[focusedIndex]?.id === itemId}
        {@const appIcons = getAppCatalogIcons(appResult)}
        <button
          class="search-setting-item"
          class:focused={isFocused}
          data-result-id={itemId}
          onclick={() => onAppCatalogClick(appResult.entry.path, appResult.label)}
        >
          <span class="app-result-icons" aria-hidden="true">
            <Icon
              name={appIcons.appIconName}
              type="app"
              size="22px"
              noAnimation={true}
            />
          </span>
          <span class="item-label">
            <!-- eslint-disable-next-line svelte/no-at-html-tags -->
            {@html highlightText(appResult.label, query)}
          </span>
        </button>
      {/each}
    </div>
  {/if}

  {#if appsByType && appsByType.skills.length > 0}
    <div class="search-section">
      <h3 class="search-section-title">{$text('settings.app_store.skills.title')}</h3>
      {#each appsByType.skills as appResult}
        {@const itemId = appResult.entry.path}
        {@const isFocused = allFocusableItems[focusedIndex]?.id === itemId}
        {@const appIcons = getAppCatalogIcons(appResult)}
        <button
          class="search-setting-item"
          class:focused={isFocused}
          data-result-id={itemId}
          onclick={() => onAppCatalogClick(appResult.entry.path, appResult.label)}
        >
          <span class="app-result-icons" aria-hidden="true">
            <Icon
              name={appIcons.appIconName}
              type="app"
              size="22px"
              noAnimation={true}
            />
            {#if appIcons.itemIconName}
              <Icon
                name={appIcons.itemIconName}
                type="skill"
                size="22px"
                noAnimation={true}
              />
            {/if}
          </span>
          <span class="item-label">
            <!-- eslint-disable-next-line svelte/no-at-html-tags -->
            {@html highlightText(appResult.label, query)}
          </span>
        </button>
      {/each}
    </div>
  {/if}

  {#if appsByType && appsByType.focusModes.length > 0}
    <div class="search-section">
      <h3 class="search-section-title">{$text('settings.app_store.focus_modes.title')}</h3>
      {#each appsByType.focusModes as appResult}
        {@const itemId = appResult.entry.path}
        {@const isFocused = allFocusableItems[focusedIndex]?.id === itemId}
        {@const appIcons = getAppCatalogIcons(appResult)}
        <button
          class="search-setting-item"
          class:focused={isFocused}
          data-result-id={itemId}
          onclick={() => onAppCatalogClick(appResult.entry.path, appResult.label)}
        >
          <span class="app-result-icons" aria-hidden="true">
            <Icon
              name={appIcons.appIconName}
              type="app"
              size="22px"
              noAnimation={true}
            />
            {#if appIcons.itemIconName}
              <Icon
                name={appIcons.itemIconName}
                type="focus"
                size="22px"
                noAnimation={true}
              />
            {/if}
          </span>
          <span class="item-label">
            <!-- eslint-disable-next-line svelte/no-at-html-tags -->
            {@html highlightText(appResult.label, query)}
          </span>
        </button>
      {/each}
    </div>
  {/if}

  {#if appsByType && appsByType.memories.length > 0}
    <div class="search-section">
      <h3 class="search-section-title">{$text('settings.app_settings_memories.settings_and_memories')}</h3>
      {#each appsByType.memories as appResult}
        {@const itemId = appResult.entry.path}
        {@const isFocused = allFocusableItems[focusedIndex]?.id === itemId}
        {@const appIcons = getAppCatalogIcons(appResult)}
        <button
          class="search-setting-item"
          class:focused={isFocused}
          data-result-id={itemId}
          onclick={() => onAppCatalogClick(appResult.entry.path, appResult.label)}
        >
          <span class="app-result-icons" aria-hidden="true">
            <Icon
              name={appIcons.appIconName}
              type="app"
              size="22px"
              noAnimation={true}
            />
            {#if appIcons.itemIconName}
              <Icon
                name={appIcons.itemIconName}
                type="memory"
                size="22px"
                noAnimation={true}
              />
            {/if}
          </span>
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
        <!-- Chat title entry (clicking keeps search open, opens chat) -->
        {@const chatItemId = chatResult.chat.chat_id}
        {@const isChatFocused = allFocusableItems[focusedIndex]?.id === chatItemId}
        <div
          role="option"
          tabindex="0"
          aria-selected={activeChatId === chatResult.chat.chat_id}
          class="search-chat-item"
          data-testid="search-chat-item"
          class:active={activeChatId === chatResult.chat.chat_id}
          class:focused={isChatFocused}
          data-result-id={chatItemId}
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
              {@const snippetIsFocused = allFocusableItems[focusedIndex]?.id === snippet.messageId}
              {@const embedIcons = getEmbedSnippetIcons(snippet)}
              {@const embedContextLabel = getEmbedSnippetContextLabel(snippet)}
              {@const focusDisplay = snippet.embedType === 'focus-mode-activation' ? getFocusSnippetDisplay(snippet) : null}
              <button
                class="message-snippet"
                class:focused={snippetIsFocused}
                data-result-id={snippet.messageId}
                title={$text('chats.search.go_to_message')}
                onclick={() => onMessageSnippetClick(
                  chatResult.chat,
                  snippet.messageId,
                  snippet.embedType === 'focus-mode-activation' ? undefined : snippet.embedId,
                  snippet.embedType,
                )}
              >
                {#if embedIcons.appIconName}
                  <span class="embed-snippet-header">
                    <span class="app-result-icons" aria-hidden="true">
                      <Icon
                        name={embedIcons.appIconName}
                        type="app"
                        size="20px"
                        noAnimation={true}
                      />
                      {#if embedIcons.itemIconName && embedIcons.itemIconType}
                        <Icon
                          name={embedIcons.itemIconName}
                          type={embedIcons.itemIconType}
                          size="20px"
                          noAnimation={true}
                        />
                      {/if}
                    </span>
                    {#if focusDisplay}
                      <span class="embed-focus-meta">
                        <span class="embed-focus-title">{focusDisplay.title}</span>
                        <span class="embed-focus-status">{focusDisplay.status}</span>
                      </span>
                    {:else if embedContextLabel}
                      <span class="embed-source-label">{embedContextLabel}</span>
                    {/if}
                  </span>
                {:else if snippet.embedSourceLabel}
                  <span class="embed-source-label">{snippet.embedSourceLabel}</span>
                {/if}
                <!-- eslint-disable-next-line svelte/no-at-html-tags -->
                {@html highlightText(snippet.snippet, query)}
              </button>
            {/each}
          </div>
        {/if}

        <!-- Metadata match snippets (summary/tags — shown for metadata-only or supplementary matches) -->
        {#if chatResult.metadataSnippets.length > 0 && chatResult.messageSnippets.length === 0}
          <div class="message-snippets">
            {#each chatResult.metadataSnippets as metaSnippet}
              <button
                class="message-snippet metadata-snippet"
                onclick={() => onChatClick(chatResult.chat)}
              >
                {#if metaSnippet.matchSource === 'tags'}
                  <span class="metadata-source-label">{$text('chats.search.tag_match')}</span>
                {:else}
                  <span class="metadata-source-label">{$text('common.summary')}</span>
                {/if}
                <!-- eslint-disable-next-line svelte/no-at-html-tags -->
                {@html highlightText(metaSnippet.snippet, query)}
              </button>
            {/each}
          </div>
        {/if}
      {/each}
    </div>
  {/each}

  <!-- No Results Message -->
  {#if results.totalCount === 0 && query.trim().length > 0}
    <div class="no-results" data-testid="search-no-results">
      <p class="no-results-text">{$text('chats.search.no_results')}</p>
    </div>
  {/if}

  <!-- Warming Up Indicator -->
  {#if results.isWarmingUp}
    <div class="warming-up" data-testid="warming-up">
      <span class="clickable-icon icon_reload syncing-icon"></span>
      <span class="warming-up-text">{$text('chats.search.indexing')}</span>
    </div>
  {/if}
</div>

<style>
  .search-results {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-2);
    padding: 0;
  }

  /* Section container */
  .search-section {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-1);
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
    gap: var(--spacing-5);
    padding: 9px 15px;
    cursor: pointer;
    border: none;
    background: transparent;
    width: 100%;
    text-align: left;
    border-radius: var(--radius-3);
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
  }

  .item-icon {
    flex-shrink: 0;
    width: 20px;
    height: 20px;
    opacity: 0.75;
  }

  .item-label {
    font-size: var(--font-size-small);
    font-weight: 500;
    color: var(--color-font-primary);
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .app-result-icons {
    display: inline-flex;
    align-items: center;
    gap: var(--spacing-3);
    flex-shrink: 0;
  }

  .app-result-icons :global(.icon) {
    margin: 0;
  }

  /* Chat result item wrapper */
  .search-chat-item {
    border-radius: var(--radius-3);
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

  .search-chat-item.focused {
    background-color: var(--color-grey-25);
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
    font-size: var(--font-size-xs);
    color: var(--color-font-secondary);
    line-height: 1.45;
    cursor: pointer;
    border: none;
    background: transparent;
    padding: 3px 6px;
    border-radius: var(--radius-1);
    text-align: left;
    /* Allow wrapping — snippets are already length-bounded by the search service.
       Using nowrap+ellipsis would cut off the match when it's not near the start. */
    overflow: hidden;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    width: 100%;
    transition: background-color 0.12s ease;
  }

  @media (hover: hover) {
    .message-snippet:hover {
      background-color: var(--color-grey-25);
      color: var(--color-font-primary);
    }
  }

  .message-snippet.focused {
    background-color: var(--color-grey-25);
    color: var(--color-font-primary);
  }

  /* Metadata source label (e.g., "Summary" or "Tag") for metadata-only search matches.
   * Uses the same visual style as embed-source-label for consistency. */
  .metadata-source-label {
    display: inline-block;
    font-size: var(--font-size-tiny);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--color-font-tertiary, var(--color-font-secondary));
    opacity: 0.75;
    margin-right: var(--spacing-2);
  }

  /* Embed source label (e.g., "Web page ·" or "Code ·") shown before embed-sourced snippets.
   * Styled as a muted badge so it doesn't compete with the match text. */
  .embed-source-label {
    display: inline-block;
    font-size: var(--font-size-tiny);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--color-font-tertiary, var(--color-font-secondary));
    opacity: 0.75;
    margin-right: var(--spacing-1);
  }

  .embed-snippet-header {
    display: flex;
    align-items: center;
    gap: var(--spacing-4);
    margin-bottom: var(--spacing-2);
  }

  .embed-focus-meta {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }

  .embed-focus-title {
    font-size: var(--font-size-xxs);
    line-height: 1.2;
    color: var(--color-font-primary);
    font-weight: 600;
  }

  .embed-focus-status {
    font-size: var(--font-size-tiny);
    line-height: 1.2;
    color: var(--color-font-secondary);
    font-weight: 500;
  }

  /* <mark> inside snippets — yellow background highlight, matching in-chat search marks.
   * Must override the global `mark` rule in fonts.css which uses -webkit-text-fill-color:transparent
   * (gradient text effect). That property takes priority over `color` in WebKit/Blink browsers,
   * making text invisible unless we explicitly reset -webkit-text-fill-color here. */
  .message-snippet :global(mark) {
    background: none;
    background-color: rgba(255, 213, 0, 0.4);
    -webkit-background-clip: unset;
    background-clip: unset;
    -webkit-text-fill-color: unset;
    color: inherit;
    font-weight: inherit;
    border-radius: 2px;
    padding: 1px 0;
  }

  /* <mark> inside metadata snippets (summary/tag matches) — same style as message snippets */
  .metadata-snippet :global(mark) {
    background: none;
    background-color: rgba(255, 213, 0, 0.4);
    -webkit-background-clip: unset;
    background-clip: unset;
    -webkit-text-fill-color: unset;
    color: inherit;
    font-weight: inherit;
    border-radius: 2px;
    padding: 1px 0;
  }

  /* <mark> inside setting/app labels */
  .item-label :global(mark) {
    background: none;
    background-color: rgba(255, 213, 0, 0.4);
    -webkit-background-clip: unset;
    background-clip: unset;
    -webkit-text-fill-color: unset;
    color: inherit;
    font-weight: inherit;
    border-radius: 2px;
    padding: 1px 0;
  }

  /* No results message */
  .no-results {
    display: flex;
    justify-content: center;
    padding: var(--spacing-20) var(--spacing-10);
  }

  .no-results-text {
    font-size: var(--font-size-small);
    color: var(--color-font-secondary);
    text-align: center;
  }

  /* Warming up / indexing indicator */
  .warming-up {
    display: flex;
    align-items: center;
    gap: var(--spacing-4);
    padding: 12px 15px;
    justify-content: center;
  }

  .warming-up-text {
    font-size: var(--font-size-xs);
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
