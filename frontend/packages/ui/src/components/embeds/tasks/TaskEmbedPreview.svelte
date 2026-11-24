<!--
  frontend/packages/ui/src/components/embeds/tasks/TaskEmbedPreview.svelte
  Snapshot child card for a task embed.
  The preview stays lightweight and does not load encrypted task detail data.
  Fullscreen handles live workspace loading and editing when possible.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '../../../i18n/translations';
  import { formatTaskDueDate, taskAssigneeLabel, taskStatusLabel, taskVisibleId, type TaskEmbedValidation } from './taskEmbedData';

  interface Props {
    id: string;
    taskId?: string;
    shortId?: string;
    title?: string;
    description?: string;
    status?: string;
    assignee?: string;
    dueDate?: string;
    projectName?: string;
    validation?: TaskEmbedValidation;
    isMobile?: boolean;
    onFullscreen: () => void;
  }

  let {
    id,
    shortId = '',
    title = '',
    description = '',
    status = 'todo',
    assignee = '',
    dueDate = '',
    projectName = '',
    validation,
    isMobile = false,
    onFullscreen,
  }: Props = $props();

  let displayTitle = $derived(title || 'Untitled task');
  let displayId = $derived(taskVisibleId(shortId));
  let dueLabel = $derived(formatTaskDueDate(dueDate));
  let errors = $derived(validation?.status === 'invalid' ? validation.errors : []);
  let invalid = $derived(validation?.status === 'invalid');

  function handleStop() {
    // Task child cards are not cancellable.
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="tasks"
  skillId="task"
  skillIconName="task"
  status="finished"
  skillName="Task"
  {isMobile}
  {onFullscreen}
  onStop={handleStop}
  showStatus={false}
  showSkillIcon={false}
>
  {#snippet details()}
    <article class="task-card" class:invalid data-testid="task-embed-card">
      <div class="card-body">
        <!-- A task that was never created has no id to show. -->
        {#if !invalid && (displayId || projectName)}<div class="kicker">{displayId || projectName}</div>{/if}
        <h3 data-testid="task-embed-title">{displayTitle}</h3>
        {#if invalid}
          <div class="errors" data-testid="task-embed-validation-errors">
            <strong>{$text('embed_user_edits.task_not_created')}</strong>
            <ul>
              {#each errors as error}<li data-testid="task-embed-validation-error">{error}</li>{/each}
            </ul>
          </div>
        {:else}
          {#if description}<p>{description}</p>{/if}
          <div class="meta-row">
            {#if dueLabel}<span data-testid="task-embed-due-date">{$text('embed_user_edits.task_due', { values: { date: dueLabel } })}</span>{/if}
            <span data-testid="task-embed-status">{taskStatusLabel(status)}</span>
            <span data-testid="task-embed-pill">{taskAssigneeLabel(assignee)}</span>
          </div>
        {/if}
      </div>
    </article>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  /* Text only: the task icon lives in the embed's top-left corner. The body starts
     where the header text starts (BasicInfosBar .result-identity-header, 54px from the
     card edge); the details section already adds 20px, so the card adds 34px. */
  .task-card {
    display: flex;
    box-sizing: border-box;
    width: 100%;
    height: 100%;
    padding: var(--spacing-2) var(--spacing-6) var(--spacing-6) 34px;
  }

  .card-body {
    display: flex;
    min-width: 0;
    flex: 1 1 0;
    flex-direction: column;
    justify-content: flex-start;
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
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    flex-shrink: 0;
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

  .invalid {
    padding-block: 0;
  }

  .invalid .card-body {
    gap: var(--spacing-1);
  }

  .errors {
    min-height: 0;
    overflow-y: auto;
    color: var(--color-error);
    font-size: var(--font-size-xs);
    line-height: 1.25;
  }

  .errors ul {
    margin: 0;
    padding-inline-start: 1rem;
  }

  .errors li {
    overflow-wrap: anywhere;
  }

  .meta-row {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .meta-row span {
    padding: 2px 7px;
    border-radius: var(--radius-full);
    background: var(--color-grey-10);
  }
</style>
