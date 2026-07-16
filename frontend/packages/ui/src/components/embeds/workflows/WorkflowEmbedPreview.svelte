<!--
  frontend/packages/ui/src/components/embeds/workflows/WorkflowEmbedPreview.svelte
  Snapshot child card for a workflow embed.
  The preview avoids live workflow store reads; fullscreen upgrades to live data.
  This mirrors search-result child previews in other app-skill embeds.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { workflowStatusLabel } from './workflowEmbedData';

  interface Props {
    id: string;
    workflowId?: string;
    title?: string;
    description?: string;
    status?: string;
    enabled?: boolean;
    triggerSummary?: string;
    isMobile?: boolean;
    onFullscreen: () => void;
  }

  let {
    id,
    workflowId = '',
    title = '',
    description = '',
    status = 'manual',
    enabled = true,
    triggerSummary = '',
    isMobile = false,
    onFullscreen,
  }: Props = $props();

  let displayTitle = $derived(title || 'Untitled workflow');
  let subtitle = $derived(triggerSummary || workflowId || workflowStatusLabel(status, enabled));

  function handleStop() {
    // Workflow child cards are not cancellable.
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="workflows"
  skillId="workflow"
  skillIconName="workflow"
  status="finished"
  skillName="Workflow"
  {isMobile}
  {onFullscreen}
  onStop={handleStop}
  showStatus={false}
  showSkillIcon={false}
>
  {#snippet details()}
    <article class="workflow-card" data-testid="workflow-embed-card">
      <div class="icon-shell" aria-hidden="true"><span class="clickable-icon icon_workflow"></span></div>
      <div class="card-body">
        <div class="kicker">{subtitle}</div>
        <h3>{displayTitle}</h3>
        {#if description}<p>{description}</p>{/if}
        <div class="meta-row"><span>{workflowStatusLabel(status, enabled)}</span></div>
      </div>
    </article>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .workflow-card {
    display: flex;
    align-items: stretch;
    gap: var(--spacing-5);
    width: 100%;
    height: 100%;
    padding: var(--spacing-6);
  }

  .icon-shell {
    display: grid;
    flex: 0 0 56px;
    place-items: center;
    border-radius: 18px;
    background: linear-gradient(135deg, var(--color-app-workflows-start, var(--color-primary-start)), var(--color-app-workflows-end, var(--color-primary-end)));
  }

  .icon_workflow {
    width: 28px;
    height: 28px;
    background: var(--color-grey-0) !important;
  }

  .card-body {
    display: flex;
    min-width: 0;
    flex: 1 1 0;
    flex-direction: column;
    justify-content: center;
    gap: var(--spacing-3);
  }

  .kicker,
  .meta-row {
    color: var(--color-font-secondary);
    font-size: var(--font-size-xs);
    font-weight: 600;
  }

  h3,
  p {
    margin: 0;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  h3 {
    color: var(--color-font-primary);
    font-size: var(--font-size-sm);
    font-weight: 700;
    line-height: 1.25;
  }

  p {
    display: -webkit-box;
    color: var(--color-font-secondary);
    font-size: var(--font-size-xs);
    line-height: 1.35;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
  }

  .meta-row span {
    padding: 2px 7px;
    border-radius: var(--radius-full);
    background: var(--color-grey-10);
  }

  :global(.unified-embed-preview.mobile) .workflow-card {
    flex-direction: column;
  }
  :global(.unified-embed-preview.mobile) .icon-shell {
    flex: 0 0 48px;
  }
</style>
