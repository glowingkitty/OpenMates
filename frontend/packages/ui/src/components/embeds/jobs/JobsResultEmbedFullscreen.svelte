<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import EmbedHeaderCtaButton from '../EmbedHeaderCtaButton.svelte';
  import { text } from '@repo/ui';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import { jobDate, jobProviderLabel, jobSalary, normalizeJob, safeExternalUrl } from './jobsEmbedData';
  import { renderJobResult } from './jobsEmbedText';

  interface Props {
    data: EmbedFullscreenRawData;
    embedId?: string;
    onClose: () => void;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
  }
  let { data, embedId, onClose, hasPreviousEmbed = false, hasNextEmbed = false, onNavigatePrevious, onNavigateNext }: Props = $props();
  let job = $derived(normalizeJob(embedId ?? '', data.decodedContent ?? {}));
  let sourceUrl = $derived(safeExternalUrl(job.url));
  let applyUrl = $derived(safeExternalUrl(job.apply_url));
  let salary = $derived(jobSalary(job));
  let published = $derived(jobDate(job.published_at));
  let deadline = $derived(jobDate(job.valid_through));
  let providerSourceLabel = $derived($text('embeds.jobs.search.result.source').replace('{provider}', jobProviderLabel(job.provider) || $text('embeds.jobs.search.result.listing')));
  const factFields = ['sector', 'role', 'seniority', 'organization_type'] as const;
</script>

<UnifiedEmbedFullscreen
  testId="jobs-result-fullscreen"
  appId="jobs"
  skillId="search"
  embedHeaderTitle={job.title || $text('embeds.jobs.search.result.title')}
  embedHeaderSubtitle={[job.company, job.location, jobProviderLabel(job.provider)].filter(Boolean).join(' · ')}
  skillIconName="jobs"
  showSkillIcon={true}
  currentEmbedId={embedId || job.embed_id}
  {onClose}
  onCopy={() => navigator.clipboard.writeText(renderJobResult(data.decodedContent ?? {}))}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
>
  {#snippet embedHeaderCta()}
    <div class="embed-header-cta-group">
      {#if applyUrl}
        <EmbedHeaderCtaButton label={$text('embeds.jobs.search.result.apply')} href={applyUrl} testId="jobs-apply-link" />
      {:else if sourceUrl}
        <EmbedHeaderCtaButton label={providerSourceLabel} href={sourceUrl} testId="jobs-source-link" />
      {/if}
      {#if sourceUrl && applyUrl && sourceUrl !== applyUrl}
        <EmbedHeaderCtaButton label={providerSourceLabel} href={sourceUrl} variant="secondary" testId="jobs-source-link" />
      {/if}
    </div>
  {/snippet}

  {#snippet content()}
    <main class="job-detail" data-testid="jobs-detail-body">
      <div class="facts">
        {#if job.company}<div><span>{$text('embeds.jobs.search.result.company')}</span><strong data-testid="jobs-company-value">{job.company}</strong></div>{/if}
        {#if job.location}<div><span>{$text('common.location')}</span><strong>{job.location}</strong></div>{/if}
        {#if job.employment_type}<div><span>{$text('embeds.jobs.search.result.employment_type')}</span><strong>{job.employment_type.replaceAll('_', ' ')}</strong></div>{/if}
        {#each factFields as field}
          {#if job[field]}<div><span>{$text(`embeds.jobs.search.result.${field}`)}</span><strong data-testid={`jobs-${field.replaceAll('_', '-')}-value`}>{job[field]}</strong></div>{/if}
        {/each}
        {#if published}<div><span>{$text('embeds.jobs.search.result.published')}</span><strong>{published}</strong></div>{/if}
        {#if job.work_arrangement || job.remote === true}<div><span>{$text('embeds.jobs.search.result.work_arrangement')}</span><strong data-testid={job.remote === true ? 'jobs-remote-badge' : 'jobs-work-arrangement'}>{job.work_arrangement || $text('embeds.jobs.search.result.remote')}</strong></div>{/if}
        {#if salary || job.salary_text}<div><span>{$text('embeds.jobs.search.result.salary')}</span><strong data-testid="jobs-salary">{salary || job.salary_text}</strong></div>{/if}
        {#if deadline}<div><span>{$text('embeds.jobs.search.result.valid_through')}</span><strong>{deadline}</strong></div>{/if}
      </div>

      {#if job.impact}<section class="description" data-testid="jobs-impact"><h2>{$text('embeds.jobs.search.result.impact')}</h2><p>{job.impact}</p></section>{/if}
      {#if job.description}
        <section class="description" data-testid="jobs-description"><h2>{$text('embeds.jobs.search.result.description')}</h2><p>{job.description}</p></section>
      {/if}
      {#if job.detail_status === 'summary'}<p class="details-warning" data-testid="jobs-details-warning">{$text('embeds.jobs.search.result.details_unavailable')}</p>{/if}
    </main>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .job-detail { box-sizing: border-box; width: 100%; max-width: 1000px; container-type: inline-size; padding: var(--spacing-24) var(--spacing-10) var(--spacing-10); margin: 0 auto; color: var(--color-font-primary); }
  .facts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--spacing-8); }
  .facts > div { display: flex; flex-direction: column; gap: var(--spacing-2); min-width: 0; padding: var(--spacing-6); background: var(--color-grey-10); border-radius: var(--radius-5); overflow-wrap: anywhere; }
  .facts span { color: var(--color-font-secondary); font-size: var(--font-size-small); }
  .facts strong { font-size: var(--font-size-p); font-weight: 600; }
  .description { margin-top: var(--spacing-10); }
  h2 { margin: 0 0 var(--spacing-4); font-size: var(--font-size-h4); }
  .description p { margin: 0; white-space: pre-wrap; line-height: 1.5; overflow-wrap: anywhere; }
  .details-warning { margin-top: var(--spacing-8); color: var(--color-font-secondary); }
  @container (max-width: 540px) { .facts { grid-template-columns: 1fr; } }
  /* Header CTAs wrap into two rows on phones and extend below the banner. */
  @media (max-width: 600px) { .job-detail { padding: var(--spacing-32) var(--spacing-6) var(--spacing-6); } }
</style>
