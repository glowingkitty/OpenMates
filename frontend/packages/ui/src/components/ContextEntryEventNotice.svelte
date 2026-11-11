<!-- frontend/packages/ui/src/components/ContextEntryEventNotice.svelte
     Chat history system event written when the user saved a memory or workflow from a
     chat Recommendation: one line with the entry icon and title (full sentence as aria-label/title); the whole
     row opens the entry, or says "No longer exists" when it was deleted later. Rendered only in the owner's view
     (never in shared or public chats); the event is not sent to the AI.
     Plan: docs/plans/chat-recommendations/plan.yml (wire_contract.system_event)
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
  }
  let { event, checkExists, onOpenMemory }: Props = $props();
  let workflowHref = $derived(`/#workflow-id=${encodeURIComponent(event.entry_id)}&workflow-tab=details`);

  let exists = $state<boolean | null>(null);
  let label = $derived($text(`recommendations.${event.kind}_${event.action}`, { values: { title: event.title } }));

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
  data-action={event.action} data-entry-id={event.entry_id}>
  {#if exists === false}
    <span class="entry-row" title={label}>
      <span class="entry-icon" class:workflow={event.kind === 'workflow'} aria-hidden="true"></span>
      <span class="entry-label" data-testid="context-entry-event-label">{event.title}</span>
      <span class="entry-missing" data-testid="context-entry-event-missing">{$text('recommendations.entry_missing')}</span>
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
      <span class="entry-label" data-testid="context-entry-event-label">{event.title}</span>
    </button>
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
  .entry-missing { flex: none; font-style: italic; }
</style>
