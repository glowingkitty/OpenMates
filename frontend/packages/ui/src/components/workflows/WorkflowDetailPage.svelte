<!--
  WorkflowDetailPage.svelte
  Shared Workflow detail header composition for Automation Vault records.
  The owning route supplies the loaded workflow and approved mutation callbacks.
-->

<script lang="ts">
  import WorkspaceReportIssueButton from '../workspace/WorkspaceReportIssueButton.svelte';

  let {
    title,
    description,
    createdAt,
    nextRunAt,
    enabled,
    dirty,
    saving,
    onToggleEnabled,
    onSaveWorkflow,
    onUndoWorkflow,
    onCreateWorkflow,
    onRunWorkflow,
    onDeleteWorkflow,
    runsHref,
  }: {
    title: string;
    description: string;
    createdAt?: number | null;
    nextRunAt?: number | null;
    enabled: boolean;
    dirty: boolean;
    saving: boolean;
    onToggleEnabled: () => void | Promise<void>;
    onSaveWorkflow: () => void | Promise<void>;
    onUndoWorkflow: () => void;
    onCreateWorkflow: () => void | Promise<void>;
    onRunWorkflow: () => void | Promise<void>;
    onDeleteWorkflow: () => void | Promise<void>;
    runsHref: string;
  } = $props();

  const metadataLabel = $derived(nextRunAt ? `Next run ${relativeTime(nextRunAt)}` : createdAt ? `Created ${relativeTime(createdAt)}` : 'Manual workflow');

  function relativeTime(timestampSeconds: number): string {
    const diffSeconds = Math.round(timestampSeconds - Date.now() / 1000);
    const absoluteSeconds = Math.abs(diffSeconds);
    if (absoluteSeconds < 60) return diffSeconds >= 0 ? 'soon' : 'just now';
    const absoluteMinutes = Math.round(absoluteSeconds / 60);
    if (absoluteMinutes < 60) return diffSeconds >= 0 ? `in ${absoluteMinutes} min` : `${absoluteMinutes} min ago`;
    const absoluteHours = Math.round(absoluteMinutes / 60);
    if (absoluteHours < 24) return diffSeconds >= 0 ? `in ${absoluteHours} hr` : `${absoluteHours} hr ago`;
    const absoluteDays = Math.round(absoluteHours / 24);
    return diffSeconds >= 0 ? `in ${absoluteDays} day${absoluteDays === 1 ? '' : 's'}` : `${absoluteDays} day${absoluteDays === 1 ? '' : 's'} ago`;
  }
</script>

