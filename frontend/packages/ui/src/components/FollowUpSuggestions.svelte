<!--
  FollowUpSuggestions.svelte

  Compact quick-send prompts displayed below the chat history.
  The previous gradient suggestion card is intentionally not rendered here anymore;
  that colorful container is reserved for new content after product discussion.
-->
<script lang="ts">
  import { fade } from 'svelte/transition';
  import { appSkillsStore } from '../stores/appSkillsStore';

  let {
    suggestions = [],
    messageInputContent = '',
    onSuggestionClick,
  }: {
    suggestions: string[];
    messageInputContent?: string;
    onSuggestionClick: (suggestion: string, mentionSyntax?: string) => void;
  } = $props();

  // Apps metadata for icon resolution
  let appsMetadata = $state(appSkillsStore.getState());
  let isDismissing = $state(false);
  let clickedSuggestionRaw = $state<string | null>(null);

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

  // Full suggestions pool - computed from prop to avoid duplicates.
  // Strip HTML tags and parse prefix.
  let fullSuggestions = $derived(
    Array.from(new Set(suggestions))
      .map(s => parseSuggestion(stripHtmlTags(s)))
  );

  // Filtered and displayed suggestions based on input content.
  let filteredSuggestions = $derived.by(() => {
    const visibleSuggestions = clickedSuggestionRaw
      ? fullSuggestions.filter(suggestion => suggestion.raw !== clickedSuggestionRaw)
      : fullSuggestions;

    if (!messageInputContent || messageInputContent.trim() === '') {
      return visibleSuggestions.slice(0, 3).map(parsed => ({ ...parsed, matchIndex: -1, matchLength: 0 }));
    }

    // When user is typing, filter across the FULL pool (searching over body text)
    const searchTerm = messageInputContent.trim();
    const searchTermLower = searchTerm.toLowerCase();

    // Search over body text (not the prefix) so prefix doesn't interfere with filtering
    const allFiltered = visibleSuggestions
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

    return allFiltered.slice(0, 3);
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
    if (isDismissing) return;

    const clickedSuggestion = filteredSuggestions.find(suggestion => suggestion.body === body);
    clickedSuggestionRaw = clickedSuggestion?.raw ?? body;
    isDismissing = true;

    // Build mention syntax for skill-prefixed suggestions (e.g. "@skill:web:search")
    const mentionSyntax = appId && subId ? `@skill:${appId}:${subId}` : undefined;
    onSuggestionClick(body, mentionSyntax);
  }

</script>

{#if filteredSuggestions.length > 0}
  <div
    class="suggestions-wrapper"
    class:is-dismissing={isDismissing}
    data-testid="suggestions-wrapper"
    transition:fade={{ duration: 200 }}
  >
    {#each filteredSuggestions as suggestion (suggestion.raw)}
      {@const highlighted = renderHighlightedText(suggestion)}
      <button
        class="suggestion-item"
        data-testid="follow-up-suggestion-item"
        disabled={isDismissing}
        onmousedown={(event) => {
          event.preventDefault();
        }}
        onclick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          handleSuggestionClick(suggestion.appId, suggestion.subId, suggestion.body);
        }}
      >
        <span class="suggestion-text">
          {#if typeof highlighted === 'string'}
            {highlighted}
          {:else}
            <span class="text-part">{highlighted.before}</span><span class="text-match">{highlighted.match}</span><span class="text-part">{highlighted.after}</span>
          {/if}
        </span>
        <svg class="suggestion-enter-icon" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M9 10v4h7a4 4 0 0 0 4-4V4h-2v6a2 2 0 0 1-2 2H9V8l-5 5 5 5v-4" />
        </svg>
      </button>
    {/each}
  </div>
{/if}

<style>
  .suggestions-wrapper {
    width: 100%;
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 0.35rem;
    animation: fadeIn 200ms ease-out;
    transition: opacity 180ms var(--easing-default);
  }

  .suggestions-wrapper.is-dismissing {
    opacity: 0;
    pointer-events: none;
  }

  .suggestion-item {
    all: unset;
    box-sizing: border-box;
    display: inline-flex;
    flex-direction: row;
    align-items: center;
    justify-content: flex-end;
    gap: 0.45rem;
    max-width: min(100%, 780px);
    cursor: pointer;
    color: var(--color-grey-70);
    font-size: clamp(0.8125rem, 0.78rem + 0.2vw, 0.875rem);
    font-weight: 600;
    line-height: 1.35;
    text-align: right;
    transition: color var(--duration-fast) var(--easing-default);
  }

  .suggestion-item:hover,
  .suggestion-item:focus-visible {
    color: var(--color-grey-100);
  }

  .suggestion-item:focus-visible {
    outline: 2px solid var(--color-grey-70);
    outline-offset: 3px;
    border-radius: var(--radius-3);
  }

  .suggestion-enter-icon {
    width: 1.2em;
    height: 1.2em;
    flex-shrink: 0;
    fill: none;
    stroke: currentColor;
    stroke-width: 2.35;
    stroke-linecap: round;
    stroke-linejoin: round;
    transition: color var(--duration-fast) var(--easing-default);
  }

  .suggestion-text {
    color: currentColor;
    flex: 1 1 auto;
  }

  .suggestion-text .text-part,
  .suggestion-text .text-match {
    color: currentColor;
  }

  .suggestion-text .text-match {
    font-weight: 700;
  }

  @keyframes fadeIn {
    from { opacity: 0; }
    to   { opacity: 1; }
  }

  @media (max-width: 500px) {
    .suggestion-item {
      max-width: 100%;
    }
  }

  @media (hover: none), (pointer: coarse) {
    .suggestions-wrapper {
      gap: 0.8rem;
    }
  }

  /* Previous gradient suggestion-card rendering intentionally removed.
     Keep this component as the follow-up quick-send list until the colorful
     container gets its new content. */
</style>
