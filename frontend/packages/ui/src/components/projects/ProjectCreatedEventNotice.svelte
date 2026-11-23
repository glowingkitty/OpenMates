<!-- frontend/packages/ui/src/components/projects/ProjectCreatedEventNotice.svelte
     Chat-history system event "Created <name> project · Undo" for a Project the assistant created
     on its own. The name is a link that opens the Project; Undo is a text link styled like the
     assistant-memory Undo (ContextEntryEventNotice). Pure presentation: ProjectCreatedEvent.svelte
     runs the undo in the client core. After the undo the row reads "Project removed".
     Spec: projects.creation.assistant-inferred -->
<script lang="ts">
  import { text } from '../../i18n/translations';
  import SystemMessageNotice from '../SystemMessageNotice.svelte';

  let { projectName, undone = false, undoing = false, failed = false, onOpen, onUndo }: {
    projectName: string;
    undone?: boolean;
    undoing?: boolean;
    failed?: boolean;
    onOpen: () => void;
    onUndo?: () => void;
  } = $props();

  // The translated sentence places the name; split around a sentinel so the name can be a link.
  const NAME = '\u0001';
  let parts = $derived($text('projects.created_project_event', { values: { name: NAME } }).split(NAME));
</script>

<div class="project-created-event" data-testid="project-created-event" data-state={undone ? 'undone' : 'created'}>
  <SystemMessageNotice>
    {#if undone}
      <span data-testid="project-created-status">{$text('projects.created_project_undone')}</span>
    {:else}
      <span>{parts[0]}<button type="button" class="event-link" data-testid="project-created-name" onclick={onOpen}>{projectName}</button>{parts[1] ?? ''}</span>
      {#if onUndo}
        <button type="button" class="event-link undo" data-testid="project-created-undo" disabled={undoing}
          aria-busy={undoing} onclick={onUndo}>{$text('projects.created_project_undo')}</button>
      {/if}
    {/if}
    {#if failed}
      <span class="undo-error" role="alert" data-testid="project-created-undo-error">{$text('projects.created_project_undo_failed')}</span>
    {/if}
  </SystemMessageNotice>
</div>

<style>
  .project-created-event { display: flex; justify-content: center; width: 100%; }
  .event-link {
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
    cursor: pointer;
  }
  .event-link:hover { text-decoration: underline; }
  .event-link:disabled { opacity: 0.55; cursor: default; }
  .event-link:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
  .undo { margin-inline-start: var(--spacing-4) !important; text-decoration: underline; }
  .undo-error { display: block; color: var(--color-error); }
</style>
