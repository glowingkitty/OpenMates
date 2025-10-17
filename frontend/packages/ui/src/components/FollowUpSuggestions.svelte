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

  let filteredSuggestions = $derived.by(() => {
    if (!messageInputContent || messageInputContent.trim() === '') {
      return suggestions.slice(0, 3).map(s => ({ text: s, matchIndex: -1, matchLength: 0 }));
    }

    const searchTerm = messageInputContent.trim();
    const searchTermLower = searchTerm.toLowerCase();

    const filtered = suggestions
      .map(suggestion => {
        const lowerSuggestion = suggestion.toLowerCase();
        const matchIndex = lowerSuggestion.indexOf(searchTermLower);
        return {
          text: suggestion,
          matchIndex,
          matchLength: searchTerm.length
        };
      })
      .filter(item => item.matchIndex !== -1)
      .slice(0, 3);

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
    /* Changed from inline-flex to flex for vertical layout */
    display: flex;
    flex-direction: column;
    gap: 4px; /* Reduced gap between suggestions for less height */
    margin-bottom: 10px;
    padding: 10px 14px;
    /* Enhanced background with slight transparency for better readability */
    background-color: var(--color-grey-10);
    border: 1px solid var(--color-grey-30);
    border-radius: 12px;
    width: 100%;
    max-width: 100%;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
  }

  .suggestion-item {
    background-color: transparent;
    border: none;
    padding: 6px 10px;
    font-size: 14px; /* Increased from 12px to 14px */
    color: var(--color-grey-70);
    cursor: pointer;
    transition: all 0.15s ease;
    white-space: normal; /* Allow wrapping for longer suggestions */
    text-align: left;
    border-radius: 8px;
    line-height: 1.5;
    width: 100%;
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
    color: var(--color-grey-90);
    font-weight: 600;
    background-color: var(--color-grey-30);
    padding: 1px 3px;
    border-radius: 3px;
  }

  @media (max-width: 730px) {
    .suggestions-container {
      gap: 3px;
      margin-bottom: 8px;
      padding: 8px 12px;
    }

    .suggestion-item {
      font-size: 13px;
      padding: 5px 8px;
    }
  }
</style>
