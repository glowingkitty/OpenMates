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

  // Import text function for translations
  import { text } from '@repo/ui';

  // Detect if device is touch-capable
  // Checks for ontouchstart event support and maxTouchPoints
  const isTouchDevice = () => {
    return (('ontouchstart' in window) ||
            (navigator.maxTouchPoints > 0) ||
            ((navigator as any).msMaxTouchPoints > 0));
  };

  let touchDevice = $state(isTouchDevice());

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

  /**
   * Handle suggestion click - local function like NewChatSuggestions does
   */
  function handleSuggestionClick(suggestionText: string) {
    // console.debug('[FollowUpSuggestions] Suggestion clicked via local handler:', suggestionText);
    // console.debug('[FollowUpSuggestions] onSuggestionClick callback exists:', typeof onSuggestionClick);
    // console.debug('[FollowUpSuggestions] Calling parent callback with:', suggestionText);
    onSuggestionClick(suggestionText);
    // console.debug('[FollowUpSuggestions] Parent callback completed');
  }
</script>

{#if filteredSuggestions.length > 0}
  <div class="suggestions-wrapper" transition:fade={{ duration: 200 }}>
    <div class="suggestions-header">
      {touchDevice ? $text('chat.suggestions.header_tap.text') : $text('chat.suggestions.header_click.text')}
    </div>
    <div class="suggestions-container">
      {#each filteredSuggestions as suggestion (suggestion.text)}
        {@const highlighted = renderHighlightedText(suggestion)}
        <button
          class="suggestion-item"
          onmousedown={(event) => {
            event.preventDefault();
          }}
          onclick={(event) => {
            event.preventDefault();
            event.stopPropagation();
            handleSuggestionClick(suggestion.text);
          }}
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
  </div>
{/if}

<style>
  .suggestions-wrapper {
    animation: fadeIn 200ms ease-out;
    width: 100%;
    max-width: 629px;
  }

  @keyframes fadeIn {
    from {
      opacity: 0;
    }
    to {
      opacity: 1;
    }
  }

  .suggestions-header {
    color: var(--color-grey-50);
    font-size: 16px;
    font-weight: 500;
    padding: 0 18px;
    letter-spacing: 0.5px;
    opacity: 0.9;
    position: relative;
    z-index: 60;
  }

  .suggestions-container {
    display: flex;
    flex-direction: column;
    gap: 5px;
    padding: 6px 10px;
    border-radius: 10px;
    position: relative;
    z-index: 50;
  }

  /* Gradient fade background that extends slightly above the suggestions
     to 10px below the top of the message input field, with 10px edge margins.
     Positioned to not cover the header text. */
  .suggestions-container::before {
    content: '';
    position: absolute;
    top: -100px;
    bottom: -10px;
    left: -9999px;
    right: -9999px;
    /* Gradient stays solid longer with a smoother, more gradual fade at the top
       This ensures smooth transition while maintaining readability */
    background: linear-gradient(to top, var(--color-grey-20) 0%, var(--color-grey-20) 60%, transparent 100%);
    border-radius: 10px;
    z-index: -1;
    pointer-events: none;
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

    .suggestion-item {
      font-size: 16px;
      padding: 2px 7px;
    }

    .suggestions-header {
      padding: 0 15px;
    }
  }
</style>
