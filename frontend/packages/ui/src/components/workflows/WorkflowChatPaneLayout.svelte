<!--
  WorkflowChatPaneLayout — presentational shell of the workflow editor shown in
  a chat (WorkflowChatPane.svelte owns state and persistence). It renders the
  regular /workflows UI: WorkflowProvisionalView with the AI status and Stop
  while authoring runs, then WorkflowEditorPane (draft or saved) with the
  regular detail header, Save (workflow-save-draft), enable toggle and Close
  (workflow-detail-back). `fullscreen` is true below the 1024px split
  breakpoint, where the pane covers the chat.
  Exposed (editor stage): hasUnsavedChanges(), hasPendingDraft(), saveChanges(), discardChanges().
-->
<script lang="ts" module>
  import type { WorkflowDetail } from '../../stores/workflowWorkspaceStore';
  import type { WorkflowAuthoringStopControl } from './WorkflowAuthoringStatus.svelte';
  import type { WorkflowEditorPaneState, WorkflowEditorSource } from './workflowEditorPane';

  /** What the pane shows. */
  export type WorkflowChatPaneStage =
    | { kind: 'message'; title: string; message: string | null }
    | { kind: 'authoring'; workflow: WorkflowDetail; phase: 'planning' | 'validating' | 'retrying_node' | 'saving'; acceptedNodeCount: number; message: string; stop: WorkflowAuthoringStopControl }
    | { kind: 'editor'; source: WorkflowEditorSource; onError: (message: string | null) => void; onStateChange: (state: WorkflowEditorPaneState) => void };

  /** Error line; `onRetry` is null when retrying cannot help. */
  export interface WorkflowChatPaneError {
    message: string;
    onRetry: (() => void) | null;
  }
</script>

<script lang="ts">
  import { text } from '../../i18n/translations';
  import WorkflowDetailPage from './WorkflowDetailPage.svelte';
  import WorkflowEditorPane from './WorkflowEditorPane.svelte';
  import WorkflowProvisionalView from './WorkflowProvisionalView.svelte';
  import WorkflowAuthoringStatus from './WorkflowAuthoringStatus.svelte';

  let { fullscreen, stage, error, onClose }: {
    fullscreen: boolean;
    stage: WorkflowChatPaneStage;
    error: WorkflowChatPaneError | null;
    onClose: () => void;
  } = $props();

  let editor = $state<WorkflowEditorPane | null>(null);

  const paneState = $derived(stage.kind === 'editor' ? stage.source.kind : stage.kind);

  export function hasUnsavedChanges(): boolean { return editor?.hasUnsavedChanges() ?? false; }
  export function hasPendingDraft(): boolean { return editor?.hasPendingDraft() ?? false; }
  export function saveChanges(): Promise<boolean> { return editor ? editor.saveChanges() : Promise.resolve(true); }
  export function discardChanges(): void { editor?.discardChanges(); }
</script>

<section class="workflow-chat-pane" class:fullscreen data-testid="workflow-chat-pane" data-layout={fullscreen ? 'fullscreen' : 'side'} data-state={paneState} aria-label={$text('workflows.builder.workflow')}>
  {#if stage.kind === 'authoring'}
    <WorkflowProvisionalView workflow={stage.workflow} pendingMessage={null} phase={stage.phase} acceptedNodeCount={stage.acceptedNodeCount} {onClose} />
    <div class="pane-status"><WorkflowAuthoringStatus message={stage.message} stop={stage.stop} check={null} /></div>
  {:else if stage.kind === 'editor'}
    <WorkflowEditorPane bind:this={editor} source={stage.source} {onClose} onError={stage.onError} onStateChange={stage.onStateChange} />
  {:else}
    <WorkflowDetailPage state="provisional" title={stage.title} description="" category="general_knowledge" icon="workflow" onOpenHome={onClose} />
    {#if stage.message}<WorkflowAuthoringStatus message={stage.message} stop={null} check={null} />{/if}
  {/if}
  {#if error}
    <div class="pane-error" data-testid="workflow-chat-pane-error" role="alert">
      <span>{error.message}</span>
      {#if error.onRetry}{@const retry = error.onRetry}<button type="button" data-testid="workflow-chat-pane-retry" onclick={() => retry()}>{$text('workflows.side_panel.retry')}</button>{/if}
    </div>
  {/if}
</section>

<style>
  .workflow-chat-pane { box-sizing: border-box; height: 100%; min-height: 0; overflow-y: auto; padding-bottom: var(--spacing-8); color: var(--color-font-primary); background: var(--color-grey-20); }
  /* The AI status and Stop stay reachable below a tall pending graph. */
  .pane-status { position: sticky; bottom: var(--spacing-4); z-index: var(--z-index-raised-3); width: fit-content; margin: 0 auto; padding: 0 var(--spacing-5); border-radius: var(--radius-full); background: var(--color-grey-0); box-shadow: var(--shadow-md); }
  .pane-error { position: sticky; bottom: var(--spacing-4); z-index: var(--z-index-raised-3); display: flex; justify-content: center; align-items: center; flex-wrap: wrap; gap: var(--spacing-4); max-width: 42rem; margin: var(--spacing-4) auto; padding: var(--spacing-4) var(--spacing-5); border: 1px solid var(--color-error); border-radius: var(--radius-5); color: var(--color-font-primary); background: var(--color-grey-0); }
  .pane-error button { min-width: 0; margin: 0; padding: var(--spacing-2) var(--spacing-4); border: 1px solid var(--color-button-primary); border-radius: var(--radius-5); color: var(--color-primary); background: transparent; filter: none; font: inherit; cursor: pointer; }
</style>
