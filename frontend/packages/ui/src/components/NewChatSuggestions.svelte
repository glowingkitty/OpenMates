<!--
  NewChatSuggestions.svelte — Horizontal suggestion cards for the new chat screen.

  Each card shows the app's color gradient background, a skill or app icon (white),
  and the suggestion text in white. Clicking a card copies its text into the message
  input and hides the card. Multiple cards can be clicked to combine suggestions.

  Layout: horizontally scrollable row of 5 randomly selected suggestion cards.
  Suggestions are re-randomized on every mount (page reload / new chat).

  Architecture: docs/architecture/new-chat-suggestions.md
  Related: ActiveChat.svelte (parent), suggestionTracker.ts (click tracking)
-->
<script lang="ts">
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
  import { locale } from 'svelte-i18n';
  import NewChatSuggestionContextMenu from './NewChatSuggestionContextMenu.svelte';
  import Icon from './Icon.svelte';
  import { appSkillsStore } from '../stores/appSkillsStore';
  import { search as performSearch } from '../services/searchService';
  import { chatMetadataCache } from '../services/chatMetadataCache';
  import { getLucideIcon, getValidIconName, getFallbackIconForCategory, getCategoryGradientColors } from '../utils/categoryUtils';
  import { isDemoChat, isLegalChat } from '../demo_chats';

  /** Number of suggestion cards to show in the scrollable row */
  const VISIBLE_COUNT = 10;

  /** Minimum word count for suggestion body text (after stripping prefix).
   *  Suggestions with fewer words are too vague and get filtered out. */
  const MIN_BODY_WORDS = 4;

  /** Maximum number of existing chat results to show in the suggestion row */
  const MAX_CHAT_RESULTS = 5;

  let {
    onSuggestionClick,
    onChatNavigate,
    messageInputContent = ''
  }: {
    onSuggestionClick: (suggestion: string) => void;
    onChatNavigate: (chatId: string) => void;
    messageInputContent?: string;
  } = $props();

  // Apps metadata for icon resolution
  let appsMetadata = $state(appSkillsStore.getState());

  /**
   * Parsed suggestion: splits "[app_id-skill_id] body text" or "[app_id] body text".
   * Returns null appId/subId if no valid prefix is present (fallback to 'ai' app).
   */
  interface ParsedSuggestionMeta {
    appId: string;               // e.g. "web", "ai" (always set — defaults to 'ai')
    subId: string | null;        // e.g. "search" (null when app-only prefix)
    body: string;                // Text to insert on click (without prefix)
  }

  /**
   * Parse a raw suggestion string of the form "[app_id-skill_id] body text" or
   * "[app_id] body text". LLMs sometimes generate dashes in the skill name portion
   * (e.g. "reminder-set-reminder") instead of underscores ("reminder-set_reminder").
   * We correct for this by replacing dashes in the subId portion with underscores,
   * then validate against the known app skills store.
   *
   * If no valid prefix is found, defaults to appId='ai' with no skill.
   */
  function parseSuggestion(raw: string): ParsedSuggestionMeta {
    // Match [prefix] at the start — prefix can contain alphanumerics, underscores, dashes
    const match = raw.match(/^\[([a-z0-9_-]+)\]\s*(.+)$/i);
    if (!match) {
      return { appId: 'ai', subId: null, body: raw };
    }
    const prefix = match[1];
    const body = match[2].trim();
    const dashIdx = prefix.indexOf('-');

    if (dashIdx === -1) {
      // App-only prefix like [ai], [code], [mail]
      const appId = prefix;
      const app = appsMetadata?.apps?.[appId];
      if (app) {
        return { appId, subId: null, body };
      }
      // Unknown app — fallback to 'ai'
      return { appId: 'ai', subId: null, body };
    }

    // App + skill prefix like [web-search], [images-generate], [reminder-set-reminder]
    const appId = prefix.substring(0, dashIdx);
    const subIdRaw = prefix.substring(dashIdx + 1);
    // Replace dashes with underscores to correct LLM errors (e.g. "set_reminder" variant).
    // Some YAML skill IDs use dashes (e.g. "set-reminder"), so we check both forms.
    const subIdUnderscored = subIdRaw.replace(/-/g, '_');

    // Validate against the known app skills/focus modes store — try both dash and underscore forms
    const app = appsMetadata?.apps?.[appId];
    const matchedSkill = app?.skills?.find(s => s.id === subIdRaw || s.id === subIdUnderscored);
    const matchedFocus = !matchedSkill
      ? app?.focus_modes?.find(f => f.id === subIdRaw || f.id === subIdUnderscored)
      : undefined;

    if (app && (matchedSkill || matchedFocus)) {
      // Return the actual stored ID (preserves dashes if the YAML uses dashes)
      const actualSubId = (matchedSkill ?? matchedFocus)!.id;
      return { appId, subId: actualSubId, body };
    }

    // Valid app but unknown skill — show app icon only
    if (app) {
      return { appId, subId: null, body };
    }

    // Unknown app entirely — fallback to 'ai'
    return { appId: 'ai', subId: null, body };
  }

  /**
   * Resolve the icon name for the suggestion card.
   * Priority: skill/focus icon_image > app icon_image > appId fallback.
   * Returns the icon name string (svg filename without extension).
   */
  function resolveIconName(appId: string, subId: string | null): string {
    const app = appsMetadata?.apps?.[appId];
    if (!app) return appId;

    if (subId) {
      // Check skills first — try exact match and dash↔underscore variant
      const subIdAlt = subId.includes('-') ? subId.replace(/-/g, '_') : subId.replace(/_/g, '-');
      const skill = app.skills?.find(s => s.id === subId || s.id === subIdAlt);
      if (skill?.icon_image) return skill.icon_image.replace(/\.svg$/i, '').trim();

      // Check focus modes
      const focus = app.focus_modes?.find(f => f.id === subId || f.id === subIdAlt);
      if (focus?.icon_image) return focus.icon_image.replace(/\.svg$/i, '').trim();
    }

    // Fallback to app icon
    if (app.icon_image) return app.icon_image.replace(/\.svg$/i, '').trim();

    // Last resort: use appId as icon name
    return appId;
  }

  /**
   * Get the CSS variable name for the app's gradient color.
   * Maps icon names to app IDs where they differ (mirrors Icon.svelte logic).
   */
  function getAppCssGradient(appId: string): string {
    // Mirror Icon.svelte's getAppIdForCssVariable mappings
    const mappings: Record<string, string> = {
      'image': 'images',
      'book': 'books',
      'heart': 'health'
    };
    const cssAppId = mappings[appId] || appId;
    return `var(--color-app-${cssAppId})`;
  }

  /**
   * Strip HTML tags from text to display as plain text.
   * Converts HTML like "<strong><mark>Open</mark>Mates</strong>" to "OpenMates"
   */
  function stripHtmlTags(html: string): string {
    if (!html) return '';
    const tmp = document.createElement('div');
    tmp.innerHTML = html;
    return tmp.textContent || tmp.innerText || '';
  }

  /**
   * Mulberry32 seeded PRNG — returns a function that produces deterministic
   * floats in [0, 1) for the given seed. Used in media mode (?media=1&seed=N)
   * so suggestion card order is reproducible across captures.
   */
  function mulberry32(seed: number): () => number {
    let s = seed | 0;
    return () => {
      s = (s + 0x6d2b79f5) | 0;
      let t = Math.imul(s ^ (s >>> 15), 1 | s);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  /** Read the ?seed=N media mode param (returns null if not in media mode) */
  const mediaSeed = typeof window !== 'undefined'
    ? (() => {
        const p = new URLSearchParams(window.location.search);
        if (p.get('media') !== '1') return null;
        const s = p.get('seed');
        return s !== null ? parseInt(s, 10) : null;
      })()
    : null;

  /**
   * Shuffle an array using Fisher-Yates algorithm.
   * When a media seed is set, uses a deterministic PRNG so the same seed
   * always produces the same card order.
   * @returns A new shuffled array (original is not modified)
   */
  function shuffleArray<T>(array: T[]): T[] {
    const rng = mediaSeed !== null ? mulberry32(mediaSeed) : Math.random;
    const shuffled = [...array];
    for (let i = shuffled.length - 1; i > 0; i--) {
      const j = Math.floor(rng() * (i + 1));
      [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
    }
    return shuffled;
  }

  // Force reactivity to language changes
  let currentLocale = $state($locale);

  // Debounced filter query — updated 400ms after user pauses typing.
  // Self-contained here so no extra overhead is added to MessageInput or ActiveChat.
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

  // --- Existing chat search ---
  // Processed chat search results to display as cards
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

  /**
   * Format a timestamp into a short relative/absolute date label.
   * e.g., "Today", "Yesterday", "Mar 15", "Dec 2025"
   */
  function formatChatDate(timestamp: number): string {
    // Timestamps are stored as Unix seconds (Math.floor(Date.now() / 1000))
    // but Date constructor expects milliseconds
    const date = new Date(timestamp * 1000);
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
   * Uses the existing searchService for full-text search across titles + messages.
   */
  $effect(() => {
    const query = filterQuery;
    if (!query || !$authStore.isAuthenticated) {
      chatSearchResults = [];
      return;
    }

    const gen = ++searchGeneration;
    const textFn = get(text);

    (async () => {
      try {
        await chatDB.init();
        const allChats = await chatDB.getAllChats();
        const results = await performSearch(query, allChats, textFn);
        // Stale guard — a newer search was triggered while this one ran
        if (gen !== searchGeneration) return;

        // Filter out demo/legal chats, limit to MAX_CHAT_RESULTS
        const userChatResults = results.chats.filter(
          r => !isDemoChat(r.chat.chat_id) && !isLegalChat(r.chat.chat_id)
        );

        // Resolve metadata (icon, category) for each result
        const processed = await Promise.all(
          userChatResults.slice(0, MAX_CHAT_RESULTS).map(async (result) => {
            const metadata = await chatMetadataCache.getDecryptedMetadata(result.chat);
            const category = metadata?.category || 'general_knowledge';
            const icon = metadata?.icon || getFallbackIconForCategory(category);
            const validIcon = getValidIconName(icon, category);
            const gradient = getCategoryGradientColors(category) || { start: '#DE1E66', end: '#FF763B' };
            const timestamp = result.chat.last_edited_overall_timestamp || result.chat.created_at || 0;

            return {
              chatId: result.chat.chat_id,
              title: result.decryptedTitle || metadata?.title || 'Untitled',
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
        console.error('[NewChatSuggestions] Chat search error:', error);
        if (gen === searchGeneration) chatSearchResults = [];
      }
    })();
  });

  // Context menu state
  let contextMenu = $state({
    show: false,
    x: 0,
    y: 0,
    suggestionText: '',
    suggestionId: ''
  });

  // Touch handling for context menu and scroll-vs-tap discrimination
  let touchStartTime = $state(0);
  let touchStartX = $state(0);  // X position at touchstart — used to detect horizontal scroll
  let touchStartY = $state(0);  // Y position at touchstart — used to detect vertical scroll
  let touchTimer: number | undefined;

  /** Max pixels a finger can move before we treat the gesture as a scroll, not a tap */
  const TOUCH_SCROLL_THRESHOLD = 8;

  // Full suggestions pool with text, encrypted value, and ID
  let fullSuggestionsWithEncrypted = $state<Array<{ text: string; encrypted: string; id: string }>>([]);
  let loading = $state(true);
  // Whether we're showing default (placeholder) suggestions before user's real ones arrive
  let showingDefaults = $state(true);
  // Fade transition state: 'visible' | 'fading-out' | 'fading-in'
  let fadeState = $state<'visible' | 'fading-out' | 'fading-in'>('visible');
  // Set of suggestion texts that have been clicked (hidden from view, pending deletion on send)
  let hiddenSuggestionTexts = $state(new Set<string>());
  let previousAuthState = $authStore.isAuthenticated;

  /**
   * Build the default suggestions array from translation keys.
   * Used for non-auth users, as initial placeholder while sync loads, and as fallback.
   */
  function buildDefaultSuggestions(): Array<{ text: string; encrypted: string; id: string }> {
    const t = get(text);
    const translatedSuggestions = DEFAULT_NEW_CHAT_SUGGESTION_KEYS.map(key => t(key));
    const plainTextSuggestions = translatedSuggestions.map(s => stripHtmlTags(s));
    return shuffleArray(plainTextSuggestions.map(text => ({
      text,
      encrypted: '',
      id: ''
    })));
  }

  /**
   * Apply default suggestions to component state (used for immediate display).
   */
  function applyDefaultSuggestions() {
    const defaults = buildDefaultSuggestions();
    fullSuggestionsWithEncrypted = defaults;
    showingDefaults = true;
  }

  /**
   * Transition from current suggestions to new ones with a fade-out / fade-in animation.
   * Used when user's real suggestions arrive to replace the default placeholder suggestions.
   */
  function transitionToSuggestions(newSuggestions: Array<{ text: string; encrypted: string; id: string }>) {
    if (showingDefaults && newSuggestions.length > 0) {
      fadeState = 'fading-out';
      setTimeout(() => {
        fullSuggestionsWithEncrypted = newSuggestions;
        showingDefaults = false;
        fadeState = 'fading-in';
        setTimeout(() => {
          fadeState = 'visible';
        }, 200);
      }, 200);
    } else {
      fullSuggestionsWithEncrypted = newSuggestions;
      showingDefaults = newSuggestions.length === 0 || newSuggestions.every(s => s.id === '');
    }
  }

  /**
   * Load suggestions from IndexedDB (auth) or defaults (non-auth).
   * For authenticated users, shows default suggestions immediately and transitions
   * to real suggestions once they're loaded from IndexedDB.
   */
  const loadSuggestions = async () => {
    if (!$authStore.isAuthenticated) {
      applyDefaultSuggestions();
      loading = false;
      return;
    }

    // For authenticated users, keep loading=true (component hidden) until
    // IndexedDB results arrive. This prevents a flash where default suggestions
    // briefly appear before being replaced by user-specific ones.
    try {
      await chatDB.init();
      await new Promise(resolve => setTimeout(resolve, 100));

      const all: NewChatSuggestion[] = await chatDB.getAllNewChatSuggestions();
      const decryptedSuggestions = await Promise.all(
        all.map(async s => {
          const decrypted = await decryptWithMasterKey(s.encrypted_suggestion);
          if (!decrypted) return null;
          const plainText = stripHtmlTags(decrypted);
          return {
            text: plainText,
            encrypted: s.encrypted_suggestion,
            id: s.id
          };
        })
      );
      let realSuggestions = decryptedSuggestions.filter(
        (s): s is { text: string; encrypted: string; id: string } => s !== null
      );

      // Shuffle for random order
      realSuggestions = shuffleArray(realSuggestions);

      if (realSuggestions.length > 0) {
        fullSuggestionsWithEncrypted = realSuggestions;
        showingDefaults = false;
      } else {
        // No user-specific suggestions — fall back to defaults
        applyDefaultSuggestions();
      }
      loading = false;
    } catch (error) {
      if ($authStore.isAuthenticated) {
        console.error('[NewChatSuggestions] Error loading suggestions:', error);
      }
      // On error, fall back to defaults so the UI isn't permanently empty
      applyDefaultSuggestions();
      loading = false;
    }
  };

  // React to auth state changes — reload suggestions when auth state transitions
  $effect(() => {
    const isAuthenticated = $authStore.isAuthenticated;
    if (previousAuthState !== isAuthenticated) {
      previousAuthState = isAuthenticated;
      hiddenSuggestionTexts = new Set();
      loadSuggestions();
    }
  });

  onMount(() => {
    loadSuggestions();

    const handleFullSyncReady = () => {
      loadSuggestions();
    };
    chatSyncService.addEventListener('fullSyncReady', handleFullSyncReady);

    const handleLanguageChange = () => {
      currentLocale = $locale;
      if (!$authStore.isAuthenticated) {
        loadSuggestions();
      }
    };
    window.addEventListener('language-changed', handleLanguageChange);

    return () => {
      chatSyncService.removeEventListener('fullSyncReady', handleFullSyncReady);
      window.removeEventListener('language-changed', handleLanguageChange);
    };
  });

  /**
   * Visible suggestion cards: deduplicated, parsed, limited to VISIBLE_COUNT,
   * with clicked suggestions hidden from view.
   */
  let visibleSuggestions = $derived.by(() => {
    if (loading) return [];

    const seen = new Set<string>();
    const parsed = fullSuggestionsWithEncrypted
      .filter(s => {
        // Skip duplicates
        if (seen.has(s.text)) return false;
        seen.add(s.text);
        // Skip clicked/hidden suggestions
        if (hiddenSuggestionTexts.has(s.text)) return false;
        return true;
      })
      .map(s => {
        const meta = parseSuggestion(s.text);
        const iconName = resolveIconName(meta.appId, meta.subId);
        return {
          text: s.text,
          body: meta.body,
          appId: meta.appId,
          subId: meta.subId,
          iconName,
          encrypted: s.encrypted,
          id: s.id
        };
      })
      // Filter out suggestions with too few words in the body text
      .filter(s => s.body.split(/\s+/).filter(Boolean).length >= MIN_BODY_WORDS);

    // Apply search filter when query is active
    const filtered = filterQuery
      ? parsed.filter(s =>
          s.body.toLowerCase().includes(filterQuery) ||
          s.appId.toLowerCase().includes(filterQuery)
        )
      : parsed;

    // Graceful fallback: if filter matches nothing AND no chat results found, show all (not empty).
    // When chat results exist, an empty suggestion filter is fine — the chat cards fill the gap.
    const pool = (filterQuery && filtered.length === 0 && chatSearchResults.length === 0) ? parsed : filtered;

    return pool.slice(0, VISIBLE_COUNT);
  });

  // True when filter produced 0 matches across both suggestions AND chat results
  let noMatchFallback = $derived(
    filterQuery !== '' &&
    !loading &&
    chatSearchResults.length === 0 &&
    fullSuggestionsWithEncrypted
      .filter(s => !hiddenSuggestionTexts.has(s.text))
      .every(s => {
        const body = parseSuggestion(s.text).body.toLowerCase();
        const appId = parseSuggestion(s.text).appId.toLowerCase();
        return !body.includes(filterQuery) && !appId.includes(filterQuery);
      })
  );

  /**
   * Handle suggestion click — hide the card from view, track for deletion on send,
   * and pass body text (without prefix) to parent for insertion into message input.
   * No @mention syntax is inserted — the LLM auto-selects the appropriate skill.
   */
  function handleSuggestionClick(
    rawText: string,
    body: string,
    suggestionId?: string,
    encryptedSuggestion?: string
  ) {
    // Hide this suggestion card from view immediately
    hiddenSuggestionTexts = new Set([...hiddenSuggestionTexts, rawText]);

    // For authenticated users, track the suggestion for deletion after sending
    if ($authStore.isAuthenticated) {
      let encrypted = encryptedSuggestion;
      if (!encrypted) {
        const data = fullSuggestionsWithEncrypted.find(s => s.text === rawText);
        encrypted = data?.encrypted;
      }

      if (encrypted && encrypted.trim() !== '') {
        setClickedSuggestion(body, encrypted);
      }
    }

    // Pass body text only to parent (no mentionSyntax)
    onSuggestionClick(body);
  }

  /**
   * Handle context menu (right-click or long touch)
   */
  function handleContextMenu(event: MouseEvent | TouchEvent, suggestionText: string, suggestionId?: string) {
    if (!$authStore.isAuthenticated) return;

    event.preventDefault();
    event.stopPropagation();

    let id = suggestionId;
    if (!id) {
      const data = fullSuggestionsWithEncrypted.find(s => s.text === suggestionText);
      id = data?.id;
    }

    if (!id || id.trim() === '') return;

    let x = 0;
    let y = 0;
    if (event instanceof MouseEvent) {
      x = event.clientX;
      y = event.clientY;
    } else if (event instanceof TouchEvent && event.touches.length > 0) {
      x = event.touches[0].clientX;
      y = event.touches[0].clientY;
    }

    contextMenu = { show: true, x, y, suggestionText, suggestionId: id };
  }

  /**
   * Handle touch start — record position and start long-press timer.
   */
  function handleTouchStart(event: TouchEvent, suggestionText: string, suggestionId?: string) {
    touchStartTime = Date.now();
    if (event.touches.length > 0) {
      touchStartX = event.touches[0].clientX;
      touchStartY = event.touches[0].clientY;
    }
    if (touchTimer) clearTimeout(touchTimer);
    touchTimer = window.setTimeout(() => {
      handleContextMenu(event, suggestionText, suggestionId);
    }, 500);
  }

  /**
   * Handle touch end — fire click only if the finger didn't scroll.
   * Checks both duration (< 500ms) and horizontal movement (< TOUCH_SCROLL_THRESHOLD px)
   * to distinguish a tap from a scroll gesture. This prevents false-click pastes
   * when the user is swiping through the suggestion card row on a touch device.
   */
  function handleTouchEnd(
    event: TouchEvent,
    rawText: string,
    body: string,
    suggestionId?: string,
    encryptedSuggestion?: string
  ) {
    const touchDuration = Date.now() - touchStartTime;
    if (touchTimer) {
      clearTimeout(touchTimer);
      touchTimer = undefined;
    }

    // Measure how far the finger moved from the start position
    let deltaX = 0;
    let deltaY = 0;
    if (event.changedTouches.length > 0) {
      deltaX = Math.abs(event.changedTouches[0].clientX - touchStartX);
      deltaY = Math.abs(event.changedTouches[0].clientY - touchStartY);
    }

    // Only fire the click if: short tap AND finger barely moved (not a scroll)
    const isScroll = deltaX > TOUCH_SCROLL_THRESHOLD || deltaY > TOUCH_SCROLL_THRESHOLD;
    if (touchDuration < 500 && !isScroll) {
      handleSuggestionClick(rawText, body, suggestionId, encryptedSuggestion);
    }

    // Don't preventDefault — we want native scroll to still work
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

  function handleContextMenuClose() {
    contextMenu = { show: false, x: 0, y: 0, suggestionText: '', suggestionId: '' };
  }

  /**
   * Handle context menu delete action
   */
  async function handleContextMenuDelete() {
    if (!contextMenu.suggestionId || contextMenu.suggestionId.trim() === '') {
      handleContextMenuClose();
      return;
    }

    const trimmedId = contextMenu.suggestionId.trim();

    try {
      const deleteResult = await chatDB.deleteNewChatSuggestionById(trimmedId);
      if (deleteResult) {
        try {
          await chatSyncService.sendDeleteNewChatSuggestionById(trimmedId);
        } catch (serverError) {
          console.warn('[NewChatSuggestions] Failed to delete suggestion from server:', serverError);
        }
        loading = true;
        loadSuggestions();
      } else {
        console.error('[NewChatSuggestions] Failed to delete suggestion from IndexedDB');
      }
    } catch (error) {
      console.error('[NewChatSuggestions] Error deleting suggestion:', error);
    }

    handleContextMenuClose();
  }
</script>

{#if !loading && (visibleSuggestions.length > 0 || chatSearchResults.length > 0)}
  <div class="suggestions-wrapper" data-testid="suggestions-wrapper" class:fade-out={fadeState === 'fading-out'} class:fade-in={fadeState === 'fading-in'}>
    <div class="suggestions-header">
      {#key currentLocale}
        {#if noMatchFallback}
          <span class="filter-no-match">{$text('chat.suggestions.filter_no_match')}</span>
        {:else}
          {$text('chat.suggestions.header_click')}
        {/if}
      {/key}
    </div>
    <div class="suggestions-scroll">
      {#each visibleSuggestions as suggestion (suggestion.text)}
        <button
          class="suggestion-card"
          style="background: {getAppCssGradient(suggestion.appId)};"
          onclick={() => handleSuggestionClick(suggestion.text, suggestion.body, suggestion.id, suggestion.encrypted)}
          oncontextmenu={(event) => handleContextMenu(event, suggestion.text, suggestion.id)}
          ontouchstart={(event) => handleTouchStart(event, suggestion.text, suggestion.id)}
          ontouchend={(event) => handleTouchEnd(event, suggestion.text, suggestion.body, suggestion.id, suggestion.encrypted)}
          ontouchmove={handleTouchMove}
        >
          <span class="card-icon">
            <Icon name={suggestion.iconName} type="skill" size="24px" noAnimation noMargin />
          </span>
          <span class="card-text">{suggestion.body}</span>
        </button>
      {/each}

      <!-- Existing chat search results (shown when user types a search query) -->
      {#if chatSearchResults.length > 0}
        {#if visibleSuggestions.length > 0}
          <div class="chat-results-divider"></div>
        {/if}
        {#each chatSearchResults as chatResult (chatResult.chatId)}
          {@const IconComponent = getLucideIcon(chatResult.iconName)}
          <div class="chat-result-wrapper">
            <button
              class="suggestion-card chat-result-card"
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
  suggestionId={contextMenu.suggestionId}
  on:close={handleContextMenuClose}
  on:delete={handleContextMenuDelete}
/>

<style>
  .suggestions-wrapper {
    animation: fadeIn 200ms ease-out;
    animation-delay: 200ms;
    animation-fill-mode: backwards;
    transition: opacity 200ms ease;
    opacity: 1;
    /* Must span full parent width so children's calc(50% - 120px) padding resolves
       against the actual container width, not a content-shrunk width.
       Without this, align-items:center on the parent shrinks us and breaks centering. */
    width: 100%;
    /* overflow-x must NOT be set here — it would clip the scroll container's cards */

    /* Fade edges to transparent so the gap between scroll content and
       the parent container's padding is not visible as a hard cut-off. */
    -webkit-mask-image: linear-gradient(to right, transparent, black 28px, black calc(100% - 28px), transparent);
    mask-image: linear-gradient(to right, transparent, black 28px, black calc(100% - 28px), transparent);
  }

  .suggestions-wrapper.fade-out {
    opacity: 0;
    transition: opacity 200ms ease-out;
  }

  .suggestions-wrapper.fade-in {
    opacity: 0;
    animation: fadeIn 200ms ease-in forwards;
  }

  .suggestions-header {
    color: var(--color-grey-60);
    font-size: var(--font-size-p);
    /* Align header left edge with the first card (mirroring recent-chats centering).
       Cards are 300px wide → left edge at 50% - 150px centres the first card. */
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

  /* Horizontally scrollable row of suggestion cards.
     First card is centred in the chat area via padding-left: calc(50% - 150px)
     (cards are 300px wide, so half-card = 150px). This mirrors the recent-chats
     scroll container which uses calc(50% - 150px) for its 300px cards.
     Right padding (48px) keeps a partial next-card visible as a scroll affordance.
     overflow-x: auto enables horizontal scrolling; overflow-y must also be
     set (not left as 'visible') since mixing overflow-x:auto with overflow-y:visible
     forces both to auto per CSS spec, which can clip shadows. */
  .suggestions-scroll {
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: var(--spacing-6);
    overflow-x: auto;
    overflow-y: hidden;
    -webkit-overflow-scrolling: touch;
    scroll-behavior: smooth;
    scrollbar-width: none; /* Firefox */
    -ms-overflow-style: none; /* IE/Edge */
    /* Extra bottom padding so card drop-shadows aren't clipped */
    padding: 4px 48px 14px calc(50% - 150px);
    /* Negative bottom margin to reclaim the extra padding without affecting layout */
    margin-bottom: -4px;
    /* Must match recent-chats-scroll-container: explicit width + border-box so
       padding-left calc(50% - 120px) resolves against the full container width. */
    box-sizing: border-box;
    width: 100%;
    max-width: 100%;
  }

  .suggestions-scroll::-webkit-scrollbar {
    display: none; /* Chrome/Safari */
  }

  /* Each suggestion card: rounded rectangle with app gradient background,
     icon on the left, white text on the right.
     Fixed width of 300px (matching recent-chats cards) — wide enough for
     longer suggestion text, narrow enough that a second card is partially
     visible as a scroll affordance. Mobile uses 210px (see media query).
     Cards are always full-height (align-items: stretch on parent). */
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

  /* Icon container — white icon on gradient background.
     Uses CSS filter to make skill icons white regardless of their original color. */
  .card-icon {
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    width: 27px;
    height: 27px;
  }

  /* Force all icon pseudo-elements to render white on the gradient card */
  .card-icon :global(.icon) {
    animation: none !important;
    opacity: 1 !important;
    border: none !important;
    background: none !important;
    /* Override skill icon background/border styling so it's just a white icon */
  }

  .card-icon :global(.icon::before) {
    filter: brightness(0) invert(1) !important;
  }

  /* White bold text — matches Figma: Lexend Deca Bold 14px, line-height ~18px.
     Clamped to 2 lines with ellipsis so cards keep a consistent height. */
  .card-text {
    color: var(--color-grey-0);
    font-size: var(--font-size-small);
    font-weight: 700;
    line-height: 1.3;
    text-align: left;
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    overflow: hidden;
    /* Allow flex child to shrink below content width so line-clamp works */
    min-width: 0;
  }

  .filter-no-match {
    color: var(--color-grey-50);
    font-style: italic;
    font-size: var(--font-size-small);
    opacity: 0.75;
  }

  /* --- Existing chat search result cards --- */

  /* Thin vertical divider separating suggestion cards from chat result cards */
  .chat-results-divider {
    width: 1px;
    min-width: 1px;
    height: 40px;
    background: var(--color-grey-30);
    opacity: 0.4;
    flex-shrink: 0;
    border-radius: 1px;
    align-self: center;
  }

  /* Ensure lucide icon component is centered in the card icon container */
  .chat-result-icon {
    display: flex;
    align-items: center;
    justify-content: center;
  }

  /* Wrapper for chat result card + date label below it */
  .chat-result-wrapper {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--spacing-2);
    flex-shrink: 0;
  }

  /* Small date label below the chat result card */
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
    .suggestions-wrapper {
      /* Tighter fade on mobile to preserve more visible card area */
      -webkit-mask-image: linear-gradient(to right, transparent, black 16px, black calc(100% - 16px), transparent);
      mask-image: linear-gradient(to right, transparent, black 16px, black calc(100% - 16px), transparent);
    }

    .suggestions-header {
      /* Cards are 210px on mobile → left edge at 50% - 105px */
      padding: 0 0 0 calc(50% - 105px);
      font-size: var(--font-size-small);
    }

    .suggestions-scroll {
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
