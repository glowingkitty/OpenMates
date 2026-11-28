<!--
  Purpose: Fullscreen viewer for Mail search skill results.
  Architecture: Uses UnifiedEmbedFullscreen and renders sanitized HTML email bodies.
  Security: DOMPurify sanitize + image proxy rewrite for external image URLs.
  Architecture: docs/architecture/embeds.md
  Tests: N/A
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import { text } from '@repo/ui';
  import { sanitizeMailHtmlForRender, buildMailBodyPreviewText } from './mailSearchContent';
  import { extractSearchResultsFromContent } from '../embedPreviewHydration';

  interface MailSearchResult {
    embed_id?: string;
    from?: string;
    to?: string;
    receiver?: string;
    subject?: string;
    snippet?: string;
    body_text?: string;
    body_html?: string;
    date?: string;
  }

  interface Props {
    /** Raw embed data — component extracts its own fields internally */
    data: EmbedFullscreenRawData;
    onClose: () => void;
    embedId?: string;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
    navigateDirection?: 'previous' | 'next';
    showChatButton?: boolean;
    onShowChat?: () => void;
  }

  let {
    data,
    onClose,
    embedId,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    navigateDirection,
    showChatButton = false,
    onShowChat,
  }: Props = $props();

  // Extract fields from data prop
  let query = $derived(typeof data.decodedContent?.query === 'string' ? data.decodedContent.query : 'Recent emails');
  let provider = $derived(typeof data.decodedContent?.provider === 'string' ? data.decodedContent.provider : '');
  let inlineResults = $derived(extractSearchResultsFromContent(data.decodedContent) as MailSearchResult[]);
  let embedIds = $derived(data.decodedContent?.embed_ids ?? data.embedData?.embed_ids);
  let timeRange = $derived.by(() => {
    const content = data.decodedContent || {};
    if (typeof content.time_range === 'string' && content.time_range.trim()) return content.time_range;
    const start = typeof content.start_date === 'string' ? content.start_date.trim() : '';
    const end = typeof content.end_date === 'string' ? content.end_date.trim() : '';
    if (start && end) return `${start} to ${end}`;
    if (start) return `Since ${start}`;
    if (end) return `Until ${end}`;
    return 'All time';
  });
  let resultCount = $derived(typeof data.decodedContent?.result_count === 'number' ? data.decodedContent.result_count : inlineResults.length);

  let selection = $state<{ parentId: string | undefined; childId?: string; index: number }>();

  function selectResult(result: MailSearchResult, index: number) {
    selection = { parentId: embedId, childId: result.embed_id, index };
  }

  function transformMailResult(embedId: string, content: Record<string, unknown>): MailSearchResult {
    return { ...content, embed_id: embedId };
  }

  function getSelectedIndex(results: MailSearchResult[]): number {
    const current = selection?.parentId === embedId ? selection : undefined;
    const targetId = current?.childId ?? (current ? undefined : data.focusChildEmbedId);
    const targetIndex = targetId ? results.findIndex((result) => result.embed_id === targetId) : -1;
    return targetIndex >= 0 ? targetIndex : Math.min(current?.index ?? 0, Math.max(0, results.length - 1));
  }
</script>

