<!--
  WorkflowSidePanelView — presentational shell of the chat workflow side panel:
  header (kicker, editable name, Save, Close), status line (loading / AI
  generating with Stop / error with retry), the shared WorkflowEditorWorkspace,
  and a saved/unsaved hint. State and persistence live in WorkflowSidePanel.svelte.
  `fullscreen` is true below the 1024px split breakpoint, where the panel covers
  the chat and the close control reads as "back to chat".
-->
<script lang="ts">
  import { text } from '../../i18n/translations';
  import type { WorkflowGraph } from '../../stores/workflowWorkspaceStore';
  import WorkflowEditorWorkspace, { type WorkflowEditorPreview } from './WorkflowEditorWorkspace.svelte';
  import WorkflowAuthoringStatus, { type WorkflowAuthoringStopControl } from './WorkflowAuthoringStatus.svelte';
  import type { WorkflowAiChangeReview, WorkflowAuthoringInfo } from './WorkflowAuthoringNotices.svelte';

  /** Editor content; null while loading or when nothing could be generated. */
  export interface WorkflowSidePanelEditor {
    workflowId: string | null;
    graph: WorkflowGraph;
    preview: WorkflowEditorPreview | null;
    info: WorkflowAuthoringInfo | null;
    review: WorkflowAiChangeReview | null;
    aiAddedNodeIds: string[];
    aiEditedNodeIds: string[];
    onChange: (graph: WorkflowGraph) => void;
    onSave: (graph: WorkflowGraph) => Promise<void>;
    onDraftStateChange: (hasDraft: boolean) => void;
  }

  /** Error line; `onRetry` is null when retrying cannot help. */
  export interface WorkflowSidePanelError {
    message: string;
    onRetry: (() => void) | null;
  }

  let {
    fullscreen,
    saved,
    title,
    status,
    stop,
    error,
    editor,
    saving,
    canSave,
    onTitleInput,
    onSave,
    onClose
  }: {
    fullscreen: boolean;
    /** True once the workflow exists on the server and has no unsaved panel changes. */
    saved: boolean;
    title: string;
    /** Loading or generating status; null hides the status line. */
    status: string | null;
    stop: WorkflowAuthoringStopControl | null;
    error: WorkflowSidePanelError | null;
    editor: WorkflowSidePanelEditor | null;
    saving: boolean;
    canSave: boolean;
    onTitleInput: (title: string) => void;
    onSave: () => void;
    onClose: () => void;
  } = $props();

  const tr = (key: string) => $text(`workflows.side_panel.${key}`);
  let workspace = $state<WorkflowEditorWorkspace | null>(null);

  export function hasPendingDraft(): boolean { return workspace?.hasPendingDraft() ?? false; }
  export function savePendingDraft(): Promise<boolean> { return workspace ? workspace.savePendingDraft() : Promise.resolve(true); }
  export function discardPendingDraft(): void { workspace?.discardPendingDraft(); }
</script>