<section class="workflow-detail-header" data-testid="workspace-detail-header" data-header-system="workflow-detail">
  <div class="header-actions" data-testid="workflow-detail-actions" aria-label="Workflow actions">
    <a class="back-action" data-testid="workflow-detail-back" href="/workflows" aria-label="Back to workflows">&larr;</a>
    {#if dirty}
      <button type="button" class="secondary-action" data-testid="undo-workflow" disabled={saving} onclick={onUndoWorkflow}>Undo</button>
      <button type="button" class="primary-action" data-testid="save-workflow" disabled={saving} onclick={() => void onSaveWorkflow()}>{saving ? 'Saving...' : 'Save'}</button>
    {/if}
    <button type="button" class="primary-action" data-testid="create-blank-workflow" disabled={saving} onclick={() => void onCreateWorkflow()}>New workflow</button>
    <a class="secondary-action" data-testid="workflow-run-history" href={runsHref}>Run history</a>
    <button type="button" class="secondary-action" data-testid="run-workflow" disabled={saving} onclick={() => void onRunWorkflow()}>Run now</button>
    <button type="button" class="destructive-action" data-testid="delete-workflow" disabled={saving} onclick={() => void onDeleteWorkflow()}>Delete</button>
    <WorkspaceReportIssueButton />
  </div>

  <div class="header-content">
    <p class="workflow-kicker">Workflow</p>
    <h1 data-testid="workspace-detail-title">{title}</h1>
    <p class="description" data-testid="workspace-detail-description">{description}</p>
    <div class="metadata-row">
      <button type="button" class="toggle-pill" data-testid="toggle-workflow" disabled={saving} onclick={() => void onToggleEnabled()}>{enabled ? 'Workflow on' : 'Workflow off'}</button>
      <span data-testid="workflow-detail-metadata">{metadataLabel}</span>
    </div>
  </div>
</section>

<style>
  .workflow-detail-header {
    position: relative;
    min-height: 238px;
    overflow: hidden;
    border-radius: 14px;
    color: var(--color-grey-0);
    background:
      radial-gradient(circle at 18% 8%, color-mix(in srgb, var(--color-grey-0) 22%, transparent), transparent 28%),
      linear-gradient(135deg, var(--color-button-primary), color-mix(in srgb, var(--color-button-primary) 48%, var(--color-grey-100)));
  }

  .header-actions {
    position: absolute;
    z-index: var(--z-index-raised-3);
    top: var(--spacing-5);
  }

  .back-action {
    display: grid;
    width: 42px;
    height: 42px;
    place-items: center;
    border-radius: var(--radius-full);
    color: var(--color-grey-0);
    background: color-mix(in srgb, var(--color-grey-0) 18%, transparent);
    text-decoration: none;
    font-size: 1.4rem;
    font-weight: 900;
  }

  .header-actions {
    left: var(--spacing-5);
    display: flex;
    align-items: center;
    justify-content: flex-start;
    flex-wrap: wrap;
    gap: var(--spacing-4);
  }

  .header-actions button,
  .header-actions a {
    border: 0;
    border-radius: var(--radius-8);
    padding: var(--spacing-5) var(--spacing-8);
    color: var(--color-font-button);
    background: var(--color-button-primary);
    font-weight: 800;
    cursor: pointer;
    text-decoration: none;
  }

  .header-actions .secondary-action {
    color: var(--color-grey-0);
    background: color-mix(in srgb, var(--color-grey-0) 18%, transparent);
  }

  .header-actions .destructive-action {
    color: var(--color-grey-0);
    background: var(--color-danger, #b42318);
  }

  .header-actions button:disabled,
  .toggle-pill:disabled {
    opacity: 0.6;
    cursor: wait;
  }

  .header-content {
    display: grid;
    min-height: inherit;
    place-items: center;
    align-content: center;
    gap: var(--spacing-4);
    padding: calc(var(--spacing-20) + var(--spacing-8)) var(--spacing-20) var(--spacing-12);
    text-align: center;
  }

  .workflow-kicker,
  h1,
  .description {
    margin: 0;
  }

  .workflow-kicker {
    font-size: var(--font-size-small);
    font-weight: 900;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    opacity: 0.82;
  }

  h1 {
    max-width: 860px;
    font-size: clamp(2.1rem, 5vw, 4.5rem);
    line-height: 0.95;
  }

  .description {
    max-width: 680px;
    font-size: clamp(1rem, 2vw, 1.4rem);
    opacity: 0.9;
  }

  .metadata-row {
    display: flex;
    align-items: center;
    justify-content: center;
    flex-wrap: wrap;
    gap: var(--spacing-5);
    color: color-mix(in srgb, var(--color-grey-0) 86%, transparent);
    font-weight: 700;
  }

  .toggle-pill {
    border: 0;
    border-radius: var(--radius-full);
    padding: var(--spacing-4) var(--spacing-8);
    color: var(--color-font-primary);
    background: var(--color-grey-0);
    font-weight: 900;
    cursor: pointer;
  }

  @media (max-width: 720px) {
    .workflow-detail-header {
      min-height: 260px;
    }

    .header-content {
      padding-inline: var(--spacing-8);
      padding-top: 112px;
    }
  }
</style>
