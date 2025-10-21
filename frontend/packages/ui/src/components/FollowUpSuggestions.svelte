<script lang="ts">
  import { fade } from 'svelte/transition';

  let {
    suggestions = [],
    messageInputContent = '',
    onSuggestionClick
  }: {
    suggestions: string[];
    messageInputContent?: string;
    onSuggestionClick: (suggestion: string) => void;
  } = $props();

  // Full suggestions pool - computed from prop to avoid duplicates
  let fullSuggestions = $derived(Array.from(new Set(suggestions)));

  // Filtered and displayed suggestions based on input content
  let filteredSuggestions = $derived.by(() => {
    // When input is empty, show first 3 suggestions
    if (!messageInputContent || messageInputContent.trim() === '') {
      const displayedSuggestions = fullSuggestions.slice(0, 3);
      console.debug('[FollowUpSuggestions] Showing first 3 suggestions (input empty):', displayedSuggestions.length);
      return displayedSuggestions.map(text => ({ text, matchIndex: -1, matchLength: 0 }));
    }

    // When user is typing, filter across the FULL pool
    const searchTerm = messageInputContent.trim();
    const searchTermLower = searchTerm.toLowerCase();

    console.debug('[FollowUpSuggestions] Filtering with search term:', {
      searchTerm,
      searchTermLower,
      fullPoolSize: fullSuggestions.length
    });

    // Exact substring match (case-insensitive) across FULL pool
    const filtered = fullSuggestions
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

    console.debug('[FollowUpSuggestions] Filtered results:', filtered.length, 'unique matches');

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
</script>

{#if filteredSuggestions.length > 0}
  <div class="suggestions-container" transition:fade={{ duration: 200 }}>
    {#each filteredSuggestions as suggestion (suggestion.text)}
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
    display: flex;
    flex-direction: column;
    gap: 5px;
    margin-bottom: 8px;
    padding: 6px 10px;
    /* Colored block for contrast and readability - using a subtle blue/purple tint */
    background: linear-gradient(135deg, rgba(100, 120, 255, 0.08) 0%, rgba(120, 80, 255, 0.06) 100%);
    border: 1px solid rgba(100, 120, 255, 0.2);
    border-radius: 10px;
    width: 100%;
    max-width: 629px;
    box-shadow: 0 1px 4px rgba(100, 120, 255, 0.1);
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
    background-color: rgba(100, 120, 255, 0.05);
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

    .suggestion-item {
      font-size: 16px;
      padding: 2px 7px;
    }
  }
</style>
