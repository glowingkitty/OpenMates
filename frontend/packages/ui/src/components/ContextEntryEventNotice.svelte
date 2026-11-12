<!-- frontend/packages/ui/src/components/ContextEntryEventNotice.svelte
     Chat history system event written when the user saved a memory or workflow from a
     chat Recommendation: one line with the entry icon and title (full sentence as aria-label/title); the whole
     row opens the entry, or says "No longer exists" when it was deleted later. When the assistant saved a
     memory itself (source: assistant, save_memory tool, no review step) the row reads "The assistant saved a
     memory: <title>" and an Undo button follows; Undo runs in the Rust core and leaves a persisted undone
     marker, so the undone state survives reload. Rendered only in the owner's view
     (never in shared or public chats); the event is not sent to the AI.
     Plans: docs/plans/chat-recommendations/plan.yml (wire_contract.system_event),
     docs/plans/assistant-memory-writes/plan.yml (TASK-3)
-->
<script lang="ts">
  import { text } from '../i18n/translations';
  import type { ContextEntryHistoryEvent } from '../types/recommendations';

  interface Props {
    event: ContextEntryHistoryEvent;
    /** Resolves whether the saved entry still exists. */
    checkExists: (event: ContextEntryHistoryEvent) => Promise<boolean>;
    /** Opens a saved memory in Settings > Memories (workflows open through their link). */
    onOpenMemory: (event: ContextEntryHistoryEvent) => void;
    /** True when a persisted undone marker exists for this assistant write. */
    undone: boolean;
    /** Undoes an assistant write; rejects with the core code (`rule_changed`, ...). */
    onUndo: (event: ContextEntryHistoryEvent) => Promise<void>;
  }
  let { event, checkExists, onOpenMemory, undone, onUndo }: Props = $props();
  let workflowHref = $derived(`/#workflow-id=${encodeURIComponent(event.entry_id)}&workflow-tab=details`);

  let exists = $state<boolean | null>(null);
  let byAssistant = $derived(event.source === 'assistant' && event.kind === 'memory');
  let label = $derived($text(
    byAssistant ? `recommendations.memory_${event.action}_by_assistant` : `recommendations.${event.kind}_${event.action}`,
    { values: { title: event.title } },
  ));
  /** Visible text: the title, or the full sentence when the assistant saved the memory without review. */
  let shown = $derived(byAssistant ? label : event.title);
  let undoing = $state(false);
  let undoneHere = $state(false);
  let undoError = $state<'changed' | 'failed' | null>(null);
  let isUndone = $derived(undone || undoneHere);
  let canUndo = $derived(byAssistant && !!event.undo && !isUndone && undoError !== 'changed' && exists !== false);

  async function undo() {
    if (undoing) return;
    undoing = true;
    undoError = null;
    try {
      await onUndo(event);
      undoneHere = true;
      // A deleted Memory is gone; a restored one still exists.
      if (event.undo?.action === 'create') exists = false;
    } catch (error) {
      const code = error instanceof Error ? error.message : '';
      console.warn('[ContextEntryEventNotice] Undo was refused', code);
      undoError = code === 'rule_changed' ? 'changed' : 'failed';
    } finally {
      undoing = false;
    }
  }

  $effect(() => {
    const current = event;
    let stale = false;
    exists = null;
    checkExists(current)
      .then((value) => { if (!stale) exists = value; })
      .catch((error) => {
        // Unknown is shown as available: opening reports the real state.
        console.warn('[ContextEntryEventNotice] Could not check the saved entry', error);
        if (!stale) exists = true;
      });
    return () => { stale = true; };
  });
</script>

<span class="context-entry-event" data-testid="context-entry-event" data-kind={event.kind}
  data-action={event.action} data-entry-id={event.entry_id} data-source={event.source ?? 'user'}
  data-undone={isUndone ? 'true' : 'false'}>
  {#if exists === false}
    <span class="entry-row" title={label}>
      <span class="entry-icon" class:workflow={event.kind === 'workflow'} aria-hidden="true"></span>
      <span class="entry-label" data-testid="context-entry-event-label">{shown}</span>
      {#if isUndone}
        <span class="entry-undone" data-testid="context-entry-event-undone">{$text('recommendations.memory_write_undone')}</span>
      {:else}
        <span class="entry-missing" data-testid="context-entry-event-missing">{$text('recommendations.entry_missing')}</span>
      {/if}
    </span>
  {:else if event.kind === 'workflow'}
    <a class="entry-row entry-open" data-testid="context-entry-event-open" href={workflowHref}
      aria-label={label} title={label}>
      <span class="entry-icon workflow" aria-hidden="true"></span>
      <span class="entry-label" data-testid="context-entry-event-label">{event.title}</span>
    </a>
  {:else}
    <button type="button" class="entry-row entry-open" data-testid="context-entry-event-open"
      disabled={exists === null} aria-label={label} title={label}
      onclick={() => onOpenMemory(event)}>
      <span class="entry-icon" aria-hidden="true"></span>
      <span class="entry-label" data-testid="context-entry-event-label">{shown}</span>
    </button>
    {#if isUndone}
      <span class="entry-undone" data-testid="context-entry-event-undone">{$text('recommendations.memory_write_undone')}</span>
    {/if}
  {/if}
  {#if canUndo}
    <button type="button" class="entry-open entry-undo" data-testid="context-entry-event-undo" disabled={undoing || exists === null}
      aria-busy={undoing} onclick={undo}>{$text('recommendations.undo_memory_write')}</button>
  {/if}
  {#if undoError}
    <span class="entry-undo-error" role="alert" data-testid="context-entry-event-undo-error" data-error={undoError}>
      {$text(undoError === 'changed' ? 'recommendations.memory_write_undo_changed' : 'recommendations.memory_write_undo_failed')}
    </span>
  {/if}
</span>

<style>
  .context-entry-event {
    display: flex;
    min-width: 0;
    max-width: 100%;
    color: var(--color-grey-60);
  }
  .entry-row {
    display: flex;
    align-items: center;
    gap: var(--spacing-2);
    min-width: 0;
    max-width: 100%;
  }
  .entry-icon {
    flex: none;
    width: 1rem;
    height: 1rem;
    background-color: var(--color-primary-start);
    -webkit-mask: url("@openmates/ui/static/icons/insight.svg") center / contain no-repeat;
    mask: url("@openmates/ui/static/icons/insight.svg") center / contain no-repeat;
  }
  .entry-icon.workflow {
    -webkit-mask-image: url("@openmates/ui/static/icons/workflow.svg");
    mask-image: url("@openmates/ui/static/icons/workflow.svg");
  }
  .entry-label {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .entry-open {
    padding: 0 !important;
    margin: 0 !important;
    min-width: 0 !important;
    height: auto !important;
    border: 0;
    background: transparent !important;
    filter: none !important;
    color: var(--color-primary);
    font: inherit;
    font-weight: 600;
    text-decoration: none;
    text-align: start;
    cursor: pointer;
  }
  .entry-open:hover .entry-label { text-decoration: underline; }
  .entry-open:disabled { opacity: 0.55; cursor: default; }
  .entry-open:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
  .entry-missing, .entry-undone { flex: none; font-style: italic; }
  .entry-undo { flex: none; margin-inline-start: var(--spacing-4) !important; text-decoration: underline; }
  .entry-undone { margin-inline-start: var(--spacing-4); }
  .context-entry-event { flex-wrap: wrap; align-items: center; }
  .entry-undo-error { flex-basis: 100%; color: var(--color-error); }
</style>
