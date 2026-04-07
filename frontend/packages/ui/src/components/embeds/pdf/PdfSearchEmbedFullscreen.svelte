<!--
  frontend/packages/ui/src/components/embeds/pdf/PdfSearchEmbedFullscreen.svelte

  Fullscreen view for pdf/search skill result embeds.
  Shows the search query and all matches with their context + bolded keyword.

  Architecture:
  - Mounted by ActiveChat.svelte in response to the 'pdfsearchfullscreen' CustomEvent.
  - AppSkillUseRenderer and GroupRenderer dispatch that event when the user clicks
    a finished pdf.search embed card.
  - Data comes from results[0]: { query, total_matches, matches[], truncated }
  - Each match has: { page_num, match_text, context, char_offset }
  - Context is shown with match_text bolded inline (simple string search + split).

  Display:
  - Header: filename + "Search" skill label
  - Meta: search query + match count
  - Match list: each match shows page number + context with keyword highlighted
  - Actions: Copy (copies query + all matches as text)
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import { text } from '@repo/ui';
  import { copyToClipboard } from '../../../utils/clipboardUtils';

  interface SearchMatch {
    page_num?: number;
    match_text?: string;
    context?: string;
    char_offset?: number;
  }

  interface Props {
    /** The skill-use embed's own ID */
    embedId?: string;
    /** Filename of the PDF */
    filename?: string;
    /** Search query */
    query?: string;
    /** Total number of matches found */
    totalMatches?: number;
    /** Whether results were truncated (>50 matches) */
    truncated?: boolean;
    /** Match list */
    matches?: SearchMatch[];
    /** Close handler */
    onClose: () => void;
    /** Whether there is a previous embed to navigate to */
    hasPreviousEmbed?: boolean;
    /** Whether there is a next embed to navigate to */
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
    navigateDirection?: 'previous' | 'next';
    showChatButton?: boolean;
    onShowChat?: () => void;
  }

  let {
    embedId,
    filename: filenameProp,
    query: queryProp,
    totalMatches: totalMatchesProp,
    truncated: truncatedProp,
    matches: matchesProp,
    onClose,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    navigateDirection,
    showChatButton = false,
    onShowChat,
  }: Props = $props();

  // ---------------------------------------------------------------------------
  // Local state — updated via onEmbedDataUpdated
  // ---------------------------------------------------------------------------

  let localFilename = $state<string>('');
  let localQuery = $state<string>('');
  let localTotalMatches = $state<number | undefined>(undefined);
  let localTruncated = $state<boolean>(false);
  let localMatches = $state<SearchMatch[]>([]);

  $effect(() => {
    localFilename = filenameProp || '';
    localQuery = queryProp || '';
    localTotalMatches = totalMatchesProp;
    localTruncated = truncatedProp || false;
    localMatches = matchesProp || [];
  });

  function handleEmbedDataUpdated(data: {
    status: string;
    decodedContent: Record<string, unknown>;
    results?: unknown[];
  }): void {
    console.debug('[PdfSearchEmbedFullscreen] Received embed data update:', {
      status: data.status,
    });

    const c = data.decodedContent;
    if (!c) return;

    const results = c.results as Array<Record<string, unknown>> | undefined;
    const r = results?.[0];

    const fn = c.filename as string | undefined;
    if (fn) localFilename = fn;

    const q = (r?.query ?? c.query) as string | undefined;
    if (q) localQuery = q;

    const tm = (r?.total_matches ?? c.total_matches) as number | undefined;
    if (tm !== undefined) localTotalMatches = tm;

    const tr = (r?.truncated ?? c.truncated) as boolean | undefined;
    if (tr !== undefined) localTruncated = tr;

    const m = (r?.matches ?? c.matches) as SearchMatch[] | undefined;
    if (Array.isArray(m)) localMatches = m;
  }

  // ---------------------------------------------------------------------------
  // Derived display values
  // ---------------------------------------------------------------------------

  let skillName = $derived($text('common.search') || 'Search');

  let displayFilename = $derived.by(() => {
    const fn = localFilename;
    if (!fn) return 'PDF';
    if (fn.length > 50) {
      const lastDot = fn.lastIndexOf('.');
      if (lastDot > 0) {
        const ext = fn.slice(lastDot);
        return fn.slice(0, 47 - ext.length) + '\u2026' + ext;
      }
      return fn.slice(0, 47) + '\u2026';
    }
    return fn;
  });

  let matchSummary = $derived.by(() => {
    if (localTotalMatches === undefined) return '';
    if (localTotalMatches === 0) return 'No matches';
    const count = localTotalMatches === 1 ? '1 match' : `${localTotalMatches} matches`;
    return localTruncated ? `${count} (first 50 shown)` : count;
  });

  /**
   * Build HTML for a context string with match_text bolded.
   * We escape HTML first, then find & wrap the first occurrence of the term.
   */
  function buildContextHtml(context: string, matchText: string): string {
    // HTML-escape the context
    const escaped = context
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');

    if (!matchText) return escaped;

    // Case-insensitive search for the first occurrence of matchText
    const escapedTerm = matchText
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');

    const idx = escaped.toLowerCase().indexOf(escapedTerm.toLowerCase());
    if (idx === -1) return escaped;

    const before = escaped.slice(0, idx);
    const match = escaped.slice(idx, idx + escapedTerm.length);
    const after = escaped.slice(idx + escapedTerm.length);
    return `${before}<strong class="match-highlight">${match}</strong>${after}`;
  }

  // ---------------------------------------------------------------------------
  // Copy action
  // ---------------------------------------------------------------------------

  async function handleCopy(): Promise<void> {
    if (!localQuery && localMatches.length === 0) return;
    try {
      const lines: string[] = [];
      if (localQuery) lines.push(`Search: "${localQuery}"`);
      if (matchSummary) lines.push(matchSummary);
      lines.push('');
      for (const m of localMatches) {
        const pg = m.page_num !== undefined ? `Page ${m.page_num}` : '';
        const ctx = m.context || m.match_text || '';
        if (pg) lines.push(`[${pg}] ${ctx}`);
        else lines.push(ctx);
      }
      const clipResult = await copyToClipboard(lines.join('\n'));
      if (!clipResult.success) throw new Error(clipResult.error || 'Copy failed');
      const { notificationStore } = await import('../../../stores/notificationStore');
      notificationStore.success('Copied to clipboard');
    } catch (err) {
      console.error('[PdfSearchEmbedFullscreen] Failed to copy:', err);
      const { notificationStore } = await import('../../../stores/notificationStore');
      notificationStore.error('Failed to copy to clipboard');
    }
  }
