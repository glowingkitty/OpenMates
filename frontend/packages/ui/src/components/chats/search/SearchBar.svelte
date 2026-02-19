<!--
  SearchBar.svelte
  Search input bar placed at the top of the chat list sidebar.
  Features:
  - Search icon + text input + close (X) button
  - 250ms debounce on input to avoid thrashing during typing
  - Cmd+K / Ctrl+K keyboard shortcut to focus
  - Dispatches 'search' event with the debounced query
  - Dispatches 'close' event when X is clicked or Escape is pressed
-->
<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { text } from '@repo/ui';

  // Props using Svelte 5 runes
  interface Props {
    /** Called when the debounced search query changes */
    onSearch: (query: string) => void;
    /** Called when search is closed (X button or Escape) */
    onClose: () => void;
    /** Called when ArrowDown is pressed in the input (to move focus to results) */
    onArrowDown?: () => void;
    /** Called when ArrowUp is pressed in the input (to move focus within results) */
    onArrowUp?: () => void;
    /**
     * Initial query to pre-populate the search input.
     * Used when the panel is reopened after being closed while search was active,
     * so the user sees their previous query and can continue from where they left off.
     */
    initialQuery?: string;
  }

  let { onSearch, onClose, onArrowDown, onArrowUp, initialQuery = '' }: Props = $props();

  // Local state — initialize from initialQuery so the search is restored on panel reopen
  let query = $state(initialQuery);
  let inputElement: HTMLInputElement | null = $state(null);
  let debounceTimer: ReturnType<typeof setTimeout> | null = null;

  /** Debounce delay in ms — 250ms is the sweet spot for responsive feel without thrashing */
  const DEBOUNCE_MS = 250;

  /**
   * Handle input changes with debounce.
   * Fires onSearch after user stops typing for DEBOUNCE_MS.
   */
  function handleInput(): void {
    if (debounceTimer) {
      clearTimeout(debounceTimer);
    }
    debounceTimer = setTimeout(() => {
      onSearch(query);
    }, DEBOUNCE_MS);
  }

  /**
   * Handle key events on the input:
   * - Escape: close search
   * - ArrowDown/Up: delegate to search results for keyboard navigation
   */
  function handleKeyDown(event: KeyboardEvent): void {
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      handleClose();
    } else if (event.key === 'ArrowDown') {
      event.preventDefault();
      onArrowDown?.();
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      onArrowUp?.();
    }
  }

  /**
   * Close search: clear query and notify parent.
   */
  function handleClose(): void {
    query = '';
    if (debounceTimer) {
      clearTimeout(debounceTimer);
    }
    onClose();
  }

  /**
   * Global keyboard shortcut handler for Cmd+K / Ctrl+K to focus the search input.
   */
  function handleGlobalKeyDown(event: KeyboardEvent): void {
    if ((event.metaKey || event.ctrlKey) && event.key === 'k') {
      event.preventDefault();
      event.stopPropagation();
      inputElement?.focus();
    }
  }

  onMount(() => {
    // Focus the search input when the component mounts
    // Use a short delay to ensure the DOM is ready
    setTimeout(() => {
      inputElement?.focus();
    }, 50);

    // If we have an initial query (restored from a previous search session),
    // immediately fire onSearch so the results are re-populated without any user interaction.
    if (initialQuery && initialQuery.trim().length > 0) {
      onSearch(initialQuery);
    }

    // Register global keyboard shortcut
    window.addEventListener('keydown', handleGlobalKeyDown);
  });

  onDestroy(() => {
    if (debounceTimer) {
      clearTimeout(debounceTimer);
    }
    window.removeEventListener('keydown', handleGlobalKeyDown);
  });
</script>

<div class="search-bar">
  <span class="search-icon clickable-icon icon_search"></span>
  <input
    bind:this={inputElement}
    bind:value={query}
    type="search"
    class="search-input"
    placeholder={$text('chats.search.placeholder')}
    oninput={handleInput}
    onkeydown={handleKeyDown}
    autocomplete="off"
    autocorrect="off"
    spellcheck="false"
  />
  <button
    class="search-close-button clickable-icon icon_close"
    aria-label={$text('activity.close')}
    onclick={handleClose}
  ></button>
</div>

<style>
  .search-bar {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    background-color: var(--color-grey-20);
    border-radius: 12px;
    border: 1px solid var(--color-grey-25);
    transition: border-color 0.15s ease;
  }

  .search-bar:focus-within {
    border-color: var(--color-grey-50);
  }

  .search-icon {
    flex-shrink: 0;
    width: 20px;
    height: 20px;
    opacity: 0.5;
  }

  .search-input {
    flex: 1;
    border: none;
    background: transparent;
    color: var(--color-font-primary);
    font-size: 15px;
    padding: 4px 0;
    outline: none;
    min-width: 0;
    /* Override browser default search input styles */
    -webkit-appearance: none;
    appearance: none;
  }

  .search-input::placeholder {
    color: var(--color-font-field-placeholder);
  }

  /* Remove the default clear button in search inputs (we have our own X) */
  .search-input::-webkit-search-cancel-button {
    display: none;
    -webkit-appearance: none;
  }

  .search-close-button {
    flex-shrink: 0;
    width: 20px;
    height: 20px;
    cursor: pointer;
    opacity: 0.5;
    transition: opacity 0.15s ease;
    /* NOTE: Do NOT set background here — button.clickable-icon sets
       background: var(--color-primary) which is used as the mask fill color.
       Overriding it to transparent makes the icon invisible. */
    border: none;
    padding: 0;
  }

  .search-close-button:hover {
    opacity: 1;
  }
</style>
