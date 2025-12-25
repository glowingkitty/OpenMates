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
  import { DEFAULT_NEW_CHAT_SUGGESTION_KEYS } from '../demo_chats/defaultNewChatSuggestions';
  import { get } from 'svelte/store';
  import { _, locale } from 'svelte-i18n';
  import NewChatSuggestionContextMenu from './NewChatSuggestionContextMenu.svelte';

  let {
    messageInputContent = '',
    onSuggestionClick
  }: {
    messageInputContent?: string;
    onSuggestionClick: (suggestion: string) => void;
  } = $props();

  /**
   * Strip HTML tags from text to display as plain text
   * Converts HTML like "<strong><mark>Open</mark>Mates</strong>" to "OpenMates"
   */
  function stripHtmlTags(html: string): string {
    if (!html) return '';
    // Create a temporary div to parse HTML
    const tmp = document.createElement('div');
    tmp.innerHTML = html;
    return tmp.textContent || tmp.innerText || '';
  }

  /**
   * Shuffle an array using Fisher-Yates algorithm
   * This ensures suggestions are displayed in random order rather than always newest-first
   * @param array - The array to shuffle
   * @returns A new shuffled array (original array is not modified)
   */
  function shuffleArray<T>(array: T[]): T[] {
    const shuffled = [...array]; // Create a copy to avoid mutating the original
    for (let i = shuffled.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
    }
    return shuffled;
  }

  // Detect if device is touch-capable
  // Checks for ontouchstart event support and maxTouchPoints
  const isTouchDevice = () => {
    return (('ontouchstart' in window) ||
            (navigator.maxTouchPoints > 0) ||
            ((navigator as any).msMaxTouchPoints > 0));
  };

  let touchDevice = $state(isTouchDevice());

  // Force reactivity to language changes
  let currentLocale = $state($locale);

  // Context menu state
  let contextMenu = $state({
    show: false,
    x: 0,
    y: 0,
    suggestionText: '',
    encryptedSuggestion: ''
  });

  // Touch handling for context menu
  let touchStartTime = $state(0);
  let touchTimer: number | undefined;

  // Full suggestions pool with both encrypted and decrypted text
  let fullSuggestionsWithEncrypted = $state<Array<{ text: string; encrypted: string }>>([]);
  // Full suggestions pool (decrypted only), used for filtering
  let fullSuggestions = $state<string[]>([]);
  let loading = $state(true);
  // Carousel state - tracks current page (0-indexed)
  let currentSlide = $state(0);
  let suggestionsPerSlide = 3;
  // Track previous search term to reset pagination when search changes
  let previousSearchTerm = $state<string>('');
  let previousAuthState = $authStore.isAuthenticated;

  /**
   * Load suggestions from IndexedDB (auth) or defaults (non-auth)
   */
  const loadSuggestions = async () => {
      loading = true;
      
      // For non-authenticated users, use default suggestions instead of IndexedDB
      if (!$authStore.isAuthenticated) {
          console.debug('[NewChatSuggestions] Non-authenticated user - using default suggestions');
          // Translate the suggestion keys to the current locale
          const t = get(_);
          const translatedSuggestions = DEFAULT_NEW_CHAT_SUGGESTION_KEYS.map(key => t(key));
          
          // Strip HTML tags from translated suggestions to display as plain text
          const plainTextSuggestions = translatedSuggestions.map(s => stripHtmlTags(s));
          
          // Use default suggestions (no encrypted versions for non-auth users)
          const defaultSuggestionsWithEncrypted = plainTextSuggestions.map(text => ({
              text,
              encrypted: '' // No encrypted version for default suggestions
          }));
          // Shuffle default suggestions for variety
          fullSuggestionsWithEncrypted = shuffleArray(defaultSuggestionsWithEncrypted);
          fullSuggestions = fullSuggestionsWithEncrypted.map(s => s.text);
          console.debug('[NewChatSuggestions] Loaded default pool:', fullSuggestions.length);
          currentSlide = 0; // Reset to first page when suggestions are reloaded
          loading = false;
          return;
      }

      // For authenticated users, load from IndexedDB
      // Handle case where database might be unavailable (e.g., during logout/deletion)
      try {
          await chatDB.init();
          // Small delay to ensure upgrade completion
          await new Promise(resolve => setTimeout(resolve, 100));

          // Load full pool and decrypt, keeping both encrypted and decrypted versions
          const all: NewChatSuggestion[] = await chatDB.getAllNewChatSuggestions();
          const decryptedSuggestions = await Promise.all(
              all.map(async s => {
                  const decrypted = await decryptWithMasterKey(s.encrypted_suggestion);
                  if (!decrypted) return null;
                  // Strip HTML tags from decrypted suggestions to display as plain text
                  const plainText = stripHtmlTags(decrypted);
                  return {
                      text: plainText,
                      encrypted: s.encrypted_suggestion
                  };
              })
          );
          fullSuggestionsWithEncrypted = decryptedSuggestions.filter((s): s is { text: string; encrypted: string } => s !== null);

          // Shuffle suggestions to ensure random order (not always newest-first)
          // This provides variety in what users see each time suggestions are loaded
          fullSuggestionsWithEncrypted = shuffleArray(fullSuggestionsWithEncrypted);

          // Create decrypted-only array for filtering (maintains shuffled order)
          fullSuggestions = fullSuggestionsWithEncrypted.map(s => s.text);

          // CRITICAL FIX: If authenticated user has no suggestions, fall back to default suggestions
          // This ensures users always see suggestions even if they haven't been set up yet
          if ($authStore.isAuthenticated && fullSuggestions.length === 0) {
              console.debug('[NewChatSuggestions] Authenticated user has no suggestions - falling back to default suggestions');
              // Translate the suggestion keys to the current locale
              const t = get(_);
              const translatedSuggestions = DEFAULT_NEW_CHAT_SUGGESTION_KEYS.map(key => t(key));
              
              // Strip HTML tags from translated suggestions to display as plain text
              const plainTextSuggestions = translatedSuggestions.map(s => stripHtmlTags(s));
              
              // Use default suggestions (no encrypted versions for fallback)
              const defaultSuggestionsWithEncrypted = plainTextSuggestions.map(text => ({
                  text,
                  encrypted: '' // No encrypted version for default suggestions
              }));
              // Shuffle default suggestions for variety
              fullSuggestionsWithEncrypted = shuffleArray(defaultSuggestionsWithEncrypted);
              fullSuggestions = fullSuggestionsWithEncrypted.map(s => s.text);
          }

          console.debug('[NewChatSuggestions] Loaded full pool:', fullSuggestions.length);
          currentSlide = 0; // Reset to first page when suggestions are reloaded
      } catch (error) {
          // Handle database errors gracefully (e.g., database being deleted during logout)
          // For non-authenticated users, this is expected - they don't need suggestions from DB
          if (!$authStore.isAuthenticated) {
              console.debug('[NewChatSuggestions] Database unavailable for non-authenticated user - using default suggestions');
              // Use default suggestions for non-authenticated users
              const t = get(_);
              const translatedSuggestions = DEFAULT_NEW_CHAT_SUGGESTION_KEYS.map(key => t(key));
              const plainTextSuggestions = translatedSuggestions.map(s => stripHtmlTags(s));
              const defaultSuggestionsWithEncrypted = plainTextSuggestions.map(text => ({
                  text,
                  encrypted: ''
              }));
              // Shuffle default suggestions for variety
              fullSuggestionsWithEncrypted = shuffleArray(defaultSuggestionsWithEncrypted);
              fullSuggestions = fullSuggestionsWithEncrypted.map(s => s.text);
              currentSlide = 0; // Reset to first page when suggestions are reloaded
          } else {
              console.error('[NewChatSuggestions] Error loading suggestions:', error);
              // For authenticated users with errors, also fall back to defaults
              const t = get(_);
              const translatedSuggestions = DEFAULT_NEW_CHAT_SUGGESTION_KEYS.map(key => t(key));
              const plainTextSuggestions = translatedSuggestions.map(s => stripHtmlTags(s));
              const defaultSuggestionsWithEncrypted = plainTextSuggestions.map(text => ({
                  text,
                  encrypted: ''
              }));
              // Shuffle default suggestions for variety
              fullSuggestionsWithEncrypted = shuffleArray(defaultSuggestionsWithEncrypted);
              fullSuggestions = fullSuggestionsWithEncrypted.map(s => s.text);
              currentSlide = 0; // Reset to first page when suggestions are reloaded
          }
      } finally {
          loading = false;
      }
  };

  // React to auth state changes (e.g., logout) - reload suggestions when auth state actually changes
  // This ensures non-authenticated users get default suggestions immediately after logout
  // Only reload when auth state transitions (not on every reactive update)
  $effect(() => {
    const isAuthenticated = $authStore.isAuthenticated;
    // Only reload if auth state actually changed (not just a reactive update)
    if (previousAuthState !== isAuthenticated) {
      console.debug('[NewChatSuggestions] Auth state changed, reloading suggestions. Previous:', previousAuthState, 'Current:', isAuthenticated);
      previousAuthState = isAuthenticated;
      loadSuggestions();
    }
  });

  onMount(() => {
    // Initial load
    loadSuggestions();

    // Refresh suggestions when Phase 3 completes (server sends latest suggestions)
    const handleFullSyncReady = (event: CustomEvent) => {
      console.debug('[NewChatSuggestions] fullSyncReady received, refreshing suggestions');
      // Re-load suggestions from DB (they were saved by chatSyncService on phase 3)
      loadSuggestions();
    };
    chatSyncService.addEventListener('fullSyncReady', handleFullSyncReady as EventListener);

    // Add language change listener to reload suggestions when language changes
    const handleLanguageChange = () => {
      // Update locale for header text reactivity
      currentLocale = $locale;
      
      if (!$authStore.isAuthenticated) {
          console.debug('[NewChatSuggestions] Language changed, reloading default suggestions');
          loadSuggestions();
      }
    };
    window.addEventListener('language-changed', handleLanguageChange);

    return () => {
      chatSyncService.removeEventListener('fullSyncReady', handleFullSyncReady as EventListener);
      window.removeEventListener('language-changed', handleLanguageChange);
    };
  });

  // Reset pagination when search term changes
  $effect(() => {
    const searchTerm = (messageInputContent || '').trim();
    if (searchTerm !== previousSearchTerm) {
      previousSearchTerm = searchTerm;
      currentSlide = 0; // Reset to first page when search changes
      console.debug('[NewChatSuggestions] Search term changed, resetting to first page');
    }
  });

  // CRITICAL: Reset currentSlide if it's beyond available complete pages
  // This can happen when filtering reduces the number of complete pages
  $effect(() => {
    if (currentSlide >= totalCompletePages && totalCompletePages > 0) {
      console.debug('[NewChatSuggestions] Current slide beyond complete pages, resetting to 0:', {
        currentSlide,
        totalCompletePages
      });
      currentSlide = 0;
    }
  });

  // Get all available suggestions (either all when empty, or filtered when searching)
  let filteredSuggestions = $derived.by(() => {
    if (loading) return [];

    if (!messageInputContent || messageInputContent.trim() === '') {
      // When input is empty, return all suggestions (will be paginated)
      // Suggestions are already shuffled when loaded, so we maintain that order
      const uniqueSuggestions = Array.from(new Set(fullSuggestions));
      return uniqueSuggestions.map(text => ({ 
        text, 
        matchIndex: -1, 
        matchLength: 0 
      }));
    }

    const searchTerm = messageInputContent.trim();
    const searchTermLower = searchTerm.toLowerCase();

    console.debug('[NewChatSuggestions] Filtering with search term:', {
      searchTerm,
      searchTermLower,
      fullPoolSize: fullSuggestions.length
    });

    // Exact substring match (case-insensitive) across FULL pool
    // Remove duplicates first, then filter (return ALL matches, not limited to 3)
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
      .filter(item => item.text.toLowerCase() !== searchTermLower);

    // Shuffle filtered results to avoid always showing the same matches first
    // This provides variety when multiple suggestions match the search term
    const shuffledFiltered = shuffleArray(filtered);

    console.debug('[NewChatSuggestions] Filtered results:', shuffledFiltered.length, 'unique matches');

    return shuffledFiltered;
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

  /**
   * Handle context menu (right-click or long touch)
   */
  function handleContextMenu(event: MouseEvent | TouchEvent, suggestionText: string) {
    if (!$authStore.isAuthenticated) {
      return; // Only show context menu for authenticated users
    }

    event.preventDefault();
    event.stopPropagation();

    // Find the encrypted version of this suggestion
    const suggestionData = fullSuggestionsWithEncrypted.find(s => s.text === suggestionText);
    if (!suggestionData || !suggestionData.encrypted) {
      console.warn('[NewChatSuggestions] Could not find encrypted version of suggestion for context menu');
      return;
    }

    // Get position for context menu
    let x = 0;
    let y = 0;

    if (event instanceof MouseEvent) {
      x = event.clientX;
      y = event.clientY;
    } else if (event instanceof TouchEvent && event.touches.length > 0) {
      x = event.touches[0].clientX;
      y = event.touches[0].clientY;
    }

    // Show context menu
    contextMenu = {
      show: true,
      x,
      y,
      suggestionText,
      encryptedSuggestion: suggestionData.encrypted
    };

    console.debug('[NewChatSuggestions] Context menu shown for suggestion:', suggestionText);
  }

  /**
   * Handle touch start for long-press detection
   */
  function handleTouchStart(event: TouchEvent, suggestionText: string) {
    touchStartTime = Date.now();

    // Clear any existing timer
    if (touchTimer) {
      clearTimeout(touchTimer);
    }

    // Start timer for long press (500ms)
    touchTimer = window.setTimeout(() => {
      handleContextMenu(event, suggestionText);
    }, 500);
  }

  /**
   * Handle touch end - cancel long press if it's a quick tap
   */
  function handleTouchEnd(event: TouchEvent, suggestionText: string) {
    const touchDuration = Date.now() - touchStartTime;

    // Clear the timer
    if (touchTimer) {
      clearTimeout(touchTimer);
      touchTimer = undefined;
    }

    // If it was a short tap (less than 500ms), handle as regular click
    if (touchDuration < 500) {
      handleSuggestionClickWithTracking(suggestionText);
    }

    // Prevent default to avoid any unwanted behaviors
    event.preventDefault();
  }

  /**
   * Handle touch move - cancel context menu if user moves finger
   */
  function handleTouchMove() {
    if (touchTimer) {
      clearTimeout(touchTimer);
      touchTimer = undefined;
    }
  }

  /**
   * Close context menu
   */
  function handleContextMenuClose() {
    contextMenu = {
      show: false,
      x: 0,
      y: 0,
      suggestionText: '',
      encryptedSuggestion: ''
    };
  }

  /**
   * Handle context menu delete action
   */
  async function handleContextMenuDelete() {
    if (!contextMenu.encryptedSuggestion) {
      console.warn('[NewChatSuggestions] No encrypted suggestion to delete');
      return;
    }

    try {
      console.debug('[NewChatSuggestions] Deleting suggestion from IndexedDB and server:', contextMenu.suggestionText);

      // Delete from IndexedDB
      const deleteResult = await chatDB.deleteNewChatSuggestionByEncrypted(contextMenu.encryptedSuggestion);

      if (deleteResult) {
        console.debug('[NewChatSuggestions] Successfully deleted suggestion from IndexedDB');

        // Delete from server
        try {
          await chatSyncService.sendDeleteNewChatSuggestion(contextMenu.encryptedSuggestion);
          console.debug('[NewChatSuggestions] Successfully deleted suggestion from server');
        } catch (serverError) {
          console.warn('[NewChatSuggestions] Failed to delete suggestion from server:', serverError);
          // Continue anyway - local deletion succeeded
        }

        // Reload suggestions to update the display
        loading = true;
        loadSuggestions();
      } else {
        console.error('[NewChatSuggestions] Failed to delete suggestion from IndexedDB');
      }
    } catch (error) {
      console.error('[NewChatSuggestions] Error deleting suggestion:', error);
    }

    // Close context menu
    handleContextMenuClose();
  }

  /**
   * Calculate the number of complete pages (pages with exactly 3 suggestions)
   * First page is excluded from this count as it can have 1-3 results
   * Only subsequent pages (page 1+) need exactly 3 suggestions
   */
  let totalCompletePages = $derived(Math.floor(filteredSuggestions.length / suggestionsPerSlide));

  /**
   * Calculate if there are any complete pages after the first page
   * Used to determine if the next button should be shown
   */
  let hasCompletePagesAfterFirst = $derived(filteredSuggestions.length > suggestionsPerSlide && totalCompletePages > 1);

  /**
   * Move to next page of suggestions
   * First page can have 1-3 results, subsequent pages must have exactly 3
   * Loops back to first page when reaching the end
   */
  function nextSlide() {
    // Check if there are complete pages after the first page
    if (!hasCompletePagesAfterFirst) return; // No complete pages after first page
    
    // Calculate the maximum slide we can navigate to
    // First page (0) + complete pages after first (totalCompletePages - 1)
    const maxSlide = totalCompletePages - 1;
    
    if (currentSlide < maxSlide) {
      // Move to next complete page
      currentSlide++;
    } else {
      // Loop back to first page when reaching the end
      currentSlide = 0;
      console.debug('[NewChatSuggestions] Reached last complete page, looping back to first page');
    }
  }

  /**
   * Get the currently visible suggestions for the current page
   * First page (page 0): Shows suggestions even if there are fewer than 3 (1 or 2 results)
   * Subsequent pages: Only shows if there are exactly 3 suggestions (complete page)
   */
  let visibleSuggestions = $derived.by(() => {
    if (filteredSuggestions.length === 0) return [];
    
    // Calculate pagination for current page
    const startIdx = currentSlide * suggestionsPerSlide;
    const endIdx = startIdx + suggestionsPerSlide;
    const paginated = filteredSuggestions.slice(startIdx, endIdx);
    
    // EXCEPTION: First page (page 0) can show 1 or 2 results when searching
    // This ensures users see search results even if there are only 1-2 matches
    if (currentSlide === 0) {
      // First page: Show if we have at least 1 suggestion
      if (paginated.length > 0) {
        console.debug('[NewChatSuggestions] Visible suggestions (first page, may be incomplete):', {
          currentSlide,
          startIdx,
          endIdx,
          totalSuggestions: filteredSuggestions.length,
          visibleCount: paginated.length
        });
        return paginated;
      }
    } else {
      // Subsequent pages: Only show if we have exactly 3 (complete page)
      if (paginated.length !== suggestionsPerSlide) {
        console.debug('[NewChatSuggestions] Incomplete page detected (not first page), returning empty array:', {
          currentSlide,
          startIdx,
          endIdx,
          totalSuggestions: filteredSuggestions.length,
          visibleCount: paginated.length,
          expectedCount: suggestionsPerSlide
        });
        return [];
      }
    }
    
    console.debug('[NewChatSuggestions] Visible suggestions (complete page):', {
      currentSlide,
      startIdx,
      endIdx,
      totalSuggestions: filteredSuggestions.length,
      visibleCount: paginated.length
    });
    
    return paginated;
  });
  
  /**
   * Determine if next button should be enabled
   * Only enabled when there are complete pages after the first page
   * (First page can have 1-3 results, but subsequent pages must have exactly 3)
   */
  let canNextSlide = $derived(hasCompletePagesAfterFirst);
</script>

{#if !loading && visibleSuggestions.length > 0}
  <div class="suggestions-wrapper">
    <div class="suggestions-header">
      {#key currentLocale}
        {touchDevice ? $text('chat.suggestions.header_tap.text') : $text('chat.suggestions.header_click.text')}
      {/key}
    </div>
    <div class="carousel-container">
      <div class="suggestions-container">
        {#each visibleSuggestions as suggestion (suggestion.text)}
        {@const highlighted = renderHighlightedText(suggestion)}
        <button
          class="suggestion-item"
          onclick={() => handleSuggestionClickWithTracking(suggestion.text)}
          oncontextmenu={(event) => handleContextMenu(event, suggestion.text)}
          ontouchstart={(event) => handleTouchStart(event, suggestion.text)}
          ontouchend={(event) => handleTouchEnd(event, suggestion.text)}
          ontouchmove={handleTouchMove}
        >
          {#if typeof highlighted === 'string'}
            {highlighted}
          {:else}
            <span class="text-part">{highlighted.before}</span><span class="text-match">{highlighted.match}</span><span class="text-part">{highlighted.after}</span>
          {/if}
        </button>
      {/each}
      </div>
      {#if canNextSlide}
        <button
          class="carousel-nav next-nav"
          onclick={nextSlide}
          aria-label="Next suggestions"
        >
          →
        </button>
      {/if}
    </div>
  </div>
{/if}

<!-- Context menu for suggestion deletion -->
<NewChatSuggestionContextMenu
  show={contextMenu.show}
  x={contextMenu.x}
  y={contextMenu.y}
  suggestionText={contextMenu.suggestionText}
  encryptedSuggestion={contextMenu.encryptedSuggestion}
  on:close={handleContextMenuClose}
  on:delete={handleContextMenuDelete}
/>

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

  .carousel-container {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 8px;
  }

  .suggestions-container {
    display: flex;
    flex-direction: column;
    gap: 5px;
    flex: 1;
    padding: 6px 10px;
    background-color: var(--color-grey-15);
    border: 1px solid var(--color-grey-25);
    border-radius: 10px;
    min-height: 60px;
  }

  .carousel-nav {
    background-color: var(--color-grey-15);
    border: 1px solid var(--color-grey-25);
    border-radius: 10px;
    color: var(--color-grey-60);
    cursor: pointer;
    padding: 8px 12px;
    font-size: 18px;
    font-weight: 500;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all 0.15s ease;
    min-width: 40px;
    height: auto;
  }

  .carousel-nav:hover:not(:disabled) {
    background-color: var(--color-grey-20);
    color: var(--color-grey-70);
    border-color: var(--color-grey-35);
  }

  .carousel-nav:active:not(:disabled) {
    transform: scale(0.95);
  }

  .carousel-nav:disabled {
    opacity: 0.3;
    cursor: not-allowed;
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
    .carousel-container {
      gap: 6px;
      margin-bottom: 6px;
    }

    .suggestions-container {
      gap: 5px;
      padding: 5px 8px;
      min-height: 55px;
    }

    .suggestions-header {
      padding: 0 15px;
    }

    .carousel-nav {
      padding: 6px 10px;
      font-size: 16px;
      min-width: 36px;
    }

    .suggestion-item {
      font-size: 16px;
      padding: 2px 7px;
    }
  }
</style>