<section class="workflow-side-panel" class:fullscreen data-testid="workflow-side-panel" data-layout={fullscreen ? 'fullscreen' : 'side'} data-saved={saved ? 'true' : 'false'} aria-label={tr(saved ? 'kicker_saved' : 'kicker_draft')}>
  <header class="panel-header">
    <button type="button" class="panel-close" data-testid="workflow-side-panel-close" aria-label={tr('close')} onclick={onClose}>
      <span class="clickable-icon {fullscreen ? 'icon_back' : 'icon_close'}" aria-hidden="true"></span>
    </button>
    <div class="panel-identity">
      <span class="panel-kicker" data-testid="workflow-side-panel-kicker">{tr(saved ? 'kicker_saved' : 'kicker_draft')}</span>
      <input class="panel-title" data-testid="workflow-side-panel-title" aria-label={tr('title_label')} value={title} disabled={!editor || !!editor.preview || saving} oninput={(event) => onTitleInput(event.currentTarget.value)} />
    </div>
    <button type="button" class="panel-save" data-testid="workflow-side-panel-save" disabled={!canSave || saving} onclick={onSave}>{saving ? tr('saving') : tr('save')}</button>
  </header>

  <div class="panel-body">
    {#if status}
      <WorkflowAuthoringStatus message={status} {stop} check={null} />
    {/if}
    {#if error}
      <div class="panel-error" data-testid="workflow-side-panel-error" role="alert">
        <span>{error.message}</span>
        {#if error.onRetry}{@const retry = error.onRetry}<button type="button" data-testid="workflow-side-panel-retry" onclick={() => retry()}>{tr('retry')}</button>{/if}
      </div>
    {/if}
    {#if editor}
      <div class="panel-editor">
        <WorkflowEditorWorkspace
          bind:this={workspace}
          workflowId={editor.workflowId}
          graph={editor.graph}
          {saving}
          preview={editor.preview}
          partialNotice={null}
          info={editor.info}
          review={editor.review}
          testNow={null}
          aiAddedNodeIds={editor.aiAddedNodeIds}
          aiEditedNodeIds={editor.aiEditedNodeIds}
          onChange={editor.onChange}
          onSave={editor.onSave}
          onDraftStateChange={editor.onDraftStateChange}
        />
      </div>
      {#if !editor.preview}
        <p class="panel-hint" data-testid="workflow-side-panel-hint" role="status">{tr(saved ? 'saved_hint' : 'unsaved_hint')}</p>
      {/if}
    {/if}
  </div>
</section>

<style>
  .workflow-side-panel { display: flex; flex-direction: column; height: 100%; min-height: 0; color: var(--color-font-primary); background: var(--color-grey-10); }
  .panel-header { display: flex; align-items: center; gap: var(--spacing-4); flex: none; padding: var(--spacing-5) var(--spacing-6); border-bottom: 1px solid var(--color-grey-25); background: var(--color-grey-0); }
  /* Global button styles (buttons.css) add min-width 112px, a drop shadow and a trailing margin. */
  .panel-close { display: inline-grid; place-items: center; flex: none; width: 2.5rem; min-width: 2.5rem; height: 2.5rem; margin: 0; padding: 0; border: 0; border-radius: var(--radius-full); background: var(--color-grey-20); filter: none; cursor: pointer; }
  .panel-close .clickable-icon { width: 1.25rem; height: 1.25rem; }
  .panel-identity { display: grid; flex: 1 1 auto; min-width: 0; gap: var(--spacing-1); }
  .panel-kicker { color: var(--color-font-secondary); font-size: var(--font-size-small); font-weight: 600; }
  .panel-title { box-sizing: border-box; width: 100%; min-width: 0; padding: var(--spacing-2) var(--spacing-3); border: 1px solid transparent; border-radius: var(--radius-3); color: var(--color-font-primary); background: transparent; font: inherit; font-size: var(--input-font-size); font-weight: 650; }
  .panel-title:hover:not(:disabled),
  .panel-title:focus-visible { border-color: var(--color-grey-30); background: var(--color-grey-10); outline: none; }
  .panel-save { flex: none; padding: var(--spacing-3) var(--spacing-6); border: 0; border-radius: var(--radius-8); color: var(--color-font-button); background: var(--color-button-primary); font: inherit; font-weight: 600; cursor: pointer; }
  .panel-save:disabled { opacity: 0.55; cursor: not-allowed; }
  .panel-body { flex: 1 1 auto; min-height: 0; overflow-y: auto; padding: var(--spacing-5) 0 var(--spacing-8); }
  .panel-editor { box-sizing: border-box; width: min(60rem, calc(100% - 2rem)); margin: 0 auto; border-radius: var(--radius-8); background: var(--color-grey-0); }
  .panel-editor :global(.graph-panel) { width: 100%; margin-block: 0; }
  .panel-hint { max-width: 42rem; margin: var(--spacing-4) auto 0; padding: 0 var(--spacing-5); text-align: center; color: var(--color-font-secondary); font-size: var(--font-size-small); }
  .panel-error { display: flex; justify-content: center; align-items: center; flex-wrap: wrap; gap: var(--spacing-4); max-width: 42rem; margin: var(--spacing-4) auto; padding: var(--spacing-4) var(--spacing-5); border: 1px solid var(--color-error); border-radius: var(--radius-5); color: var(--color-font-primary); background: var(--color-grey-0); }
  .panel-error button { min-width: 0; margin: 0; padding: var(--spacing-2) var(--spacing-4); border: 1px solid var(--color-button-primary); border-radius: var(--radius-5); color: var(--color-primary); background: transparent; filter: none; font: inherit; cursor: pointer; }
  .workflow-side-panel.fullscreen .panel-header { gap: var(--spacing-3); padding: var(--spacing-4); }
  .workflow-side-panel.fullscreen .panel-save { padding: var(--spacing-3) var(--spacing-5); }
  .workflow-side-panel.fullscreen .panel-editor { width: calc(100% - 1rem); }
</style>
