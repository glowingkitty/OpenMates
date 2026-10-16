<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  import { chatSyncService } from '../../../services/chatSyncService';
  import { jobProviderLabel, jobSearchScope, parsePipeList, previewJobs, stringValue, type EmbedStatus } from './jobsEmbedData';

  interface Props {
    id: string;
    content?: Record<string, unknown>;
    status?: EmbedStatus;
    taskId?: string;
    skillTaskId?: string;
    isMobile?: boolean;
    presentationOnly?: boolean;
    onFullscreen: () => void;
  }

  let { id, content = {}, status = 'processing', taskId, skillTaskId, isMobile = false, presentationOnly = false, onFullscreen }: Props = $props();
  let current = $state<Record<string, unknown>>({});
  let currentStatus = $state<EmbedStatus>('processing');

  $effect(() => { current = content; currentStatus = status; });

  function updated(data: { status: string; decodedContent: Record<string, unknown> }) {
    current = { ...current, ...data.decodedContent };
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error' || data.status === 'cancelled') currentStatus = data.status;
  }

  async function stop() {
    if (currentStatus !== 'processing') return;
    if (skillTaskId) await chatSyncService.sendCancelSkill(skillTaskId, id);
    else if (taskId) await chatSyncService.sendCancelAiTask(taskId);
  }

  let query = $derived(stringValue(current.query) ?? $text('app_skills.jobs.search'));
  let scope = $derived(jobSearchScope(current));
  let count = $derived(typeof current.result_count === 'number' ? current.result_count : 0);
  let previews = $derived(previewJobs(current));
  let providers = $derived([...new Set(parsePipeList(current.providers))]);
  let providerLabel = $derived.by(() => {
    if (providers.length) return providers.map((provider) => jobProviderLabel(provider)).join(', ');
    const selected = stringValue(current.provider);
    if (selected && selected !== 'auto') return jobProviderLabel(selected);
    return jobProviderLabel(previews[0]?.provider) ?? '';
  });
  let warningCount = $derived(Array.isArray(current.warnings) ? current.warnings.length : 0);
  let error = $derived(stringValue(current.error));
</script>

<UnifiedEmbedPreview
  {id}
  appId="jobs"
  skillId="search"
  skillIconName="search"
  skillName={$text('app_skills.jobs.search')}
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
    <div class="jobs-search-preview" data-testid="jobs-search-preview">
      <div class="query" title={query}>{query}</div>
      {#if scope}<div class="scope" data-testid="jobs-search-scope">{scope}</div>{/if}
      {#if providerLabel}<div class="provider">{$text('embeds.via')} {providerLabel}</div>{/if}
      {#if currentStatus === 'processing'}
        <div class="state">{$text('embeds.processing')}</div>
      {:else if currentStatus === 'cancelled'}
        <div class="state">{$text('embeds.cancelled')}</div>
      {:else if currentStatus === 'error'}
        <div class="state error">{error || $text('embeds.search_failed')}</div>
      {:else if count === 0}
        <div class="state">{$text('embeds.search_no_results')}</div>
      {:else}
        <div class="count">{$text('embeds.jobs.search.result_count').replace('{count}', String(count))}</div>
        {#if previews[0]}
          <div class="first-result">
            <span class="first-title">{previews[0].title}</span>
            {#if previews[0].company}<span class="company">{previews[0].company}</span>{/if}
          </div>
        {/if}
        {#if warningCount}<div class="warning">{$text('embeds.jobs.search.partial_results')}</div>{/if}
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .jobs-search-preview { display: flex; flex-direction: column; gap: var(--spacing-2); min-width: 0; padding-top: var(--spacing-4); }
  .query { color: var(--color-font-primary); font-size: var(--font-size-p); font-weight: 600; line-height: 1.3; overflow-wrap: anywhere; display: -webkit-box; -webkit-line-clamp: 3; line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
  .scope, .provider, .state, .company, .warning { color: var(--color-font-secondary); font-size: var(--font-size-small); overflow-wrap: anywhere; }
  .count, .first-title { color: var(--color-font-primary); font-size: var(--font-size-small); font-weight: 600; }
  .first-result { display: flex; flex-direction: column; min-width: 0; }
  .first-title, .company { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
  .warning { color: var(--color-warning); }
  .error { color: var(--color-error); }
</style>
