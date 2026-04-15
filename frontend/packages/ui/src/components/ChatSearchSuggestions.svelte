<!--
  ChatSearchSuggestions.svelte — Horizontal search result cards for open chats.

  When the user types in the message input while an existing chat is open,
  this component searches across chats and shows matching results as
  horizontally scrollable gradient cards — same visual style as NewChatSuggestions.
  The container is hidden entirely when there are no results.

  Authenticated users: searches all personal chats (demo/legal/example excluded).
  Unauthenticated users: searches intro and example chats (public static content only),
    using cleartext category/icon fields instead of the encrypted metadata cache.

  Architecture: reuses searchService for full-text search, chatMetadataCache
  for icon/category resolution (authenticated only), and categoryUtils for gradient colors.
-->
<script lang="ts">
  import { search as performSearch } from '../services/searchService';
  import { chatDB } from '../services/db';
  import { chatMetadataCache } from '../services/chatMetadataCache';
  import { getLucideIcon, getValidIconName, getFallbackIconForCategory, getCategoryGradientColors } from '../utils/categoryUtils';
  import { authStore } from '../stores/authStore';
  import { text } from '@repo/ui';
  import { get } from 'svelte/store';
  import {
    isDemoChat, isLegalChat, isExampleChat,
    INTRO_CHATS, translateDemoChats, getAllExampleChats,
    convertDemoChatToChat,
  } from '../demo_chats';
  import type { Chat } from '../types/chat';

  /** Maximum number of existing chat results to show */
  const MAX_CHAT_RESULTS = 5;

  let {
    messageInputContent = '',
    onChatNavigate,
    currentChatId = undefined,
  }: {
    messageInputContent?: string;
    onChatNavigate: (chatId: string) => void;
    currentChatId?: string | undefined;
  } = $props();

  interface ChatResultCard {
    chatId: string;
    title: string;
    iconName: string;
    gradientStart: string;
    gradientEnd: string;
    dateLabel: string;
  }

  let chatSearchResults = $state<ChatResultCard[]>([]);
  let searchGeneration = 0;

  // Debounced filter query — updated 400ms after user pauses typing
  let filterQuery = $state('');
  let _filterDebounceTimer: ReturnType<typeof setTimeout> | undefined;

  $effect(() => {
    const raw = messageInputContent.trim().toLowerCase();
    if (_filterDebounceTimer) clearTimeout(_filterDebounceTimer);
    _filterDebounceTimer = setTimeout(() => {
      filterQuery = raw;
    }, 400);
    return () => {
      if (_filterDebounceTimer) clearTimeout(_filterDebounceTimer);
    };
  });

  /**
   * Format a timestamp into a short relative/absolute date label.
   * e.g., "Today", "Yesterday", "Mar 15", "Dec 2025"
   */
  function formatChatDate(timestamp: number): string {
    const date = new Date(typeof timestamp === 'number' && timestamp < 1e12 ? timestamp * 1000 : timestamp);
    if (isNaN(date.getTime())) return '';

    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

    if (diffDays === 0) return 'Today';
    if (diffDays === 1) return 'Yesterday';
    if (diffDays < 7) return `${diffDays}d ago`;

    const sameYear = date.getFullYear() === now.getFullYear();
    const month = date.toLocaleString('default', { month: 'short' });
    return sameYear ? `${month} ${date.getDate()}` : `${month} ${date.getFullYear()}`;
  }

  /**
   * Search existing chats when filterQuery changes.
   * - Authenticated users: searches all personal chats (demo/legal/example excluded).
   * - Unauthenticated users: searches intro and example chats (public static content only).
   */
  $effect(() => {
    const query = filterQuery;
    if (!query) {
      chatSearchResults = [];
      return;
    }

    const gen = ++searchGeneration;
    const textFn = get(text);
    const isAuthenticated = $authStore.isAuthenticated;

    (async () => {
      try {
        let chatsToSearch: Chat[];

        if (isAuthenticated) {
          await chatDB.init();
          chatsToSearch = await chatDB.getAllChats();
        } else {
          // Unauthenticated: search only public static chats (intro + example)
          const translatedIntroChats = translateDemoChats(INTRO_CHATS).map(convertDemoChatToChat);
          chatsToSearch = [...translatedIntroChats, ...getAllExampleChats()];
        }

        const results = await performSearch(query, chatsToSearch, textFn);
        // Stale guard — a newer search was triggered while this one ran
        if (gen !== searchGeneration) return;

        // Authenticated: exclude demo/legal/example chats and the current chat
        // Unauthenticated: only exclude the currently open chat (all results are public)
        const filteredResults = results.chats.filter((r) => {
          if (r.chat.chat_id === currentChatId) return false;
          if (isAuthenticated) {
            return !isDemoChat(r.chat.chat_id) && !isLegalChat(r.chat.chat_id) && !isExampleChat(r.chat.chat_id);
          }
          return true;
        });

        // Resolve metadata (icon, category) for each result.
        // For authenticated user chats: use chatMetadataCache (encrypted metadata).
        // For public chats (intro/example): use the cleartext fields on the Chat object directly.
        const processed = await Promise.all(
          filteredResults.slice(0, MAX_CHAT_RESULTS).map(async (result) => {
            const metadata = isAuthenticated
              ? await chatMetadataCache.getDecryptedMetadata(result.chat)
              : null;
            const category = metadata?.category || result.chat.category || 'general_knowledge';
            const icon = metadata?.icon || result.chat.icon || getFallbackIconForCategory(category);
            const validIcon = getValidIconName(icon, category);
            const gradient = getCategoryGradientColors(category) || { start: '#DE1E66', end: '#FF763B' };
            const timestamp = result.chat.last_edited_overall_timestamp || result.chat.created_at || 0;

            return {
              chatId: result.chat.chat_id,
              title: result.decryptedTitle || metadata?.title || result.chat.title || 'Untitled',
              iconName: validIcon,
              gradientStart: gradient.start,
              gradientEnd: gradient.end,
              dateLabel: formatChatDate(timestamp),
            };
          })
        );

        // Final stale guard after async metadata resolution
        if (gen !== searchGeneration) return;
        chatSearchResults = processed;
      } catch (error) {
        console.error('[ChatSearchSuggestions] Chat search error:', error);
        if (gen === searchGeneration) chatSearchResults = [];
      }
    })();
  });
