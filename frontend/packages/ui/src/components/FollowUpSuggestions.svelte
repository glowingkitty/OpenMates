<!--
  FollowUpSuggestions.svelte

  Gradient banner card displayed below the last assistant message in ChatHistory.
  Shows follow-up suggestion prompts that users can click to copy into their message input.

  Visual design mirrors ChatHeader.svelte:
  - Category gradient background with animated living gradient orbs
  - Large decorative Lucide icons at left/right edges (same category icon as ChatHeader)
  - Chevron navigation arrows to page through groups of 3 suggestions
  - White text on gradient background for suggestion items

  Each suggestion row shows an icon to the left:
  - Skill icon (if the suggestion includes a valid [app-skill] prefix with a skill icon)
  - App icon (if the suggestion includes a valid app prefix but the skill has no icon)
  - Fallback arrow icon (back.svg flipped to point right) when no app/skill is present

  Architecture: relies on shared animations from animations.css (orbMorph, orbDrift,
  decoEnter, decoFloat keyframes) — same as ChatHeader and DailyInspirationBanner.
  See docs/architecture/banner-animations.md for the shared keyframe strategy.
-->
<script lang="ts">
  import { fade } from 'svelte/transition';
  import { onMount } from 'svelte';
  import { locale } from 'svelte-i18n';
  import Icon from './Icon.svelte';
  import { appSkillsStore } from '../stores/appSkillsStore';
  import { getCategoryGradientColors, getValidIconName, getLucideIcon } from '../utils/categoryUtils';

  let {
    suggestions = [],
    messageInputContent = '',
    onSuggestionClick,
    category = null,
    icon = null,
  }: {
    suggestions: string[];
    messageInputContent?: string;
    onSuggestionClick: (suggestion: string, mentionSyntax?: string) => void;
    /** Chat category string (e.g. "technology") for the gradient background and decorative icons. */
    category?: string | null;
    /** Chat icon name (e.g. "cpu") for the decorative side icons. */
    icon?: string | null;
  } = $props();

  // Import text function for translations
  import { text } from '@repo/ui';
  
  // Force reactivity to language changes
  let currentLocale = $state($locale);

  // Apps metadata for icon resolution
  let appsMetadata = $state(appSkillsStore.getState());

  // ─── Pagination ────────────────────────────────────────────────────────────
  // Groups of 3 suggestions, navigated with prev/next arrows.

  let currentPage = $state(0);
  let isPageFading = $state(false);
  const PAGE_FADE_DURATION_MS = 120;
  let pageSwapTimeout: ReturnType<typeof setTimeout> | null = null;

  /** Lucide chevron icons for prev/next arrows. */
  const ChevronLeft = getLucideIcon('chevron-left');
  const ChevronRight = getLucideIcon('chevron-right');

  /**
   * Parsed suggestion: splits "[app_id-skill_id] body text" into parts.
   * Returns null prefix/appId/subId if no valid prefix is present.
   */
  interface ParsedSuggestion {
    raw: string;
    prefix: string | null;  // e.g. "web-search"
    appId: string | null;   // e.g. "web"
    subId: string | null;   // e.g. "search"
    body: string;           // The body text to insert on click
  }

  /**
   * Parse a raw suggestion string of the form "[app_id-skill_id] body text".
   * The prefix bracket content uses a dash separator between app and skill
   * (e.g. "web-search", "jobs-career_insights"). LLMs sometimes generate dashes
   * in the skill name portion (e.g. "reminder-set-reminder") instead of underscores
   * ("reminder-set_reminder") — we correct for this by replacing dashes in the
   * subId portion with underscores, then validate against the known app skills store.
   * If no valid app+skill pair is found, we still keep the appId if the app exists
   * (for app-level icon fallback). If the app doesn't exist, appId/subId are null.
   */
  function parseSuggestion(raw: string): ParsedSuggestion {
    // Allow dashes anywhere in the prefix (LLMs may use dashes instead of underscores in skill names)
    const match = raw.match(/^\[([a-z0-9_-]+)\]\s*(.+)$/i);
    if (!match) {
      return { raw, prefix: null, appId: null, subId: null, body: raw };
    }
    const prefix = match[1];
    const body = match[2].trim();
    const dashIdx = prefix.indexOf('-');
    if (dashIdx === -1) {
      // No dash: could be an app-only prefix like "[web]"
      const appOnly = prefix;
      const app = appsMetadata?.apps?.[appOnly];
      if (app) {
        return { raw, prefix: appOnly, appId: appOnly, subId: null, body };
      }
      return { raw, prefix: null, appId: null, subId: null, body: raw };
    }
    const appId = prefix.substring(0, dashIdx);
    // Replace any remaining dashes in the subId with underscores to correct LLM errors
    // (e.g. "set-reminder" -> "set_reminder")
    const subIdRaw = prefix.substring(dashIdx + 1);
    const subId = subIdRaw.replace(/-/g, '_');

    // Validate that appId and subId correspond to a real skill or focus mode
    const app = appsMetadata?.apps?.[appId];
    const isValidSkill = app?.skills?.some(s => s.id === subId) ?? false;
    const isValidFocus = app?.focus_modes?.some(f => f.id === subId) ?? false;
    if (!isValidSkill && !isValidFocus) {
      // Unknown skill — but if the app itself exists, keep appId for app-level icon
      if (app) {
        return { raw, prefix, appId, subId: null, body };
      }
      return { raw, prefix: null, appId: null, subId: null, body };
    }

    return { raw, prefix, appId, subId, body };
  }

  /**
   * Resolve the icon for a suggestion.
   * Priority: skill/focus mode icon → app-level icon → fallback (back.svg).
   * Returns { type, name } where type indicates how to render the icon.
   */
  function resolveSuggestionIcon(appId: string | null, subId: string | null): { type: 'skill' | 'app' | 'fallback'; name: string } {
    if (!appId) {
      return { type: 'fallback', name: 'back' };
    }

    const app = appsMetadata?.apps?.[appId];
    if (!app) {
      return { type: 'fallback', name: 'back' };
    }

    // Try skill icon first
    if (subId) {
      const skill = app.skills?.find(s => s.id === subId);
      if (skill?.icon_image) {
        return { type: 'skill', name: skill.icon_image.replace(/\.svg$/i, '') };
      }

      // Try focus mode icon
      const focus = app.focus_modes?.find(f => f.id === subId);
      if (focus?.icon_image) {
        return { type: 'skill', name: focus.icon_image.replace(/\.svg$/i, '') };
      }
    }

    // Fallback to app-level icon
    if (app.icon_image) {
      return { type: 'app', name: app.icon_image.replace(/\.svg$/i, '') };
    }

    return { type: 'fallback', name: 'back' };
  }

  /**
   * Strip HTML tags from text to display as plain text.
   * Converts HTML like "<strong><mark>Open</mark>Mates</strong>" to "OpenMates".
   * Uses DOM in the browser; falls back to a simple regex during SSR prerender
   * where `document` is not available.
   */
  function stripHtmlTags(html: string): string {
    if (!html) return '';
    if (typeof document !== 'undefined') {
      // Browser: use DOM for accurate HTML parsing
      const tmp = document.createElement('div');
      tmp.innerHTML = html;
      return tmp.textContent || tmp.innerText || '';
    }
    // SSR fallback: strip tags with a simple regex
    return html.replace(/<[^>]+>/g, '');
  }

  // Detect if device is touch-capable.
  // `window`/`navigator` are not available during SSR prerender — start as false
  // and update in onMount once running in the browser.
  let touchDevice = $state(false);

  // Full suggestions pool - computed from prop to avoid duplicates.
  // Strip HTML tags and parse prefix.
  let fullSuggestions = $derived(
    Array.from(new Set(suggestions))
      .map(s => parseSuggestion(stripHtmlTags(s)))
  );

  // Reset page when suggestions change (e.g. new chat)
  $effect(() => {
    // Re-read fullSuggestions to track changes
    // eslint-disable-next-line @typescript-eslint/no-unused-expressions
    fullSuggestions;
    currentPage = 0;
  });

  /** Total number of pages (groups of 3). */
  let totalPages = $derived(Math.ceil(fullSuggestions.length / 3));

  // Filtered and displayed suggestions based on input content and pagination.
  let filteredSuggestions = $derived.by(() => {
    // When input is empty, show paginated groups of 3
    if (!messageInputContent || messageInputContent.trim() === '') {
      const start = currentPage * 3;
      const displayedSuggestions = fullSuggestions.slice(start, start + 3);
      return displayedSuggestions.map(parsed => ({ ...parsed, matchIndex: -1, matchLength: 0 }));
    }

    // When user is typing, filter across the FULL pool (searching over body text)
    const searchTerm = messageInputContent.trim();
    const searchTermLower = searchTerm.toLowerCase();

    // Search over body text (not the prefix) so prefix doesn't interfere with filtering
    const allFiltered = fullSuggestions
      .map(parsed => {
        const lowerBody = parsed.body.toLowerCase();
        const matchIndex = lowerBody.indexOf(searchTermLower);
        return {
          ...parsed,
          matchIndex,
          matchLength: searchTerm.length
        };
      })
      .filter(item => item.matchIndex !== -1)
      // Exclude exact matches
      .filter(item => item.body.toLowerCase() !== searchTermLower);

    // Apply pagination to filtered results too
    const start = currentPage * 3;
    return allFiltered.slice(start, start + 3);
  });

  function renderHighlightedText(suggestion: ParsedSuggestion & { matchIndex: number; matchLength: number }) {
    if (suggestion.matchIndex === -1 || !messageInputContent || !messageInputContent.trim()) {
      return suggestion.body;
    }

    const before = suggestion.body.substring(0, suggestion.matchIndex);
    const match = suggestion.body.substring(suggestion.matchIndex, suggestion.matchIndex + suggestion.matchLength);
    const after = suggestion.body.substring(suggestion.matchIndex + suggestion.matchLength);

    return { before, match, after };
  }

  /**
   * Handle suggestion click - inserts body text and optionally triggers a skill mention.
   * When a suggestion has a prefix (e.g. [web-search]), we build the @skill mention syntax
   * so the parent can insert a proper mention node via pendingMentionStore, ensuring the
   * app skill is triggered on send.
   */
  function handleSuggestionClick(appId: string | null, subId: string | null, body: string) {
    // Build mention syntax for skill-prefixed suggestions (e.g. "@skill:web:search")
    const mentionSyntax = appId && subId ? `@skill:${appId}:${subId}` : undefined;
    onSuggestionClick(body, mentionSyntax);
  }

  /** Fade out, swap the suggestion page, then fade back in. */
  function transitionToPage(targetPage: number) {
    if (targetPage === currentPage || targetPage < 0 || targetPage >= totalPages) {
      return;
    }
    if (pageSwapTimeout) {
      clearTimeout(pageSwapTimeout);
      pageSwapTimeout = null;
    }
    isPageFading = true;
    pageSwapTimeout = setTimeout(() => {
      currentPage = targetPage;
      isPageFading = false;
      pageSwapTimeout = null;
    }, PAGE_FADE_DURATION_MS);
  }

  /** Navigate to the previous page of suggestions. */
  function handlePrevPage(e: MouseEvent) {
    e.stopPropagation();
    e.preventDefault();
    transitionToPage(currentPage - 1);
  }

  /** Navigate to the next page of suggestions. */
  function handleNextPage(e: MouseEvent) {
    e.stopPropagation();
    e.preventDefault();
    transitionToPage(currentPage + 1);
  }

  // ─── Gradient & decorative icon state ──────────────────────────────────────

  /** Gradient background style for the card. Uses the chat's category gradient,
   *  falling back to var(--color-primary) when no category exists.
   *  Also emits --orb-color-a and --orb-color-b for the living gradient orbs. */
  let cardStyle = $derived.by(() => {
    if (!category) {
      return [
        'background: var(--color-primary)',
        '--orb-color-a: #4867cd',
        '--orb-color-b: #a0beff',
      ].join(';');
    }
    const colors = getCategoryGradientColors(category);
    if (!colors) {
      return [
        'background: var(--color-primary)',
        '--orb-color-a: #4867cd',
        '--orb-color-b: #a0beff',
      ].join(';');
    }
    return [
      `background: linear-gradient(135deg, ${colors.start}, ${colors.end})`,
      `--orb-color-a: ${colors.start}`,
      `--orb-color-b: ${colors.end}`,
    ].join(';');
  });

  /** Lucide icon component for the category, resolved from icon name + fallback. */
  let DecoIconComponent = $derived.by(() => {
    if (!category) return null;
    const iconName = getValidIconName(icon || '', category);
    return getLucideIcon(iconName);
  });

  // Update currentLocale when language changes to force component re-render.
  // Also resolve touch capability here — `window`/`navigator` are only safe in the browser.
  onMount(() => {
    // Resolve touch capability now that we are in the browser
    touchDevice =
      'ontouchstart' in window ||
      navigator.maxTouchPoints > 0 ||
      (navigator as Navigator & { msMaxTouchPoints?: number }).msMaxTouchPoints > 0;

    const handleLanguageChange = () => {
      currentLocale = $locale;
    };
    
    window.addEventListener('language-changed', handleLanguageChange);
    
    return () => {
      window.removeEventListener('language-changed', handleLanguageChange);
      if (pageSwapTimeout) {
        clearTimeout(pageSwapTimeout);
        pageSwapTimeout = null;
      }
    };
  });
