<!--
  Purpose: Preview card for Mail search skill results.
  Architecture: Uses UnifiedEmbedPreview and displays top mail hits compactly.
  Renders safe plain-text snippets derived from body_text/body_html.
  Architecture: docs/architecture/embeds.md
  Tests: N/A
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  import { buildMailBodyPreviewText } from './mailSearchContent';

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
    id: string;
    query?: string;
    provider?: string;
    status?: 'processing' | 'finished' | 'error' | 'cancelled';
    results?: MailSearchResult[];
    taskId?: string;
    skillTaskId?: string;
    isMobile?: boolean;
    onFullscreen: () => void;
  }

  let {
    id,
    query: queryProp,
    provider: providerProp,
    status: statusProp,
    results: resultsProp,
    taskId,
    // skillTaskId reserved for future skill-cancellation support (not yet used in mail search)
    skillTaskId: _skillTaskId,
    isMobile = false,
    onFullscreen,
  }: Props = $props();

  let localQuery = $state('');
  let localProvider = $state('');
  let localStatus = $state<'processing' | 'finished' | 'error' | 'cancelled'>('processing');
  let storeResolved = $state(false);
  let localResults = $state<MailSearchResult[]>([]);

  $effect(() => {
    if (!storeResolved) {
      localQuery = queryProp || 'Recent emails';
      localProvider = providerProp || 'Proton Mail Bridge';
      localStatus = statusProp || 'processing';
      localResults = resultsProp || [];
    }
  });

  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> | null }) {
    if (!data.decodedContent) {
      if (data.status === 'processing' || data.status === 'finished' || data.status === 'error' || data.status === 'cancelled') {
        localStatus = data.status;
        if (data.status !== 'processing') { storeResolved = true; }
      }
      return;
    }

    const c = data.decodedContent;
    if (typeof c.query === 'string' && c.query.trim()) localQuery = c.query;
    if (typeof c.provider === 'string' && c.provider.trim()) localProvider = c.provider;
    if (Array.isArray(c.results)) localResults = c.results as MailSearchResult[];

    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error' || data.status === 'cancelled') {
      localStatus = data.status;
      if (data.status !== 'processing') { storeResolved = true; }
    }
  }

  let status = $derived(localStatus);
  let skillName = $derived($text('embeds.mail.email'));
  let statusText = $derived.by(() => {
    const count = localResults.length;
    if (status === 'processing') return `${localQuery} · ${localProvider}`;
    if (count <= 0) return `${localQuery} · 0 results`;
    return `${localQuery} · ${count} result${count === 1 ? '' : 's'}`;
  });

  let topResults = $derived(localResults.slice(0, 3));
</script>

<UnifiedEmbedPreview
  {id}
  appId="mail"
  skillId="search"
  skillIconName="mail"
  {status}
  {skillName}
  {taskId}
  {isMobile}
  {onFullscreen}
  showSkillIcon={true}
  showStatus={true}
  customStatusText={statusText}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet details(snippetProps)}
    <div class="mail-search-details" class:mobile={snippetProps.isMobile}>
      {#if topResults.length === 0}
        <div class="empty">{$text('embeds.mail.empty_content')}</div>
      {:else}
        {#each topResults as result}
          <div class="mail-item">
            <div class="line-1">{result.subject || '(No subject)'}</div>
            <div class="line-2">{result.from || result.receiver || 'Unknown sender'}</div>
            <div class="line-3">
              {result.snippet || buildMailBodyPreviewText(result.body_text || '', result.body_html || '')}
            </div>
          </div>
        {/each}
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .mail-search-details {
    display: flex;
    flex-direction: column;
    gap: 6px;
    color: var(--color-grey-100);
    min-height: 80px;
  }

  .mail-item {
    border: 1px solid var(--color-grey-20);
    background: var(--color-grey-5);
    border-radius: 8px;
    padding: 6px 8px;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .line-1 {
    font-size: 12px;
    line-height: 1.3;
    color: var(--color-font-primary);
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .line-2 {
    font-size: 11px;
    line-height: 1.3;
    color: var(--color-font-secondary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .line-3 {
    font-size: 11px;
    line-height: 1.35;
    color: var(--color-font-secondary);
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: normal;
  }

  .mail-search-details.mobile .line-1,
  .mail-search-details.mobile .line-2,
  .mail-search-details.mobile .line-3 {
    font-size: 10px;
  }

  .empty {
    font-size: 12px;
    color: var(--color-font-secondary);
    padding: 8px 0;
  }
</style>
