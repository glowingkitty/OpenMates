<script lang="ts">
  import { fade } from 'svelte/transition';
  import { onMount } from 'svelte';
  import { chatDB } from '../services/db';
  import { chatSyncService } from '../services/chatSyncService';
  import { decryptWithMasterKey } from '../services/cryptoService';
  import { setClickedSuggestion } from '../stores/suggestionTracker';
  import { text } from '@repo/ui';
  import type { NewChatSuggestion } from '../types/chat';
  import { authStore } from '../stores/authStore';
  import { DEFAULT_NEW_CHAT_SUGGESTIONS } from '../demo_chats/defaultNewChatSuggestions';

  let {
    messageInputContent = '',
    onSuggestionClick
  }: {
    messageInputContent?: string;
    onSuggestionClick: (suggestion: string) => void;
  } = $props();

  // Detect if device is touch-capable
  // Checks for ontouchstart event support and maxTouchPoints
  const isTouchDevice = () => {
    return (('ontouchstart' in window) ||
            (navigator.maxTouchPoints > 0) ||
            ((navigator as any).msMaxTouchPoints > 0));
  };

  let touchDevice = $state(isTouchDevice());

  // Full suggestions pool with both encrypted and decrypted text
  let fullSuggestionsWithEncrypted = $state<Array<{ text: string; encrypted: string }>>([]);
  // Full suggestions pool (decrypted only), used for filtering
  let fullSuggestions = $state<string[]>([]);
  // Currently shown suggestions (random 3 when input empty)
  let suggestions = $state<Array<{text: string}>>([]);
  let loading = $state(true);

  onMount(() => {
    const pickRandomThree = (pool: string[]): Array<{text: string}> => {
      // Ensure we only work with unique suggestions (remove duplicates)
      const unique = Array.from(new Set(pool));
      // Shuffle copy for randomization
      const shuffled = unique.slice().sort(() => Math.random() - 0.5);
      // Pick top 3 unique suggestions
      const top3 = shuffled.slice(0, Math.min(3, shuffled.length));
      return top3.map(text => ({ text }));
    };

    const loadSuggestions = async () => {
      try {
        // For non-authenticated users, use default suggestions instead of IndexedDB
        if (!$authStore.isAuthenticated) {
          console.debug('[NewChatSuggestions] Non-authenticated user - using default suggestions');
          // Use default suggestions (no encrypted versions for non-auth users)
          fullSuggestionsWithEncrypted = DEFAULT_NEW_CHAT_SUGGESTIONS.map(text => ({
            text,
            encrypted: '' // No encrypted version for default suggestions
          }));
          fullSuggestions = DEFAULT_NEW_CHAT_SUGGESTIONS;
          suggestions = pickRandomThree(fullSuggestions);
          console.debug('[NewChatSuggestions] Loaded default pool:', fullSuggestions.length, 'random shown:', suggestions.length);
          loading = false;
          return;
        }

        // For authenticated users, load from IndexedDB
        await chatDB.init();
        // Small delay to ensure upgrade completion
        await new Promise(resolve => setTimeout(resolve, 100));

        // Load full pool and decrypt, keeping both encrypted and decrypted versions
        const all: NewChatSuggestion[] = await chatDB.getAllNewChatSuggestions();
        const decryptedSuggestions = await Promise.all(
          all.map(async s => {
            const decrypted = await decryptWithMasterKey(s.encrypted_suggestion);
            if (!decrypted) return null;
            return {
              text: decrypted,
              encrypted: s.encrypted_suggestion
            };
          })
        );
        fullSuggestionsWithEncrypted = decryptedSuggestions.filter((s): s is { text: string; encrypted: string } => s !== null);

        // Create decrypted-only array for filtering
        fullSuggestions = fullSuggestionsWithEncrypted.map(s => s.text);

        // Pick 3 random suggestions for empty-input state (fresh each mount)
        suggestions = pickRandomThree(fullSuggestions);
        console.debug('[NewChatSuggestions] Loaded full pool:', fullSuggestions.length, 'random shown:', suggestions.length);
      } catch (error) {
        console.error('[NewChatSuggestions] Error loading suggestions:', error);
        fullSuggestionsWithEncrypted = [];
        fullSuggestions = [];
        suggestions = [];
      } finally {
        loading = false;
      }
    };

    // Initial load
    loadSuggestions();

    // Refresh suggestions when Phase 3 completes (server sends latest suggestions)
    const handleFullSyncReady = (event: CustomEvent) => {
      console.debug('[NewChatSuggestions] fullSyncReady received, refreshing suggestions');
      // Re-load suggestions from DB (they were saved by chatSyncService on phase 3)
      loading = true;
      loadSuggestions();
    };
    chatSyncService.addEventListener('fullSyncReady', handleFullSyncReady as EventListener);

    return () => {
      chatSyncService.removeEventListener('fullSyncReady', handleFullSyncReady as EventListener);
    };
  });

  let filteredSuggestions = $derived.by(() => {
    if (loading) return [];

    if (!messageInputContent || messageInputContent.trim() === '') {
      // Show the pre-picked random 3 when input is empty
      return suggestions.map(s => ({ text: s.text, matchIndex: -1, matchLength: 0 }));
    }

    const searchTerm = messageInputContent.trim();
    const searchTermLower = searchTerm.toLowerCase();

    console.debug('[NewChatSuggestions] Filtering with search term:', {
      searchTerm,
      searchTermLower,
      fullPoolSize: fullSuggestions.length
    });

    // Exact substring match (case-insensitive) across FULL pool
    // Remove duplicates first, then filter and limit to top 3 unique results
    const uniqueSuggestions = Array.from(new Set(fullSuggestions));
    
    const filtered = uniqueSuggestions
      .map(text => {
        const lowerSuggestion = text.toLowerCase();
        const matchIndex = lowerSuggestion.indexOf(searchTermLower);
        return {
          text,
          matchIndex,
          matchLength: searchTerm.length
        };
      })
      .filter(item => item.matchIndex !== -1)
      // Exclude exact matches (100% match) - no point showing what user already typed
      .filter(item => item.text.toLowerCase() !== searchTermLower)
      // Limit to top 3 unique matches
      .slice(0, 3);

    console.debug('[NewChatSuggestions] Filtered results:', filtered.length, 'unique matches');

    return filtered;
  });

  function renderHighlightedText(suggestion: { text: string; matchIndex: number; matchLength: number }) {
    if (suggestion.matchIndex === -1 || !messageInputContent || !messageInputContent.trim()) {
      return suggestion.text;
    }

    const before = suggestion.text.substring(0, suggestion.matchIndex);
    const match = suggestion.text.substring(suggestion.matchIndex, suggestion.matchIndex + suggestion.matchLength);
    const after = suggestion.text.substring(suggestion.matchIndex + suggestion.matchLength);

    return { before, match, after };
  }

  /**
   * Handle suggestion click - track it for deletion and pass to parent
   */
  function handleSuggestionClickWithTracking(suggestionText: string) {
    console.debug('[NewChatSuggestions] Suggestion clicked:', suggestionText);
    
    // For authenticated users, track the suggestion for deletion after sending
    if ($authStore.isAuthenticated) {
      // Find the encrypted version of this suggestion
      const suggestionData = fullSuggestionsWithEncrypted.find(s => s.text === suggestionText);
      
      if (suggestionData && suggestionData.encrypted) {
        // Track this suggestion (with encrypted text) so it can be deleted after the message is sent
        setClickedSuggestion(suggestionData.text, suggestionData.encrypted);
        console.debug('[NewChatSuggestions] Tracked suggestion for deletion');
      } else {
        console.warn('[NewChatSuggestions] Could not find encrypted version of clicked suggestion - skipping tracking');
      }
    } else {
      console.debug('[NewChatSuggestions] Non-authenticated user - not tracking suggestion for deletion');
    }
    
    // Pass to parent handler (which will set it in the message input)
    onSuggestionClick(suggestionText);
  }
