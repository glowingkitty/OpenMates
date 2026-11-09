<!--
  WorkflowUnsavedGuard — modal confirm shown before leaving a workflow editor that
  has unsaved changes: Stay, Discard or Save. Shared by the /workflows route
  navigation guard and the chat side panel close control.
-->
<script lang="ts">
  import { focusTrap } from '../../actions/focusTrap';

  let { saving, onStay, onDiscard, onSave }: {
    saving: boolean;
    onStay: () => void;
    onDiscard: () => void;
    onSave: () => void;
  } = $props();
</script>

<div class="unsaved-guard-backdrop" data-testid="workflow-unsaved-guard" role="presentation">
  <div class="unsaved-guard" role="dialog" aria-modal="true" aria-labelledby="workflow-unsaved-title" use:focusTrap={{ onEscape: onStay }}>
    <h2 id="workflow-unsaved-title">Save your changes?</h2>
    <p>This Workflow has unsaved Template changes.</p>
    <div>
      <button type="button" data-testid="workflow-guard-stay" onclick={onStay}>Stay</button>
      <button type="button" data-testid="workflow-guard-discard" onclick={onDiscard}>Discard</button>
      <button type="button" class="primary" data-testid="workflow-guard-save" disabled={saving} onclick={onSave}>Save</button>
    </div>
  </div>
</div>

<style>
  .unsaved-guard-backdrop { position: fixed; z-index: var(--z-index-modal, 1000); inset: 0; display: grid; place-items: center; padding: var(--spacing-6); background: color-mix(in srgb, var(--color-grey-100) 48%, transparent); }
  .unsaved-guard { display: grid; width: min(430px, 100%); gap: var(--spacing-5); padding: var(--spacing-8); border-radius: var(--radius-10); color: var(--color-font-primary); background: var(--color-grey-0); box-shadow: var(--shadow-xl); }
  .unsaved-guard h2,
  .unsaved-guard p { margin: 0; }
  .unsaved-guard p { color: var(--color-font-secondary); }
  .unsaved-guard div { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--spacing-3); }
  .unsaved-guard button { border: 0; border-radius: var(--radius-8, 20px); padding: 10px 14px; cursor: pointer; font: inherit; background: var(--color-grey-20); }
  .unsaved-guard button:disabled { opacity: 0.6; cursor: wait; }
  .unsaved-guard .primary { color: var(--color-font-button); background: var(--color-button-primary); }
</style>
