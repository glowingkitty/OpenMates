<!--
  Status and actions for a user message waiting for assistant work.
  The parent owns queue revisions and encrypted persistence.
  This component only reports Edit and Steer intent.
  It also shows a nearby error when an action is rejected.
-->
<script lang="ts">
  import { text } from '@repo/ui';

  let {
    mode,
    busy = false,
    error = null,
    onEdit,
    onSteer,
  }: {
    mode: 'follow_up' | 'steer';
    busy?: boolean;
    error?: string | null;
    onEdit: () => void;
    onSteer: () => void | Promise<void>;
  } = $props();
</script>

<div class="queued-followup-controls" data-testid="queued-followup-controls" data-queue-mode={mode} aria-busy={busy}>
  <div class="queued-followup-actions">
    <span class="queued-followup-status" data-testid="queued-followup-status">
      <span class="queued-followup-dot" aria-hidden="true"></span>
      {busy ? $text('chats.queued_followup.updating') : mode === 'steer' ? $text('chats.queued_followup.steering') : $text('chats.queued_followup.queued')}
    </span>
    <button type="button" class="queued-followup-action" data-testid="queued-followup-edit" disabled={busy} onclick={onEdit}>
      {$text('chats.context_menu.edit')}
    </button>
    {#if mode === 'follow_up'}
      <button type="button" class="queued-followup-action" data-testid="queued-followup-steer" disabled={busy} onclick={() => { void onSteer(); }}>
        {$text('chats.queued_followup.steer_instead')}
      </button>
    {/if}
  </div>
  {#if error}
    <p class="queued-followup-error" data-testid="queued-followup-error" role="alert">{error}</p>
  {/if}
</div>

<style>
  .queued-followup-controls {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: var(--spacing-1, 4px);
    margin-top: var(--spacing-2, 8px);
    color: var(--color-font-secondary);
    font-size: var(--font-size-xs, 12px);
  }

  .queued-followup-actions {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    flex-wrap: wrap;
    gap: var(--spacing-2, 8px);
  }

  .queued-followup-status {
    display: inline-flex;
    align-items: center;
    gap: var(--spacing-1, 4px);
    font-weight: 600;
  }

  .queued-followup-dot {
    width: 6px;
    height: 6px;
    flex: none;
    border-radius: 50%;
    background: var(--color-button-primary);
  }

  .queued-followup-action {
    appearance: none;
    background: transparent;
    border: 0;
    border-radius: var(--border-radius-small, 4px);
    padding: 2px 4px;
    color: var(--color-button-primary);
    font: inherit;
    font-weight: 600;
    cursor: pointer;
  }

  .queued-followup-action:hover { text-decoration: underline; }
  .queued-followup-action:focus-visible { outline: 2px solid var(--color-button-primary); outline-offset: 2px; }
  .queued-followup-action:disabled { opacity: 0.5; cursor: default; text-decoration: none; }
  .queued-followup-error { margin: 0; color: var(--color-error); text-align: end; }
</style>
