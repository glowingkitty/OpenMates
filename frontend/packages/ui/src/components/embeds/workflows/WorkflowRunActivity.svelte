<script lang="ts">
  import { locale } from 'svelte-i18n';
  import Icon from '../../Icon.svelte';
  import { text } from '../../../i18n/translations';
  import { loadWorkflowRunPreviewMetadata } from '../../../services/workflowRunPreviewMetadata';
  import WorkflowRunEmbedPreview from './WorkflowRunEmbedPreview.svelte';

  let {
    workflowId, runId, title, description, startedAt, allowLookup = false, onFullscreen,
  }: {
    workflowId: string;
    runId: string;
    title?: string;
    description?: string;
    startedAt?: number;
    allowLookup?: boolean;
    onFullscreen: () => void;
  } = $props();

  let expanded = $state(false);
  let metadata = $state<{ title?: string; description?: string; startedAt?: number }>({});

  $effect(() => {
    const snapshot = { workflowId, runId, title, description, startedAt };
    metadata = { title, description, startedAt };
    if (!allowLookup || (title && startedAt)) return;
    let disposed = false;
    void loadWorkflowRunPreviewMetadata(snapshot).then(result => {
      if (!disposed) metadata = result;
    }).catch(() => {});
    return () => { disposed = true; };
  });

  function formatStartedAt(seconds?: number): string {
    if (!seconds || !Number.isFinite(seconds)) return '';
    const date = new Date(seconds * 1000);
    if (Number.isNaN(date.getTime())) return '';
    const language = $locale || 'en';
    if (language.startsWith('en')) {
      const day = new Intl.DateTimeFormat(language, { month: 'short', day: 'numeric' }).format(date);
      const time = new Intl.DateTimeFormat(language, { hour: 'numeric', minute: '2-digit', hour12: true }).format(date);
      return `${day} ${time.replace(/[\s\u202f]+([AP]M)$/i, '$1')}`;
    }
    return new Intl.DateTimeFormat(language, {
      month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', hour12: true,
    }).format(date);
  }

  const dateLabel = $derived(formatStartedAt(metadata.startedAt));
  const triggerLabel = $derived(metadata.title
    ? $text('workflows.run_embed.triggered_by', { values: { name: metadata.title } })
    : $text('workflows.run_embed.title'));
</script>

<div class="run-activity" data-testid="workflow-run-activity">
  <button
    type="button"
    class="activity-toggle"
    aria-expanded={expanded}
    data-testid="workflow-run-activity-toggle"
    onclick={() => expanded = !expanded}
  >
    <span class="activity-app-icon" aria-hidden="true"><Icon name="workflow" type="app" appId="workflows" size="18px" noAnimation noMargin ariaHidden /></span>
    <span class="summary">{triggerLabel}{#if dateLabel}, {dateLabel}{/if}</span>
    <span class="chevron" class:expanded aria-hidden="true"></span>
  </button>
  {#if expanded}
    <div class="expanded-preview" data-testid="workflow-run-activity-expanded">
      <WorkflowRunEmbedPreview {runId} title={metadata.title} description={metadata.description} startedAt={metadata.startedAt} {onFullscreen} />
    </div>
  {/if}
</div>

<style>
  .run-activity { width:100%; margin-block:var(--spacing-2); border-radius:var(--radius-4); overflow:hidden; }
  .activity-toggle { display:flex; align-items:center; gap:var(--spacing-2); width:100%; min-height:30px; padding:var(--spacing-1) var(--spacing-3); border:0; border-radius:var(--radius-4); background:var(--color-grey-10); color:var(--color-font-primary); font:inherit; font-size:var(--font-size-small); text-align:start; cursor:pointer; }
  .activity-toggle:hover { background:var(--color-grey-20); }
  .activity-toggle:focus-visible { outline:2px solid var(--color-button-primary); outline-offset:-2px; }
  .activity-app-icon { display:inline-flex; align-items:center; justify-content:center; flex:0 0 22px; box-sizing:border-box; width:22px; height:22px; aspect-ratio:1; border:2px solid var(--color-grey-0); border-radius:50%; overflow:hidden; }
  .activity-app-icon :global(.icon) { box-sizing:border-box; border-radius:50% !important; }
  .summary { flex:1; min-width:0; overflow-wrap:anywhere; }
  .chevron { width:8px; height:8px; border-right:2px solid currentColor; border-bottom:2px solid currentColor; transform:rotate(45deg); margin-inline-start:auto; flex:0 0 auto; transition:transform var(--duration-fast) var(--easing-default); }
  .chevron.expanded { transform:rotate(225deg); }
  .expanded-preview { padding:var(--spacing-2) var(--spacing-4) var(--spacing-4); background:var(--color-grey-10); }
  @media (prefers-reduced-motion:reduce) { .chevron { transition:none; } }
</style>
