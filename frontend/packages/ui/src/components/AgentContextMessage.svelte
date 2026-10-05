<script lang="ts">
  import { text } from '../i18n/translations';
  import type { AgentContextEvent, ProjectAuthoringRecommendation, ProjectAuthoringJobDisplay } from '../utils/agentContextEvents';

  interface Props {
    event: AgentContextEvent;
    onAuthoring: (recommendation: ProjectAuthoringRecommendation) => Promise<void> | void;
    jobs: readonly ProjectAuthoringJobDisplay[];
    onSaveJob: (jobId: string) => Promise<unknown> | void;
  }
  let { event, onAuthoring, jobs, onSaveJob }: Props = $props();
  let pending = $state<string | null>(null);
  let submitted = $state<string[]>([]);
  let error = $state('');
  let recommendations = $derived(event.type === 'project_authoring_recommendation'
    ? [event] : event.type === 'project_authoring_recommendations' ? event.recommendations : []);
  let relatedJobs = $derived(jobs.filter((job) => recommendations.some((item) => item.recommendation_id === job.recommendation_id && item.chat_id === job.chat_id)));
  let savingJob = $state<string | null>(null);
  let savedJobs = $state<string[]>([]);
  const statuses = ['running', 'queued', 'needs_input', 'needs_save', 'needs_binding_save', 'pending_file', 'partial', 'conflict', 'ready', 'failed', 'saved', 'cancelled'];

  async function saveJob(jobId: string) {
    if (savingJob || savedJobs.includes(jobId)) return;
    savingJob = jobId;
    error = '';
    try { await onSaveJob(jobId); savedJobs = [...savedJobs, jobId]; }
    catch { error = $text('rules.authoring_save_failed'); }
    finally { savingJob = null; }
  }

  async function author(recommendation: ProjectAuthoringRecommendation) {
    if (pending || submitted.includes(recommendation.recommendation_id)) return;
    pending = recommendation.recommendation_id;
    error = '';
    try {
      await onAuthoring(recommendation);
      submitted = [...submitted, recommendation.recommendation_id];
    } catch {
      error = $text('rules.authoring_failed');
    } finally { pending = null; }
  }
</script>

<div class="context-message" data-testid="agent-context-message" data-context-type={event.type}>
  {#if event.type === 'rules_loaded' || event.type === 'memories_loaded'}
    {@const memories = event.type === 'memories_loaded' ? event.memories : event.rules}
    <details data-testid={event.type === 'memories_loaded' ? 'loaded-memories-details' : 'loaded-rules-details'}>
      <summary>{$text('memories.loaded', { values: { count: memories.length } })}</summary>
      <div class="rule-guides">
        {#each memories as rule (rule.id)}
          <section data-testid={event.type === 'memories_loaded' ? 'applied-memory' : 'applied-rule-guide'}>
            <h3>{rule.title}</h3>
            <p class="provenance">{$text(`memories.source_${rule.source}`)}{rule.app_id ? ` · ${rule.app_id}` : ''}{rule.project_id ? ` · ${rule.project_id}` : ''}</p>
            <p class="revision" data-testid="applied-rule-revision">{$text('rules.revision')} {rule.revision}</p>
            <pre data-testid={event.type === 'memories_loaded' ? 'applied-memory-body' : 'applied-rule-body'}>{rule.body}</pre>
          </section>
        {/each}
      </div>
    </details>
  {:else if event.type === 'chat_direction_correction'}
    <details data-testid="direction-correction-details">
      <summary>{event.notice}</summary>
      <pre data-testid="direction-correction-instruction">{event.instruction}</pre>
    </details>
  {:else}
    <p class="recommendation-label">{$text('rules.authoring_suggestions')}</p>
    <div class="actions">
      {#each recommendations as recommendation (recommendation.recommendation_id)}
        <button
          type="button"
          data-testid="project-authoring-action"
          data-recommendation-id={recommendation.recommendation_id}
          disabled={pending !== null || submitted.includes(recommendation.recommendation_id) || (recommendation.expires_at !== undefined && recommendation.expires_at * 1000 <= Date.now())}
          onclick={() => author(recommendation)}
        >
          {#if submitted.includes(recommendation.recommendation_id)}
            {$text('rules.authoring_started')}
          {:else if pending === recommendation.recommendation_id}
            {$text('common.loading')}
          {:else}
            {$text(`rules.${recommendation.action}_${recommendation.kind}`)}
            {recommendation.title ? ` · ${recommendation.title}` : ''}
          {/if}
        </button>
      {/each}
    </div>
    {#each relatedJobs as job (job.job_id)}
      <section class="authoring-job" data-testid="project-authoring-job" data-job-status={job.status}>
        <p role="status">{$text(`rules.job_${statuses.includes(job.status) ? job.status : 'waiting'}`)}</p>
        {#if job.status === 'needs_input' && job.draft?.question}
          <p data-testid="project-authoring-question">{job.draft.question}</p>
        {/if}
        {#if job.status === 'needs_save' || job.status === 'needs_binding_save'}
          {#if job.draft?.markdown}
            <details data-testid="project-authoring-draft">
              <summary>{$text('rules.review_draft')}</summary>
              <pre>{job.draft.markdown}</pre>
            </details>
          {/if}
          <button type="button" onclick={() => saveJob(job.job_id)} disabled={savingJob !== null || savedJobs.includes(job.job_id)} data-testid="project-authoring-save">
            {savingJob === job.job_id ? $text('common.loading') : savedJobs.includes(job.job_id) ? $text('rules.job_saved') : $text('rules.save_draft')}
          </button>
        {/if}
      </section>
    {/each}
    {#if error}<p role="alert">{error}</p>{/if}
  {/if}
</div>

<style>
  .context-message { width: 100%; min-width: 0; color: var(--color-font-secondary); font-size: var(--font-size-small); }
  summary { cursor: pointer; padding: var(--spacing-3) 0; overflow-wrap: anywhere; }
  summary:focus-visible, button:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 3px; }
  .rule-guides { display: grid; gap: var(--spacing-5); }
  section { min-width: 0; border: 1px solid var(--color-grey-25); border-radius: var(--radius-4); padding: var(--spacing-5); background: var(--color-grey-10); }
  h3 { color: var(--color-font-primary); font-size: var(--font-size-small); margin: 0; }
  .provenance, .revision { overflow-wrap: anywhere; }
  .revision { font-family: var(--font-family-mono); }
  pre { white-space: pre-wrap; overflow-wrap: anywhere; font-family: inherit; color: var(--color-font-primary); max-height: 32rem; overflow-y: auto; padding: var(--spacing-4); background: var(--color-grey-0); border-radius: var(--radius-4); }
  .actions { display: flex; flex-wrap: wrap; gap: var(--spacing-3); }
  button { min-height: 2.75rem; padding: var(--spacing-3) var(--spacing-5); border: 1px solid var(--color-grey-30); border-radius: var(--radius-4); color: var(--color-font-primary); background: var(--color-grey-0); cursor: pointer; }
  button:disabled { cursor: default; opacity: .65; }
</style>
