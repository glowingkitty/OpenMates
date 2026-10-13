<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
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
  {#snippet content()}
    <main class="job-detail" data-testid="jobs-detail-body">
      <div class="facts">
        {#if job.company}<div><span>{$text('embeds.jobs.search.result.company')}</span><strong data-testid="jobs-company-value">{job.company}</strong></div>{/if}
        {#if job.location}<div><span>{$text('common.location')}</span><strong>{job.location}</strong></div>{/if}
        {#if job.employment_type}<div><span>{$text('embeds.jobs.search.result.employment_type')}</span><strong>{job.employment_type}</strong></div>{/if}
        {#if published}<div><span>{$text('embeds.jobs.search.result.published')}</span><strong>{published}</strong></div>{/if}
        {#if job.remote === true}<div><span>{$text('embeds.jobs.search.result.remote')}</span><strong data-testid="jobs-remote-badge">{$text('embeds.jobs.search.result.remote')}</strong></div>{/if}
        {#if salary}<div><span>{$text('embeds.jobs.search.result.salary')}</span><strong data-testid="jobs-salary">{salary}</strong></div>{/if}
      </div>

      {#if job.description}
        <section class="description"><h2>{$text('embeds.jobs.search.result.description')}</h2><p>{job.description}</p></section>
      {/if}

      <div class="actions">
        {#if sourceUrl}
          <a data-testid="jobs-source-link" href={sourceUrl} target="_blank" rel="noopener noreferrer">
            {$text('embeds.jobs.search.result.source').replace('{provider}', jobProviderLabel(job.provider) || $text('embeds.jobs.search.result.listing'))}
          </a>
        {/if}
        {#if applyUrl && applyUrl !== sourceUrl}
          <a data-testid="jobs-apply-link" class="apply" href={applyUrl} target="_blank" rel="noopener noreferrer">{$text('embeds.jobs.search.result.apply')}</a>
        {/if}
      </div>
    </main>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .job-detail { box-sizing: border-box; width: 100%; max-width: 1000px; container-type: inline-size; padding: var(--spacing-10); margin: 0 auto; color: var(--color-font-primary); }
  .facts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--spacing-8); }
  .facts > div { display: flex; flex-direction: column; gap: var(--spacing-2); min-width: 0; padding: var(--spacing-6); background: var(--color-grey-10); border-radius: var(--radius-5); overflow-wrap: anywhere; }
  .facts span { color: var(--color-font-secondary); font-size: var(--font-size-small); }
  .facts strong { font-size: var(--font-size-p); font-weight: 600; }
  .description { margin-top: var(--spacing-10); }
  h2 { margin: 0 0 var(--spacing-4); font-size: var(--font-size-h4); }
  .description p { margin: 0; white-space: pre-wrap; line-height: 1.5; overflow-wrap: anywhere; }
  .actions { display: flex; flex-wrap: wrap; gap: var(--spacing-4); margin-top: var(--spacing-10); }
  a { display: inline-flex; align-items: center; padding: var(--spacing-4) var(--spacing-8); border: 1px solid var(--color-grey-30); border-radius: var(--radius-8); color: var(--color-font-primary); text-decoration: none; font-weight: 600; overflow-wrap: anywhere; }
  a:focus-visible { outline: 2px solid var(--color-button-primary); outline-offset: 2px; }
  a.apply { background: var(--color-grey-10); color: var(--color-font-primary); border-color: var(--color-app-jobs-start); }
  @container (max-width: 540px) { .facts { grid-template-columns: 1fr; } .actions { flex-direction: column; } }
  @media (max-width: 600px) { .job-detail { padding: var(--spacing-6); } }
</style>
