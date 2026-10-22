<script lang="ts">
  import ResultEmbedFullscreen from '../ResultEmbedFullscreen.svelte';
  import ResultEmbedInfo from '../ResultEmbedInfo.svelte';
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

<ResultEmbedFullscreen
  result={({ title: job.title, company: job.company, location: job.location, url: sourceUrl, apply_url: applyUrl })}
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
    </div>
  {/snippet}

  {#snippet summary()}{#if salary || job.salary_text}<ResultEmbedInfo icon="Banknote" label={$text('embeds.jobs.search.result.salary')} value={salary || job.salary_text} testId="jobs-salary">{#snippet children()}{salary || job.salary_text}{/snippet}</ResultEmbedInfo>{/if}
{#if job.employment_type}<ResultEmbedInfo icon="BriefcaseBusiness" label={$text('embeds.jobs.search.result.employment_type')} value={job.employment_type.replaceAll('_', ' ')}>{#snippet children()}{job.employment_type}{/snippet}</ResultEmbedInfo>{/if}
<ResultEmbedInfo icon="House" label="Remote work" state={job.remote === true ? 'yes' : job.remote === false ? 'no' : 'unknown'}>{#snippet children()}{job.work_arrangement || 'Work arrangement not provided.'}{/snippet}</ResultEmbedInfo>{/snippet}

  {#snippet detailContent()}
    <main class="job-detail" data-testid="jobs-detail-body">
      {#if sourceUrl && applyUrl && sourceUrl !== applyUrl}
        <div class="source-action">
          <EmbedHeaderCtaButton label={providerSourceLabel} href={sourceUrl} variant="secondary" testId="jobs-source-link" />
        </div>
      {/if}
      <div class="facts">
        {#if job.company}<ResultEmbedInfo icon="Building2" label={$text('embeds.jobs.search.result.company')} value={job.company} testId="jobs-company-value">{#snippet children()}{job.company}{/snippet}</ResultEmbedInfo>{/if}
        {#if job.location}<ResultEmbedInfo icon="MapPin" label={$text('common.location')} value={job.location}>{#snippet children()}{job.location}{/snippet}</ResultEmbedInfo>{/if}
        {#each factFields as field}{#if job[field]}<ResultEmbedInfo icon="BriefcaseBusiness" label={$text(`embeds.jobs.search.result.${field}`)} value={job[field]} testId={`jobs-${field.replaceAll('_', '-')}-value`}>{#snippet children()}{job[field]}{/snippet}</ResultEmbedInfo>{/if}{/each}
        {#if published || deadline}<ResultEmbedInfo icon="Calendar" label={$text('embeds.jobs.search.result.published')} value={published || deadline}>{#snippet children()}{#if published}<p>{$text('embeds.jobs.search.result.published')} {published}</p>{/if}{#if deadline}<p>{$text('embeds.jobs.search.result.valid_through')} {deadline}</p>{/if}{/snippet}</ResultEmbedInfo>{/if}
        {#if job.work_arrangement || job.remote === true}<ResultEmbedInfo icon="House" label={$text('embeds.jobs.search.result.work_arrangement')} value={job.work_arrangement || $text('embeds.jobs.search.result.remote')} testId={job.remote === true ? 'jobs-remote-badge' : 'jobs-work-arrangement'}>{#snippet children()}{job.work_arrangement || $text('embeds.jobs.search.result.remote')}{/snippet}</ResultEmbedInfo>{/if}
      </div>

      {#if job.impact}<section class="description" data-testid="jobs-impact"><h2>{$text('embeds.jobs.search.result.impact')}</h2><p>{job.impact}</p></section>{/if}
      {#if job.description}
        <section class="description" data-testid="jobs-description"><h2>{$text('embeds.jobs.search.result.description')}</h2><p>{job.description}</p></section>
      {/if}
      {#if job.detail_status === 'summary'}<p class="details-warning" data-testid="jobs-details-warning">{$text('embeds.jobs.search.result.details_unavailable')}</p>{/if}
    </main>
  {/snippet}
</ResultEmbedFullscreen>

<style>
 .source-action {display:flex;justify-content:center;margin-bottom:var(--spacing-4);}
 .job-detail {width:100%;color:var(--color-font-primary);} .facts {display:flex;flex-wrap:wrap;justify-content:center;gap:var(--spacing-2);} .description {margin-top:var(--spacing-6);} h2 {margin:0 0 var(--spacing-3);font-size:var(--font-size-p);} .description p {margin:0;white-space:pre-wrap;line-height:1.5;overflow-wrap:anywhere;} .details-warning {color:var(--color-font-secondary);margin-top:var(--spacing-4);}
</style>
