<script lang="ts">
  import { fade } from 'svelte/transition';
  import { onMount } from 'svelte';
  import { locale } from 'svelte-i18n';
  import Icon from './Icon.svelte';
  import { appSkillsStore } from '../stores/appSkillsStore';

  let {
    suggestions = [],
    messageInputContent = '',
    onSuggestionClick
  }: {
    suggestions: string[];
    messageInputContent?: string;
    onSuggestionClick: (suggestion: string, mentionSyntax?: string) => void;
  } = $props();

  // Import text function for translations
  import { text } from '@repo/ui';
  
  // Force reactivity to language changes
  let currentLocale = $state($locale);

  // Apps metadata for icon resolution
  let appsMetadata = $state(appSkillsStore.getState());

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
   * If no valid app+skill pair is found, appId/subId are set to null so no icons render.
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
      // Unknown skill — keep body text but don't render any app/skill icons
      return { raw, prefix: null, appId: null, subId: null, body };
    }

    return { raw, prefix, appId, subId, body };
  }

  /**
   * Resolve the icon image name for a skill or focus mode.
   * Returns the icon_image string (svg filename without extension) if found,
   * or null if not resolvable.
   */
  function resolveSubIcon(appId: string, subId: string): string | null {
    const app = appsMetadata?.apps?.[appId];
    if (!app) return null;

    // Check skills first
    const skill = app.skills?.find(s => s.id === subId);
    if (skill?.icon_image) return skill.icon_image.replace(/\.svg$/i, '');

    // Check focus modes
    const focus = app.focus_modes?.find(f => f.id === subId);
    if (focus?.icon_image) return focus.icon_image.replace(/\.svg$/i, '');

    return null;
  }

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

  // Detect if device is touch-capable
  // Checks for ontouchstart event support and maxTouchPoints
  const isTouchDevice = () => {
    return (('ontouchstart' in window) ||
            (navigator.maxTouchPoints > 0) ||
            ((navigator as Navigator & { msMaxTouchPoints?: number }).msMaxTouchPoints > 0));
  };

  let touchDevice = $state(isTouchDevice());

  // Full suggestions pool - computed from prop to avoid duplicates.
  // Strip HTML tags and parse prefix. Search is done over the full raw string
  // (including "[prefix]") so users can type "web" to find web-skill suggestions.
  let fullSuggestions = $derived(
    Array.from(new Set(suggestions))
      .map(s => parseSuggestion(stripHtmlTags(s)))
  );

  // Filtered and displayed suggestions based on input content.
  // matchIndex/matchLength are relative to `parsed.raw` (full string with prefix)
  // so the highlight stays on the body text after the prefix chip is rendered separately.
  let filteredSuggestions = $derived.by(() => {
    // When input is empty, show first 3 suggestions
    if (!messageInputContent || messageInputContent.trim() === '') {
      const displayedSuggestions = fullSuggestions.slice(0, 3);
      console.debug('[FollowUpSuggestions] Showing first 3 suggestions (input empty):', displayedSuggestions.length);
      return displayedSuggestions.map(parsed => ({ ...parsed, matchIndex: -1, matchLength: 0 }));
    }

    // When user is typing, filter across the FULL pool (searching over body text)
    const searchTerm = messageInputContent.trim();
    const searchTermLower = searchTerm.toLowerCase();

    console.debug('[FollowUpSuggestions] Filtering with search term:', {
      searchTerm,
      searchTermLower,
      fullPoolSize: fullSuggestions.length
    });

    // Search over body text (not the prefix) so prefix doesn't interfere with filtering
    const filtered = fullSuggestions
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
      .filter(item => item.body.toLowerCase() !== searchTermLower)
      // Limit to top 3 unique matches
      .slice(0, 3);

    console.debug('[FollowUpSuggestions] Filtered results:', filtered.length, 'unique matches');

    return filtered;
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

  // Update currentLocale when language changes to force component re-render
  onMount(() => {
    const handleLanguageChange = () => {
      currentLocale = $locale;
      console.debug('[FollowUpSuggestions] Language changed, updating locale:', currentLocale);
    };
    
    window.addEventListener('language-changed', handleLanguageChange);
    
    return () => {
      window.removeEventListener('language-changed', handleLanguageChange);
    };
  });
</script>

{#if filteredSuggestions.length > 0}
  <div class="suggestions-wrapper" transition:fade={{ duration: 200 }}>
    <div class="suggestions-header">
      {#key currentLocale}
        {touchDevice ? $text('chat.suggestions.header_tap') : $text('chat.suggestions.header_click')}
      {/key}
    </div>
    <div class="suggestions-container">
      {#each filteredSuggestions as suggestion (suggestion.raw)}
        {@const highlighted = renderHighlightedText(suggestion)}
        {@const subIconName = suggestion.appId && suggestion.subId ? resolveSubIcon(suggestion.appId, suggestion.subId) : null}
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
          transition:fade={{ duration: 150 }}
        >
          {#if suggestion.appId}
            <span class="app-skill-icons">
              <Icon name={suggestion.appId} type="app" size="16px" noAnimation noMargin />
              {#if subIconName}
                <Icon name={subIconName} type="skill" size="14px" noAnimation noMargin />
              {/if}
            </span>
          {/if}
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
    display: flex;
    flex-direction: row;
    flex-wrap: wrap;
    gap: 0 6px;
    justify-content: flex-start;
    align-items: center;
    scale: 1;
  }

  /* App + skill icon pair rendered before the suggestion body text.
     Shows the gradient app icon (square with rounded edges) alongside
     the smaller skill-specific icon for clear visual identification. */
  .app-skill-icons {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    flex-shrink: 0;
    opacity: 0.8;
  }

  /* Override Icon animation/border so it blends into the suggestion row */
  .app-skill-icons :global(.icon) {
    animation: none !important;
    opacity: 1 !important;
    border: none !important;
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