</script>

{#if filteredSuggestions.length > 0}
  <div class="suggestions-wrapper" transition:fade={{ duration: 200 }}>
    <!-- Header text above the gradient card -->
    <div class="suggestions-header">
      {#key currentLocale}
        <span class="header-title">{$text('chat.suggestions.explore_next')}</span>
        <span class="header-subtitle">
          {touchDevice ? $text('chat.suggestions.header_tap') : $text('chat.suggestions.header_click')}
        </span>
      {/key}
    </div>

    <!-- Navigation arrows (absolute-positioned relative to .suggestions-wrapper) -->
    {#if totalPages > 1 && currentPage > 0}
      <button
        class="nav-arrow nav-arrow-left"
        onclick={handlePrevPage}
        onmousedown={(e) => e.preventDefault()}
        aria-label="Previous suggestions"
        type="button"
      >
        <ChevronLeft size={22} color="rgba(255,255,255,0.85)" />
      </button>
    {/if}
    {#if totalPages > 1 && currentPage < totalPages - 1}
      <button
        class="nav-arrow nav-arrow-right"
        onclick={handleNextPage}
        onmousedown={(e) => e.preventDefault()}
        aria-label="Next suggestions"
        type="button"
      >
        <ChevronRight size={22} color="rgba(255,255,255,0.85)" />
      </button>
    {/if}

    <!-- Gradient card with animated orbs and suggestions -->
    <div class="suggestions-card" style={cardStyle}>
      <!-- Living gradient orbs (same as ChatHeader) -->
      <div class="card-orbs" aria-hidden="true">
        <div class="orb orb-1"></div>
        <div class="orb orb-2"></div>
        <div class="orb orb-3"></div>
      </div>

      <!-- Decorative category icons at left/right edges -->
      {#if DecoIconComponent}
        <div class="deco-icon deco-icon-left">
          <DecoIconComponent size={90} color="white" />
        </div>
        <div class="deco-icon deco-icon-right">
          <DecoIconComponent size={90} color="white" />
        </div>
      {/if}

      <!-- Suggestion items -->
      <div class="suggestions-list" class:is-page-fading={isPageFading}>
        {#each filteredSuggestions as suggestion (suggestion.raw)}
          {@const highlighted = renderHighlightedText(suggestion)}
          {@const iconInfo = resolveSuggestionIcon(suggestion.appId, suggestion.subId)}
          <button
            class="suggestion-item"
            onmousedown={(event) => {
              event.preventDefault();
            }}
            onclick={(event) => {
              event.preventDefault();
              event.stopPropagation();
              handleSuggestionClick(suggestion.appId, suggestion.subId, suggestion.body);
            }}
          >
            <!-- Suggestion icon -->
            <span class="suggestion-icon">
              {#if iconInfo.type === 'skill'}
                <Icon name={iconInfo.name} type="skill" size="18px" noAnimation noMargin />
              {:else if iconInfo.type === 'app'}
                <Icon name={iconInfo.name} type="app" size="18px" noAnimation noMargin />
              {:else}
                <!-- Fallback: back.svg flipped to point right -->
                <span class="fallback-icon"></span>
              {/if}
            </span>

            <!-- Suggestion text -->
            <span class="suggestion-text">
              {#if typeof highlighted === 'string'}
                {highlighted}
              {:else}
                <span class="text-part">{highlighted.before}</span><span class="text-match">{highlighted.match}</span><span class="text-part">{highlighted.after}</span>
              {/if}
            </span>
          </button>
        {/each}
      </div>
    </div>
  </div>
{/if}

<style>
  /* ─── Wrapper: aligns with mate-message-content ─────────────────────────── */

  .suggestions-wrapper {
    animation: fadeIn 200ms ease-out;
    width: 100%;
    /* Establish positioning context for the absolute-positioned nav arrows */
    position: relative;
    /* Clip deco icons and nav arrows that extend beyond the wrapper bounds */
    overflow: hidden;
  }

  @keyframes fadeIn {
    from { opacity: 0; }
    to   { opacity: 1; }
  }

  /* ─── Header text above the card ────────────────────────────────────────── */

  .suggestions-header {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.125rem;
    padding: 0 1.125rem;
    margin-bottom: 0.5rem;
  }

  .header-title {
    color: var(--color-grey-70);
    font-size: 1rem;
    font-weight: 700;
    letter-spacing: 0.3px;
    text-align: center;
  }

  .header-subtitle {
    color: var(--color-grey-70);
    font-size: 0.875rem;
    font-weight: 500;
    text-align: center;
  }

  /* ─── Gradient card ─────────────────────────────────────────────────────── */

  .suggestions-card {
    position: relative;
    width: 100%;
    border-radius: 14px;
    overflow: hidden;
    padding: 1rem 1rem;
    box-sizing: border-box;
    /* Smooth background transition when category changes */
    transition: background 0.5s ease;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.18);
    user-select: none;
    /* Fixed height prevents layout glitches when paging between suggestion sets */
    height: 170px;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  /* ─── Living gradient orbs (same as ChatHeader) ─────────────────────────── */

  .card-orbs {
    position: absolute;
    inset: 0;
    z-index: 0;
    pointer-events: none;
    overflow: hidden;
  }

  .orb {
    position: absolute;
    width: 320px;
    height: 280px;
    background: radial-gradient(
      ellipse at center,
      var(--orb-color-b) 0%,
      var(--orb-color-b) 40%,
      transparent 85%
    );
    filter: blur(28px);
    opacity: 0.55;
    will-change: transform, border-radius;
  }

  .orb-1 {
    top: -60px;
    left: -80px;
    animation:
      orbMorph1 11s ease-in-out infinite,
      orbDrift1 19s ease-in-out infinite;
  }

  .orb-2 {
    bottom: -80px;
    right: -80px;
    width: 300px;
    height: 260px;
    animation:
      orbMorph2 13s ease-in-out infinite,
      orbDrift2 23s ease-in-out infinite;
  }

  .orb-3 {
    top: -10px;
    left: 25%;
    width: 240px;
    height: 200px;
    opacity: 0.38;
    animation:
      orbMorph3 17s ease-in-out infinite,
      orbDrift3 29s ease-in-out infinite;
  }

  @media (prefers-reduced-motion: reduce) {
    .orb { animation: none !important; }
  }

  /* ─── Decorative category icons at card edges ───────────────────────────── */

  .deco-icon {
    position: absolute;
    width: 90px;
    height: 90px;
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1;
    pointer-events: none;
    --float-rx: 6px;
    --float-ry: 8px;
    animation:
      decoEnter 0.6s ease-out 0.1s both,
      decoFloat 16s linear 0.7s infinite;
  }

  .deco-icon-left {
    left: -20px;
    top: 50%;
    transform: translateY(-50%);
    --deco-rotate: -15deg;
  }

  .deco-icon-right {
    right: -20px;
    top: 50%;
    transform: translateY(-50%);
    --deco-rotate: 15deg;
    animation-delay: 0.1s, -8s;
  }

  @media (prefers-reduced-motion: reduce) {
    .deco-icon {
      animation: decoEnter 0.6s ease-out 0.1s both !important;
    }
  }

  /* ─── Navigation arrows (absolute-positioned relative to .suggestions-wrapper) ─ */

  .nav-arrow {
    position: absolute;
    /* Vertically align with the gradient card (skip the header text area) */
    bottom: 0;
    height: 170px;
    padding: 0 !important;
    min-width: unset !important;
    width: 36px !important;
    border-radius: 0 !important;
    background-color: transparent !important;
    filter: none !important;
    margin: 0 !important;
    border: none;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: background-color 0.15s ease;
    z-index: 20;
    pointer-events: auto;
    flex-shrink: 0;
  }

  .nav-arrow:hover {
    background-color: rgba(255, 255, 255, 0.1) !important;
    scale: none !important;
  }

  .nav-arrow:active {
    background-color: rgba(255, 255, 255, 0.18) !important;
    scale: none !important;
    filter: none !important;
  }

  .nav-arrow-left {
    left: 0;
    border-radius: 0 10px 10px 0 !important;
  }

  .nav-arrow-right {
    right: 0;
    border-radius: 10px 0 0 10px !important;
  }

  /* ─── Suggestions list ──────────────────────────────────────────────────── */

  .suggestions-list {
    display: flex;
    flex-direction: column;
    gap: 0.375rem;
    z-index: 2;
    position: relative;
    /* Shrink to the width of the longest text item, up to 700px max */
    width: fit-content;
    max-width: 700px;
    /* Center the block horizontally within the gradient card */
    margin: 0 auto;
    opacity: 1;
    transition: opacity 120ms ease;
  }

  .suggestions-list.is-page-fading {
    opacity: 0;
  }

  .suggestion-item {
    background-color: transparent;
    border: none;
    padding: 0.375rem 0.5rem;
    font-size: 1rem;
    /* Intentionally white on gradient — branded card, not a theme surface.
       Same approach as ChatHeader.svelte loaded-title. */
    color: #ffffff;
    cursor: pointer;
    transition: background-color 0.15s ease;
    white-space: normal;
    border-radius: 8px;
    line-height: 1.35;
    text-align: left;
    height: auto;
    min-height: unset;
    min-width: unset;
    margin-right: 0;
    filter: none;
    width: 100%;
    display: flex;
    flex-direction: row;
    gap: 0.5rem;
    justify-content: flex-start;
    align-items: center;
    scale: 1;
    pointer-events: auto;
  }

  .suggestion-item:hover {
    background-color: rgba(255, 255, 255, 0.1);
    scale: 1;
  }

  .suggestion-item:active {
    background-color: rgba(255, 255, 255, 0.18);
    scale: 1;
  }

  /* ─── Suggestion icon (left of text) ────────────────────────────────────── */

  .suggestion-icon {
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    width: 18px;
    height: 18px;
  }

  /* Override Icon component styling for white-on-gradient appearance */
  .suggestion-icon :global(.icon) {
    animation: none !important;
    opacity: 0.9 !important;
    border: none !important;
    background: transparent !important;
    width: 18px !important;
    height: 18px !important;
    min-width: 18px !important;
    min-height: 18px !important;
    border-radius: 0 !important;
    box-shadow: none !important;
    filter: none !important;
  }

  /* Make the icon itself white via CSS filter (invert + brightness for white on gradient) */
  .suggestion-icon :global(.icon::before) {
    filter: brightness(0) invert(1);
    opacity: 0.9;
    /* Use larger icon within the 18px container */
    background-size: 80% !important;
  }

  /* Fallback icon: back.svg flipped to point right */
  .fallback-icon {
    width: 18px;
    height: 18px;
    -webkit-mask-image: url('@openmates/ui/static/icons/back.svg');
    mask-image: url('@openmates/ui/static/icons/back.svg');
    -webkit-mask-size: contain;
    mask-size: contain;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    -webkit-mask-position: center;
    mask-position: center;
    background-color: rgba(255, 255, 255, 0.9);
    /* Flip horizontally: left-pointing arrow → right-pointing arrow */
    transform: scaleX(-1);
  }

  /* ─── Suggestion text ───────────────────────────────────────────────────── */

  .suggestion-text {
    flex: 1;
    font-weight: 600;
    /* Intentionally white on gradient — branded card, not a theme surface.
       Same approach as ChatHeader.svelte loaded-title. */
    color: #ffffff;
  }

  .suggestion-text .text-part {
    color: rgba(255, 255, 255, 0.85);
    transition: color 0.15s ease;
  }

  .suggestion-text .text-match {
    color: #ffffff;
    font-weight: 700;
  }

  .suggestion-item:hover .suggestion-text .text-part {
    color: #ffffff;
  }

  /* ─── Mobile adjustments (≤730px) ───────────────────────────────────────── */

  @media (max-width: 730px) {
    .suggestions-card {
      padding: 0.75rem 0.75rem;
      /* Taller on mobile to accommodate text wrapping from reduced width */
      height: 195px;
    }

    .deco-icon {
      width: 64px;
      height: 64px;
    }

    .deco-icon :global(svg) {
      width: 64px !important;
      height: 64px !important;
    }

    .deco-icon-left {
      left: -14px;
    }

    .deco-icon-right {
      right: -14px;
    }

    .suggestion-item {
      font-size: 0.9375rem;
      padding: 0.25rem 0.375rem;
    }

    .suggestions-header {
      padding: 0 0.9375rem;
    }

    /* Nav arrows: match mobile card height */
    .nav-arrow {
      height: 195px;
      width: 30px !important;
    }
  }
</style>