</script>

{#if chatSearchResults.length > 0}
  <div class="chat-search-wrapper" data-testid="chat-search-suggestions">
    <div class="chat-search-header">
      {$text('chat.suggestions.related_chats')}
    </div>
    <div class="chat-search-scroll">
      {#each chatSearchResults as chatResult (chatResult.chatId)}
        {@const IconComponent = getLucideIcon(chatResult.iconName)}
        <div class="chat-result-wrapper">
          <button
            class="suggestion-card chat-result-card"
            data-testid="chat-search-result"
            style="background: linear-gradient(135deg, {chatResult.gradientStart}, {chatResult.gradientEnd});"
            onclick={() => onChatNavigate(chatResult.chatId)}
          >
            <span class="card-icon chat-result-icon">
              <IconComponent size={24} color="white" />
            </span>
            <span class="card-text">{chatResult.title}</span>
          </button>
          <span class="card-date">{chatResult.dateLabel}</span>
        </div>
      {/each}
    </div>
  </div>
{/if}

<style>
  .chat-search-wrapper {
    animation: fadeIn 200ms ease-out;
    animation-delay: 200ms;
    animation-fill-mode: backwards;
    transition: opacity 200ms ease;
    opacity: 1;
    width: 100%;
    -webkit-mask-image: linear-gradient(to right, transparent, black 28px, black calc(100% - 28px), transparent);
    mask-image: linear-gradient(to right, transparent, black 28px, black calc(100% - 28px), transparent);
  }

  .chat-search-header {
    color: var(--color-grey-60);
    font-size: var(--font-size-p);
    padding: 0 0 0 calc(50% - 150px);
    letter-spacing: 0.5px;
    opacity: 0.9;
    margin-bottom: var(--spacing-3);
    width: 100%;
    box-sizing: border-box;
  }

  @keyframes fadeIn {
    from { opacity: 0; }
    to { opacity: 1; }
  }

  .chat-search-scroll {
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: var(--spacing-6);
    overflow-x: auto;
    overflow-y: hidden;
    -webkit-overflow-scrolling: touch;
    scroll-behavior: smooth;
    scrollbar-width: none;
    -ms-overflow-style: none;
    padding: 4px 48px 14px calc(50% - 150px);
    margin-bottom: -4px;
    box-sizing: border-box;
    width: 100%;
    max-width: 100%;
  }

  .chat-search-scroll::-webkit-scrollbar {
    display: none;
  }

  .suggestion-card {
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: var(--spacing-5);
    width: 300px;
    min-width: 300px;
    min-height: 56px;
    height: auto;
    padding: var(--spacing-6) var(--spacing-8);
    border: none;
    border-radius: 15px;
    cursor: pointer;
    flex-shrink: 0;
    box-shadow: 0px 4px 8px rgba(0, 0, 0, 0.3);
    transition: transform var(--duration-fast) var(--easing-default), box-shadow var(--duration-fast) var(--easing-default);
  }

  .suggestion-card:hover {
    transform: translateY(-1px);
    box-shadow: 0px 6px 8px 0px rgba(0, 0, 0, 0.3);
  }

  .suggestion-card:active {
    transform: scale(0.97);
    box-shadow: 0px 2px 4px 0px rgba(0, 0, 0, 0.2);
  }

  .card-icon {
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    width: 27px;
    height: 27px;
  }

  .chat-result-icon {
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .card-text {
    color: var(--color-font-button);
    font-size: var(--font-size-small);
    font-weight: 700;
    line-height: 1.3;
    text-align: left;
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    overflow: hidden;
    min-width: 0;
  }

  .chat-result-wrapper {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--spacing-2);
    flex-shrink: 0;
  }

  .card-date {
    color: var(--color-grey-50);
    font-size: var(--font-size-tiny);
    font-weight: 400;
    line-height: 1.2;
    white-space: nowrap;
    text-align: center;
    opacity: 0.8;
  }

  @media (max-width: 730px) {
    .chat-search-wrapper {
      -webkit-mask-image: linear-gradient(to right, transparent, black 16px, black calc(100% - 16px), transparent);
      mask-image: linear-gradient(to right, transparent, black 16px, black calc(100% - 16px), transparent);
    }

    .chat-search-header {
      padding: 0 0 0 calc(50% - 105px);
      font-size: var(--font-size-small);
    }

    .chat-search-scroll {
      gap: var(--spacing-5);
      padding: 4px 15px 8px calc(50% - 105px);
    }

    .suggestion-card {
      width: 210px;
      min-width: 210px;
      padding: var(--spacing-5) var(--spacing-6);
      gap: var(--spacing-4);
    }

    .card-text {
      font-size: var(--font-size-xs);
    }
  }
</style>