</script>

<UnifiedEmbedFullscreen
  appId="pdf"
  skillId="search"
  embedHeaderTitle={displayFilename}
  embedHeaderSubtitle={skillName}
  skillIconName="search"
  showSkillIcon={true}
  {onClose}
  onCopy={localMatches.length > 0 ? handleCopy : undefined}
  currentEmbedId={embedId}
  onEmbedDataUpdated={handleEmbedDataUpdated}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
>
  {#snippet content()}
    <div class="search-container">
      {#if !localQuery && localMatches.length === 0}
        <div class="no-content">
          <p>No search results available.</p>
        </div>
      {:else}
        <!-- Search query + match summary -->
        <div class="search-meta">
          {#if localQuery}
            <div class="search-query">
              <span class="query-label">Search:</span>
              <span class="query-text">"{localQuery}"</span>
            </div>
          {/if}
            {#if matchSummary}
              <div class="match-summary" aria-label="match summary">{matchSummary}</div>
            {/if}
        </div>

        <!-- Match list -->
        {#if localMatches.length > 0}
          <div class="matches-list">
            {#each localMatches as match, i (i)}
              <div class="match-card">
                <!-- Page number header -->
                {#if match.page_num !== undefined}
                  <div class="match-page">Page {match.page_num}</div>
                {/if}
                <!-- Context with match bolded -->
                {#if match.context || match.match_text}
                  <div class="match-context">
                    <!-- eslint-disable-next-line svelte/no-at-html-tags -->
                    {@html buildContextHtml(match.context || match.match_text || '', match.match_text || '')}
                  </div>
                {/if}
              </div>
            {/each}
          </div>
        {:else if localTotalMatches === 0}
          <div class="no-matches">
            <p>No matches found for "{localQuery}".</p>
          </div>
        {/if}
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  /* ===========================================
     PDF Search Fullscreen — Layout
     =========================================== */

  .search-container {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--spacing-8);
    width: 100%;
    margin-top: 80px;
  }

  .no-content,
  .no-matches {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 160px;
    color: var(--color-font-secondary);
  }

  /* Search query + match count meta block */
  .search-meta {
    width: 100%;
    max-width: 722px;
    display: flex;
    flex-direction: column;
    gap: var(--spacing-3);
    padding: 0 4px;
  }

  .search-query {
    display: flex;
    align-items: baseline;
    gap: var(--spacing-4);
    flex-wrap: wrap;
  }

  .query-label {
    font-size: var(--font-size-small);
    font-weight: 600;
    color: var(--color-grey-70);
    flex-shrink: 0;
  }

  .query-text {
    font-size: var(--font-size-p);
    font-weight: 700;
    color: var(--color-grey-100);
    word-break: break-word;
  }

  .match-summary {
    font-size: var(--font-size-xs);
    font-weight: 500;
    color: var(--color-grey-60);
  }

  /* List of match cards */
  .matches-list {
    width: 100%;
    max-width: 722px;
    display: flex;
    flex-direction: column;
    gap: var(--spacing-5);
  }

  .match-card {
    background-color: var(--color-grey-10);
    border-radius: var(--radius-5);
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
    padding: 14px 16px;
    display: flex;
    flex-direction: column;
    gap: var(--spacing-3);
  }

  .match-page {
    font-size: var(--font-size-xxs);
    font-weight: 700;
    color: var(--color-grey-60);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .match-context {
    font-size: var(--font-size-small);
    line-height: 1.65;
    color: var(--color-grey-90);
    word-break: break-word;
    white-space: pre-wrap;
    user-select: text;
    -webkit-user-select: text;
    cursor: text;
  }

  /* Bolded keyword highlight */
  .match-context :global(.match-highlight) {
    font-weight: 700;
    color: var(--color-grey-100);
    background-color: rgba(255, 200, 50, 0.25);
    border-radius: 2px;
    padding: 0 2px;
  }

  /* ===========================================
     Skill Icon Styling
     =========================================== */

  :global(.unified-embed-fullscreen-overlay .skill-icon[data-skill-icon="search"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/search.svg');
    mask-image: url('@openmates/ui/static/icons/search.svg');
  }
</style>
