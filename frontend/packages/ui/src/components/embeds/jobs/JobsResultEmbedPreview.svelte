<script lang="ts">
  import ExternalLink from '@lucide/svelte/icons/external-link';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import EmbedCalendarDate from '../EmbedCalendarDate.svelte';
  import ResultEmbedCard from '../ResultEmbedCard.svelte';
  import ResultEmbedInfo from '../ResultEmbedInfo.svelte';
  import { text } from '@repo/ui';
  import { jobProviderLabel, jobSalary, normalizeJob, safeExternalUrl, type JobResult } from './jobsEmbedData';

  interface Props {
    id: string;
    job?: JobResult;
    content?: Record<string, unknown>;
    isMobile?: boolean;
    presentationOnly?: boolean;
    resultContext?: 'auto' | 'chat' | 'results';
    onFullscreen: () => void;
  }
  let { id, job, content, isMobile = false, presentationOnly = false, resultContext = 'auto', onFullscreen }: Props = $props();
  let result = $derived(job ?? normalizeJob(id, content ?? {}));
  let salary = $derived(jobSalary(result));
</script>

<UnifiedEmbedPreview
  resultPreview={true}
  {resultContext}
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
  {#snippet resultPrimaryAction()}{#if safeExternalUrl(result.apply_url) || safeExternalUrl(result.url)}<a href={safeExternalUrl(result.apply_url) || safeExternalUrl(result.url)} target="_blank" rel="noopener noreferrer" aria-label="Open listing" onclick={event => event.stopPropagation()}><ExternalLink size={18} aria-hidden="true" /></a>{/if}{/snippet}
  {#snippet details()}
    <div data-testid="jobs-result-card" class="catalog-result-preview">
      <ResultEmbedCard title={result.title || $text('embeds.jobs.search.result.title')} sourceLabel={[result.company, result.location].filter(Boolean).join(" · ")} description={result.description} textFirst={true}>
        {#snippet badge()}{#if result.published_at}<EmbedCalendarDate date={result.published_at} />{/if}{/snippet}
        {#snippet facts()}{#if salary}<ResultEmbedInfo icon="Banknote" label="Salary" value={salary} testId="jobs-salary">{#snippet children()}{salary}{/snippet}</ResultEmbedInfo>{/if}
<ResultEmbedInfo icon="House" label="Remote work" state={result.remote === true ? 'yes' : result.remote === false ? 'no' : 'unknown'} testId="jobs-remote-badge">{#snippet children()}{result.work_arrangement || (result.remote == null ? 'Work arrangement not provided.' : result.remote ? 'Listed as remote.' : 'Not listed as remote.')}{/snippet}</ResultEmbedInfo>{/snippet}
      </ResultEmbedCard>
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .catalog-result-preview { width: 100%; height: 100%; min-width: 0; }
</style>
