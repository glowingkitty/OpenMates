<script lang="ts">
  import { fade } from 'svelte/transition';
  import { onMount } from 'svelte';
  import { chatDB } from '../services/db';

  let {
    messageInputContent = '',
    onSuggestionClick
  }: {
    messageInputContent?: string;
    onSuggestionClick: (suggestion: string) => void;
  } = $props();

  // Store suggestions with unique IDs to prevent duplicate key errors
  let suggestions = $state<Array<{id: string; text: string}>>([]);
  let loading = $state(true);

  onMount(async () => {
    try {
      // Wait for database to be initialized before accessing it
      // This prevents race condition where component mounts before database is ready
      await chatDB.init();
      
      const randomSuggestions = await chatDB.getRandomNewChatSuggestions(3);
      // Add unique IDs to each suggestion to prevent duplicate key errors
      suggestions = randomSuggestions.map(text => ({ 
        id: crypto.randomUUID(), 
        text 
      }));
    } catch (error) {
      console.error('[NewChatSuggestions] Error loading suggestions:', error);
      suggestions = [];
    } finally {
      loading = false;
    }
  });

  let filteredSuggestions = $derived.by(() => {
    if (loading) return [];

    if (!messageInputContent || messageInputContent.trim() === '') {
      return suggestions.map(s => ({ id: s.id, text: s.text, matchIndex: -1, matchLength: 0 }));
    }

    const searchTerm = messageInputContent.trim();
    const searchTermLower = searchTerm.toLowerCase();

    const filtered = suggestions
      .map(suggestion => {
        const lowerSuggestion = suggestion.text.toLowerCase();
        const matchIndex = lowerSuggestion.indexOf(searchTermLower);
        return {
          id: suggestion.id,
          text: suggestion.text,
          matchIndex,
          matchLength: searchTerm.length
        };
      })
      .filter(item => item.matchIndex !== -1)
      .slice(0, 3);

    return filtered;
  });

  function renderHighlightedText(suggestion: { id: string; text: string; matchIndex: number; matchLength: number }) {
    if (suggestion.matchIndex === -1 || !messageInputContent || !messageInputContent.trim()) {
      return suggestion.text;
    }

    const before = suggestion.text.substring(0, suggestion.matchIndex);
    const match = suggestion.text.substring(suggestion.matchIndex, suggestion.matchIndex + suggestion.matchLength);
    const after = suggestion.text.substring(suggestion.matchIndex + suggestion.matchLength);

    return { before, match, after };
  }
</script>

{#if !loading && filteredSuggestions.length > 0}
  <div class="suggestions-container" transition:fade={{ duration: 200 }}>
    {#each filteredSuggestions as suggestion (suggestion.id)}
      {@const highlighted = renderHighlightedText(suggestion)}
      <button
        class="suggestion-item"
        onclick={() => onSuggestionClick(suggestion.text)}
        transition:fade={{ duration: 150 }}
      >
        {#if typeof highlighted === 'string'}
          {highlighted}
        {:else}
          <span class="text-part">{highlighted.before}</span><span class="text-match">{highlighted.match}</span><span class="text-part">{highlighted.after}</span>
        {/if}
      </button>
    {/each}
  </div>
{/if}

<style>
  .suggestions-container {
    display: inline-flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-bottom: 8px;
    padding: 6px 10px;
    background-color: var(--color-grey-15);
    border: 1px solid var(--color-grey-25);
    border-radius: 10px;
    width: fit-content;
    max-width: 100%;
  }

  .suggestion-item {
    background-color: transparent;
    border: none;
    padding: 3px 8px;
    font-size: 12px;
    color: var(--color-grey-70);
    cursor: pointer;
    transition: all 0.15s ease;
    white-space: nowrap;
    border-radius: 6px;
    line-height: 1.4;
  }

  .suggestion-item:hover {
    background-color: var(--color-grey-25);
  }

  .suggestion-item:hover .text-part {
    color: var(--color-grey-80);
  }

  .suggestion-item:active {
    transform: scale(0.98);
  }

  .suggestion-item .text-part {
    color: var(--color-grey-70);
    transition: color 0.15s ease;
  }

  .suggestion-item .text-match {
    color: var(--color-grey-0);
    font-weight: 500;
  }

  @media (max-width: 730px) {
    .suggestions-container {
      gap: 5px;
      margin-bottom: 6px;
      padding: 5px 8px;
    }

    .suggestion-item {
      font-size: 11px;
      padding: 2px 7px;
    }
  }
</style>