<UnifiedEmbedFullscreen
  appId="mail"
  skillId="search"
  skillIconName="mail"
  embedHeaderTitle={query || 'Recent emails'}
  embedHeaderSubtitle={`${resultCount} result${resultCount === 1 ? '' : 's'} · ${timeRange}${provider ? ` · ${provider}` : ''}`}
  onClose={onClose}
  currentEmbedId={embedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
  embedIds={embedIds as string | string[] | undefined}
  childEmbedTransformer={transformMailResult}
>
  {#snippet content({ children })}
    {@const results = children.length ? children as MailSearchResult[] : inlineResults}
    {@const selectedIndex = getSelectedIndex(results)}
    {@const selectedResult = results[selectedIndex]}
    <div class="mail-search-fullscreen">
      <aside class="results-list">
        {#if results.length === 0}
          <div class="empty">{$text('embeds.mail.empty_content')}</div>
        {:else}
          {#each results as result, idx}
            <button
              class="result-item"
              class:selected={idx === selectedIndex}
              onclick={() => selectResult(result, idx)}
              data-testid="mail-search-result"
            >
              <div class="subject">{result.subject || '(No subject)'}</div>
              <div class="sender">{result.from || result.receiver || 'Unknown sender'}</div>
              <div class="snippet">
                {result.snippet || buildMailBodyPreviewText(result.body_text || '', result.body_html || '')}
              </div>
            </button>
          {/each}
        {/if}
      </aside>

      <section class="mail-reader">
        {#if selectedResult}
          {@const safeBodyHtml = selectedResult.body_html ? sanitizeMailHtmlForRender(selectedResult.body_html) : ''}
          {@const plainBodyText = selectedResult.body_text || selectedResult.snippet || buildMailBodyPreviewText('', selectedResult.body_html || '')}
          <header class="reader-header">
            <div class="reader-subject">{selectedResult.subject || '(No subject)'}</div>
            <div class="reader-meta">
              <span>{selectedResult.from || selectedResult.receiver || 'Unknown sender'}</span>
              {#if selectedResult.date}
                <span>· {selectedResult.date}</span>
              {/if}
            </div>
          </header>

          {#if safeBodyHtml}
            <!-- eslint-disable-next-line svelte/no-at-html-tags -- safeBodyHtml is DOMPurify-sanitized with strict allowlist and all images proxied via proxyImage() -->
            <article class="reader-body html-body">{@html safeBodyHtml}</article>
          {:else}
            <article class="reader-body text-body">{plainBodyText || $text('embeds.mail.empty_content')}</article>
          {/if}
        {:else}
          <div class="empty">{$text('embeds.mail.empty_content')}</div>
        {/if}
      </section>
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .mail-search-fullscreen {
    margin: 72px 12px 100px;
    display: grid;
    grid-template-columns: minmax(240px, 320px) 1fr;
    gap: var(--spacing-6);
    min-height: calc(100vh - 220px);
  }

  .results-list {
    border: 1px solid var(--color-grey-20);
    border-radius: var(--radius-5);
    background: var(--color-grey-5);
    padding: var(--spacing-5);
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: var(--spacing-4);
  }

  .result-item {
    border: 1px solid var(--color-grey-20);
    background: var(--color-grey-0);
    border-radius: var(--radius-4);
    padding: var(--spacing-5);
    text-align: left;
    cursor: pointer;
    display: flex;
    flex: none;
    flex-direction: column;
    align-items: stretch;
    height: auto;
    margin: 0;
    filter: none;
    gap: var(--spacing-2);
  }

  .result-item.selected {
    border-color: var(--color-app-mail);
    box-shadow: 0 0 0 1px var(--color-app-mail);
  }

  .subject {
    font-size: var(--font-size-xs);
    font-weight: 600;
    color: var(--color-font-primary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .sender,
  .snippet {
    font-size: var(--font-size-xxs);
    color: var(--color-font-secondary);
    line-height: 1.35;
  }

  .snippet {
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .mail-reader {
    border: 1px solid var(--color-grey-20);
    border-radius: var(--radius-5);
    background: var(--color-grey-0);
    overflow: hidden;
    display: flex;
    flex-direction: column;
  }

  .reader-header {
    padding: 14px 16px;
    border-bottom: 1px solid var(--color-grey-20);
    background: var(--color-grey-5);
  }

  .reader-subject {
    font-size: var(--font-size-p);
    font-weight: 700;
    color: var(--color-font-primary);
  }

  .reader-meta {
    margin-top: var(--spacing-2);
    font-size: var(--font-size-xxs);
    color: var(--color-font-secondary);
  }

  .reader-body {
    padding: var(--spacing-8);
    font-size: var(--font-size-small);
    line-height: 1.5;
    color: var(--color-font-primary);
    overflow-y: auto;
    min-height: 280px;
  }

  .text-body {
    white-space: pre-wrap;
    word-break: break-word;
  }

  .html-body :global(img) {
    max-width: 100%;
    height: auto;
    border-radius: var(--radius-2);
  }

  .empty {
    padding: var(--spacing-8);
    font-size: var(--font-size-xs);
    color: var(--color-font-secondary);
  }

  @media (max-width: 900px) {
    .mail-search-fullscreen {
      grid-template-columns: minmax(0, 1fr);
      grid-template-rows: auto 1fr;
      margin: 72px 8px 90px;
    }

    .results-list {
      max-height: 220px;
    }
  }
</style>
