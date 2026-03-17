<!--
  Purpose: Fullscreen viewer for Mail search skill results.
  Architecture: Uses UnifiedEmbedFullscreen and renders sanitized HTML email bodies.
  Security: DOMPurify sanitize + image proxy rewrite for external image URLs.
  Architecture: docs/architecture/embeds.md
  Tests: N/A
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import { text } from '@repo/ui';
  import { sanitizeMailHtmlForRender, buildMailBodyPreviewText } from './mailSearchContent';

  interface MailSearchResult {
    uid?: string;
    message_id?: string;
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
    query?: string;
    provider?: string;
    results?: MailSearchResult[];
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
    query = 'Recent emails',
    provider = 'Proton Mail Bridge',
    results = [],
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

  let selectedIndex = $state(0);
  let selectedResult = $derived(results[selectedIndex] || null);
  let safeBodyHtml = $derived(
    selectedResult?.body_html ? sanitizeMailHtmlForRender(selectedResult.body_html) : ''
  );
  let plainBodyText = $derived(
    selectedResult
      ? (selectedResult.body_text || selectedResult.snippet || buildMailBodyPreviewText('', selectedResult.body_html || ''))
      : ''
  );

  function selectResult(index: number) {
    selectedIndex = index;
  }
</script>

<UnifiedEmbedFullscreen
  appId="mail"
  skillId="search"
  skillIconName="mail"
  embedHeaderTitle={query || 'Recent emails'}
  embedHeaderSubtitle={`${results.length} result${results.length === 1 ? '' : 's'} · ${provider}`}
  onClose={onClose}
  currentEmbedId={embedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
>
  {#snippet content()}
    <div class="mail-search-fullscreen">
      <aside class="results-list">
        {#if results.length === 0}
          <div class="empty">{$text('embeds.mail.empty_content')}</div>
        {:else}
          {#each results as result, idx}
            <button
              class="result-item"
              class:selected={idx === selectedIndex}
              onclick={() => selectResult(idx)}
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
    gap: 12px;
    min-height: calc(100vh - 220px);
  }

  .results-list {
    border: 1px solid var(--color-grey-20);
    border-radius: 12px;
    background: var(--color-grey-5);
    padding: 10px;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .result-item {
    border: 1px solid var(--color-grey-20);
    background: #fff;
    border-radius: 10px;
    padding: 10px;
    text-align: left;
    cursor: pointer;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .result-item.selected {
    border-color: var(--color-app-mail);
    box-shadow: 0 0 0 1px var(--color-app-mail);
  }

  .subject {
    font-size: 13px;
    font-weight: 600;
    color: var(--color-font-primary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .sender,
  .snippet {
    font-size: 12px;
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
    border-radius: 12px;
    background: #fff;
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
    font-size: 16px;
    font-weight: 700;
    color: var(--color-font-primary);
  }

  .reader-meta {
    margin-top: 4px;
    font-size: 12px;
    color: var(--color-font-secondary);
  }

  .reader-body {
    padding: 16px;
    font-size: 14px;
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
    border-radius: 6px;
  }

  .empty {
    padding: 16px;
    font-size: 13px;
    color: var(--color-font-secondary);
  }

  @media (max-width: 900px) {
    .mail-search-fullscreen {
      grid-template-columns: 1fr;
      margin: 72px 8px 90px;
    }

    .results-list {
      max-height: 220px;
    }
  }
</style>
