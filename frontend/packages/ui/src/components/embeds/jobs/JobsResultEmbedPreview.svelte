<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  import { jobDate, jobProviderLabel, jobSalary, normalizeJob, type JobResult } from './jobsEmbedData';

  interface Props {
    id: string;
    job?: JobResult;
    content?: Record<string, unknown>;
    isMobile?: boolean;
    presentationOnly?: boolean;
    onFullscreen: () => void;
  }
  let { id, job, content, isMobile = false, presentationOnly = false, onFullscreen }: Props = $props();
  let result = $derived(job ?? normalizeJob(id, content ?? {}));
  let salary = $derived(jobSalary(result));
  let published = $derived(jobDate(result.published_at));
</script>

<UnifiedEmbedPreview
  {id}
  appId="jobs"
  skillId="search"
  skillIconName="jobs"
  skillName={jobProviderLabel(result.provider) || $text('embeds.jobs.search.result.title')}
  status="finished"
  {isMobile}
  {presentationOnly}
  {onFullscreen}
  showStatus={false}
  showSkillIcon={false}
>
  {#snippet details()}
    <div class="job-card" data-testid="jobs-result-card">
      <div class="job-title" title={result.title || ''}>{result.title || $text('embeds.jobs.search.result.title')}</div>
      {#if result.company}<div class="company">{result.company}</div>{/if}
      {#if result.location}<div class="location">{result.location}</div>{/if}
      <div class="meta">
        {#if result.remote === true}<span class="badge" data-testid="jobs-remote-badge">{$text('embeds.jobs.search.result.remote')}</span>{/if}
        {#if salary}<span class="salary" data-testid="jobs-salary">{salary}</span>{/if}
      </div>
      {#if published}<div class="published">{$text('embeds.jobs.search.result.published')} {published}</div>{/if}
      {#if result.provider}<div class="source">{$text('embeds.jobs.search.result.source').replace('{provider}', jobProviderLabel(result.provider) || result.provider)}</div>{/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .job-card { display: flex; flex-direction: column; gap: var(--spacing-2); min-width: 0; padding-top: var(--spacing-3); }
  .job-title { font-size: var(--font-size-p); font-weight: 600; line-height: 1.25; color: var(--color-font-primary); display: -webkit-box; -webkit-line-clamp: 3; line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; overflow-wrap: anywhere; }
  .company { font-size: var(--font-size-small); color: var(--color-font-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .location, .published, .source { font-size: var(--font-size-small); color: var(--color-font-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .meta { display: flex; align-items: center; gap: var(--spacing-2); flex-wrap: wrap; min-width: 0; }
  .badge { padding: 2px var(--spacing-2); border: 1px solid var(--color-grey-30); border-radius: var(--radius-3); color: var(--color-font-primary); font-size: var(--font-size-small); }
  .salary { font-size: var(--font-size-small); font-weight: 600; color: var(--color-font-primary); overflow-wrap: anywhere; }
</style>
