<!--
  WorkflowAuthoringStatus — one-line AI authoring status with an optional Stop
  control and an optional "check status" control for a session whose stream ended.
  Shared by the /workflows route composer and the chat side panel.
-->
<script lang="ts">
  /** Stop control; null hides it. */
  export interface WorkflowAuthoringStopControl {
    requested: boolean;
    label: string;
    onStop: () => void;
  }

  /** Resume control for a pending session; null hides it. */
  export interface WorkflowAuthoringCheckControl {
    label: string;
    onCheck: () => void;
  }

  let { message, stop, check }: {
    message: string;
    stop: WorkflowAuthoringStopControl | null;
    check: WorkflowAuthoringCheckControl | null;
  } = $props();
</script>

<div class="workflow-ai-pending" data-testid="workflow-ai-pending" role="status">
  <span>{message}</span>
  {#if stop}<button type="button" data-testid="workflow-ai-stop" disabled={stop.requested} onclick={() => stop.onStop()}>{stop.label}</button>{/if}
  {#if check}<button type="button" onclick={() => check.onCheck()}>{check.label}</button>{/if}
</div>

<style>
  .workflow-ai-pending { display: flex; justify-content: center; align-items: center; gap: 0.75rem; max-width: 42rem; margin: 0.75rem auto; color: var(--color-font-secondary); pointer-events: auto; }
  .workflow-ai-pending button { border: 1px solid var(--color-button-primary); border-radius: var(--radius-5); padding: 0.35rem 0.7rem; background: transparent; color: var(--color-primary); font: inherit; cursor: pointer; }
  .workflow-ai-pending button:disabled { opacity: 0.6; cursor: wait; }
</style>
