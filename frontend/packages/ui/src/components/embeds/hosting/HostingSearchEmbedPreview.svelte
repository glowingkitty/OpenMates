<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  import { chatSyncService } from '../../../services/chatSyncService';
  import { formatMoney, type DomainSearchContent, type EmbedStatus } from './hostingDomainData';

  interface Props {
    id: string;
    content?: DomainSearchContent;
    status?: EmbedStatus;
    taskId?: string;
    skillTaskId?: string;
    isMobile?: boolean;
    presentationOnly?: boolean;
    onFullscreen: () => void;
  }

  let { id, content = {}, status = 'finished', taskId, skillTaskId, isMobile = false, presentationOnly = false, onFullscreen }: Props = $props();
  let current = $state<DomainSearchContent>({});
  let currentStatus = $state<EmbedStatus>('finished');

  $effect(() => {
    current = content;
    currentStatus = status;
  });

  function updated(data: { status: string; decodedContent: Record<string, unknown> }) {
    current = { ...current, ...data.decodedContent } as DomainSearchContent;
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error' || data.status === 'cancelled') currentStatus = data.status;
  }

  async function stop() {
    if (skillTaskId) await chatSyncService.sendCancelSkill(skillTaskId, id);
    else if (taskId) await chatSyncService.sendCancelAiTask(taskId);
  }

  let selected = $derived(current.result_count ?? 0);
  let checked = $derived(current.checked_count ?? 0);
  let quote = $derived(current.preview_starting_registration);
  let showQuote = $derived(currentStatus === 'finished' && !!quote && quote.duration === 1 && quote.unit === 'year');
</script>

<UnifiedEmbedPreview
  {id}
  appId="hosting"
  skillId="search_domains"
  skillIconName="search"
  skillName={$text('embeds.hosting.search_domains.title')}
  status={currentStatus}
  {taskId}
  {isMobile}
  {presentationOnly}
  {onFullscreen}
  onStop={stop}
  onEmbedDataUpdated={updated}
  showStatus={currentStatus === 'processing'}
>
  {#snippet details()}
    <div class="search-summary" data-testid="hosting-search-preview">
      <div class="query" title={current.query || ''}>{current.query || $text('embeds.hosting.search_domains.title')}</div>
      <div class="provider">{$text('embeds.hosting.search_domains.provider_via').replace('{provider}', current.provider || 'Gandi')}</div>
      {#if currentStatus === 'processing'}
        <p>{$text('embeds.hosting.search_domains.processing')}</p>
      {:else if currentStatus === 'cancelled'}
        <p>{$text('embeds.hosting.search_domains.cancelled')}</p>
      {:else}
        <p class="counts">
          {$text('embeds.hosting.search_domains.checked_count').replace('{count}', String(checked))}
          · {$text('embeds.hosting.search_domains.available_count').replace('{count}', String(current.available_count ?? 0))}
          · {$text('embeds.hosting.search_domains.unavailable_count').replace('{count}', String(current.unavailable_count ?? 0))}
          {#if (current.unknown_count ?? 0) > 0} · {$text('embeds.hosting.search_domains.unknown_count').replace('{count}', String(current.unknown_count))}{/if}
        </p>
        {#if current.partial}<p class="warning" data-testid="hosting-search-partial">{$text('embeds.hosting.search_domains.partial_results')}</p>{/if}
        {#if currentStatus === 'error' && current.error}<p class="error">{current.error}</p>{/if}
        {#if currentStatus === 'finished' && selected === 0 && checked === 0}<p>{$text('embeds.hosting.search_domains.no_results')}</p>{/if}
        {#if showQuote && quote}<p class="from">{$text('embeds.hosting.search_domains.from_first_year').replace('{price}', formatMoney(quote.amount, quote.currency))}{quote.tax_basis === 'excluding' ? ` · ${$text('embeds.hosting.search_domains.tax_excluded')}` : ''}</p>{/if}
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .search-summary { display: flex; flex-direction: column; gap: var(--spacing-3); min-width: 0; padding-top: var(--spacing-5); }
  .query { color: var(--color-font-primary); font-weight: 600; overflow-wrap: anywhere; line-height: 1.25; max-height: 3.75em; overflow: hidden; }
  .provider, .counts { color: var(--color-font-secondary); }
  p { margin: 0; font-size: var(--font-size-p); }
  .from { color: var(--color-font-primary); font-weight: 600; }
  .warning { color: var(--color-warning); }
  .error { color: var(--color-error); }
</style>
