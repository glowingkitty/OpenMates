<script lang="ts">
  import SearchResultsTemplate from '../SearchResultsTemplate.svelte';
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import JobsResultEmbedPreview from './JobsResultEmbedPreview.svelte';
  import JobsResultEmbedFullscreen from './JobsResultEmbedFullscreen.svelte';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import { text } from '@repo/ui';
  import { jobProviderLabel, jobSearchScope, normalizeJob, parsePipeList, stringValue, type EmbedStatus, type JobResult } from './jobsEmbedData';

  interface Props {
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
  let { data, onClose, embedId, hasPreviousEmbed = false, hasNextEmbed = false, onNavigatePrevious, onNavigateNext, navigateDirection, showChatButton = false, onShowChat }: Props = $props();

  let content = $state<Record<string, unknown>>({});
  let status = $state<EmbedStatus>('finished');
  $effect(() => {
    content = data.decodedContent ?? {};
    const raw = data.embedData?.status ?? data.decodedContent?.status;
    status = raw === 'processing' || raw === 'error' || raw === 'cancelled' ? raw : 'finished';
  });
  function updated(data: { status: string; decodedContent: Record<string, unknown> }) {
    content = { ...content, ...data.decodedContent };
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error' || data.status === 'cancelled') status = data.status;
  }

  let query = $derived(stringValue(content.query) ?? $text('app_skills.jobs.search'));
  let scope = $derived(jobSearchScope(content));
  let providers = $derived([...new Set(parsePipeList(content.providers))]);
  let providerLabel = $derived.by(() => {
    if (providers.length) return providers.map((provider) => jobProviderLabel(provider)).join(', ');
    const selected = stringValue(content.provider);
    if (selected && selected !== 'auto') return jobProviderLabel(selected);
    const previews = content.preview_results;
    if (Array.isArray(previews) && previews[0] && typeof previews[0] === 'object') {
      return jobProviderLabel((previews[0] as Record<string, unknown>).provider) ?? '';
    }
    return '';
  });
  let warningCount = $derived(Array.isArray(content.warnings) ? content.warnings.length : 0);
  let subtitle = $derived([scope, providerLabel ? `${$text('embeds.via')} ${providerLabel}` : '', warningCount ? $text('embeds.jobs.search.partial_results') : ''].filter(Boolean).join(' · '));
  let error = $derived(stringValue(content.error));
  let childIds = $derived(content.embed_ids ?? data.embedData?.embed_ids);
  let initialChildEmbedId = $derived(data.focusChildEmbedId ?? undefined);

  function legacyJobs(raw: unknown[]): JobResult[] {
    const jobs: JobResult[] = [];
    for (const entry of raw) {
      if (!entry || typeof entry !== 'object' || Array.isArray(entry)) continue;
      const group = entry as Record<string, unknown>;
      const values = Array.isArray(group.results) ? group.results : [group];
      for (const value of values) {
        if (!value || typeof value !== 'object' || Array.isArray(value)) continue;
        jobs.push(normalizeJob(`legacy-job-${jobs.length}`, value as Record<string, unknown>));
      }
    }
    return jobs;
  }
  let legacyResults = $derived(Array.isArray(content.results) ? content.results : []);
</script>

{#if status === 'finished'}
  <SearchResultsTemplate
    testId="jobs-search-fullscreen"
    appId="jobs"
    skillId="search"
    embedHeaderTitle={query}
    embedHeaderSubtitle={subtitle}
    skillIconName="search"
    showSkillIcon={true}
    {onClose}
    currentEmbedId={embedId}
    embedIds={childIds as string | string[] | undefined}
    childEmbedTransformer={normalizeJob}
    {legacyResults}
    legacyResultTransformer={legacyJobs}
    {initialChildEmbedId}
    onEmbedDataUpdated={updated}
    {hasPreviousEmbed}
    {hasNextEmbed}
    {onNavigatePrevious}
    {onNavigateNext}
    {navigateDirection}
    {showChatButton}
    {onShowChat}
    emptyTestId="jobs-search-empty"
  >
    {#snippet resultCard({ result, onSelect })}
      <JobsResultEmbedPreview id={result.embed_id} job={result} onFullscreen={onSelect} />
    {/snippet}
    {#snippet childFullscreen(nav)}
      <JobsResultEmbedFullscreen
        data={{ decodedContent: nav.result }}
        embedId={nav.result.embed_id}
        onClose={nav.onClose}
        hasPreviousEmbed={nav.hasPrevious}
        hasNextEmbed={nav.hasNext}
        onNavigatePrevious={nav.onPrevious}
        onNavigateNext={nav.onNext}
      />
    {/snippet}
  </SearchResultsTemplate>
{:else}
  <UnifiedEmbedFullscreen
    testId="jobs-search-fullscreen"
    appId="jobs"
    skillId="search"
    embedHeaderTitle={query}
    embedHeaderSubtitle={subtitle}
    skillIconName="search"
    showSkillIcon={true}
    currentEmbedId={embedId}
    {onClose}
    {hasPreviousEmbed}
    {hasNextEmbed}
    {onNavigatePrevious}
    {onNavigateNext}
    onEmbedDataUpdated={updated}
  >
    {#snippet content()}
      <div class="search-state" data-testid="jobs-search-state" role={status === 'error' ? 'alert' : 'status'}>
        {#if status === 'processing'}{$text('embeds.processing')}
        {:else if status === 'cancelled'}{$text('embeds.cancelled')}
        {:else}{error || $text('embeds.search_failed')}{/if}
      </div>
    {/snippet}
  </UnifiedEmbedFullscreen>
{/if}

<style>
  .search-state { max-width: 700px; margin: var(--spacing-12) auto; padding: var(--spacing-10); color: var(--color-font-secondary); text-align: center; overflow-wrap: anywhere; }
</style>