</script>

{#if !loading && filteredSuggestions.length > 0}
  <div class="suggestions-wrapper">
    <div class="suggestions-header">
      {touchDevice ? $text('chat.suggestions.header_tap.text') : $text('chat.suggestions.header_click.text')}
    </div>
    <div class="suggestions-container">
      {#each filteredSuggestions as suggestion (suggestion.text)}
      {@const highlighted = renderHighlightedText(suggestion)}
      <button
        class="suggestion-item"
        onclick={() => handleSuggestionClickWithTracking(suggestion.text)}
      >
        {#if typeof highlighted === 'string'}
          {highlighted}
        {:else}
          <span class="text-part">{highlighted.before}</span><span class="text-match">{highlighted.match}</span><span class="text-part">{highlighted.after}</span>
        {/if}
      </button>
    {/each}
    </div>
  </div>
{/if}

<style>
  .suggestions-wrapper {
    animation: fadeIn 200ms ease-out;
    animation-delay: 200ms;
  }

  .suggestions-header {
    color: var(--color-grey-50);
    font-size: 16px;
    font-weight: 500;
    padding: 0 18px;
    letter-spacing: 0.5px;
    opacity: 0.9;
  }

  @keyframes fadeIn {
    from {
      opacity: 0;
    }
    to {
      opacity: 1;
    }
  }

  .suggestions-container {
    display: flex;
    flex-direction: column;
    gap: 5px;
    margin-bottom: 8px;
    padding: 6px 10px;
    background-color: var(--color-grey-15);
    border: 1px solid var(--color-grey-25);
    border-radius: 10px;
  }

  .suggestion-item {
    background-color: transparent;
    border: none;
    padding: 2px 8px;
    font-size: 16px;
    color: var(--color-grey-60);
    cursor: pointer;
    transition: color 0.15s ease;
    white-space: normal;
    border-radius: 6px;
    line-height: 1.2;
    text-align: left;
    height: auto;
    min-height: unset;
    min-width: unset;
    margin-right: 0;
    filter: none;
    width: 100%;
    display: block;
    justify-content: flex-start;
    align-items: flex-start;
    scale: 1;
  }

  .suggestion-item:hover {
    color: var(--color-grey-70);
    scale: 1;
  }

  .suggestion-item:active {
    scale: 1;
  }

  .suggestion-item:hover .text-part {
    color: var(--color-grey-70);
  }

  .suggestion-item .text-part {
    color: var(--color-grey-60);
    transition: color 0.15s ease;
  }

  .suggestion-item .text-match {
    color: var(--color-grey-100);
    font-weight: 500;
  }

  @media (max-width: 730px) {
    .suggestions-container {
      gap: 5px;
      margin-bottom: 6px;
      padding: 5px 8px;
    }

    .suggestions-header {
      padding: 0 15px;
    }

    .suggestion-item {
      font-size: 16px;
      padding: 2px 7px;
    }
  }
</style>
