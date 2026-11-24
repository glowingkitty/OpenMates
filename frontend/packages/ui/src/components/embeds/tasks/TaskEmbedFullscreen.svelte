<!--
  frontend/packages/ui/src/components/embeds/tasks/TaskEmbedFullscreen.svelte
  Child fullscreen for task result embeds.
  It tries the live task detail adapter for editable data, then falls back to
  the snapshot content used by preview pages and public example chats.
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import WorkspaceDetailHeader from '../../workspace/WorkspaceDetailHeader.svelte';
  import { taskDetailAdapter } from '../../workspace/detailMetadataAdapters';
  import type { UserTaskViewModel } from '../../../services/userTaskService';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import EmbedVersionTimeline from '../shared/EmbedVersionTimeline.svelte';
  import { commitEmbedContentRevision, isHeadPersisted } from '../../../services/embedDiffStore';
  import { updateUserTask } from '../../../services/userTaskService';
  import { text } from '../../../i18n/translations';
  import { formatTaskDueDate, normalizeTaskResult, taskAssigneeLabel, taskRestoreFromSource, taskStatusLabel } from './taskEmbedData';

  interface Props {
    data: EmbedFullscreenRawData;
    embedId?: string;
    onClose: () => void;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
    chatId?: string;
    projectId?: string;
    teamId?: string | null;
  }

  let { data, embedId, onClose, hasPreviousEmbed = false, hasNextEmbed = false, onNavigatePrevious, onNavigateNext, chatId, projectId, teamId }: Props = $props();

  let snapshot = $derived(normalizeTaskResult(embedId || 'task', data.decodedContent ?? {}));
  let task = $state<UserTaskViewModel | null>(null);
  let liveLoadFailed = $state(false);
  let taskId = $derived(snapshot.task_id || snapshot.embed_id);
  let title = $derived(task?.title || snapshot.title || 'Untitled task');
  let description = $derived(task?.description || snapshot.description || '');
  let dueLabel = $derived(formatTaskDueDate(snapshot.due_date));
  let metadata = $derived([
    taskStatusLabel(task?.status || snapshot.status),
    taskAssigneeLabel(snapshot.assignee || task?.assigneeType),
    dueLabel ? $text('embed_user_edits.task_due', { values: { date: dueLabel } }) : '',
  ].filter(Boolean).join(' · '));

  // Standalone assistant-authored task embeds carry the diff target `task_source`;
  // they get the shared version timeline with Undo.
  let dc = $derived((data.decodedContent ?? {}) as Record<string, unknown>);
  let taskSource = $derived(typeof dc.task_source === 'string' ? dc.task_source : '');
  let versionNumber = $derived(
    typeof dc.version_number === 'number' ? dc.version_number : (data.embedData?.version_number as number | undefined) ?? 1,
  );
  let validationErrors = $derived(snapshot.validation?.status === 'invalid' ? snapshot.validation.errors : []);

  /** Restore the Task fields through the existing encrypted update, then write the matching card version. */
  async function restoreTaskVersion(restoredContent: string, selectedVersion: number): Promise<{ version: number; content: string }> {
    if (!embedId || !taskId || taskId.startsWith('legacy-') || selectedVersion >= versionNumber) {
      throw new Error($text('embed_user_edits.task_restore_failed'));
    }
    try {
      const restore = taskRestoreFromSource(restoredContent);
      if (!restore) throw new Error('Invalid saved Task source.');
      const currentTask = await taskDetailAdapter.load(taskId);
      const { patch } = restore;
      const alreadyRestored = currentTask.title === patch.title &&
        (currentTask.description ?? '') === patch.description && currentTask.status === patch.status &&
        currentTask.assigneeType === patch.assigneeType && currentTask.dueAt === patch.dueAt;
      const restoredTask = alreadyRestored ? currentTask : await updateUserTask(currentTask, patch);
      task = restoredTask;
      const restored = await commitEmbedContentRevision(embedId, restoredContent, {
        currentVersion: versionNumber,
        currentContent: taskSource,
        chatId,
        projectId,
        teamId,
        buildRestoredContent: (content, newVersion) => ({
          ...dc,
          ...restore.fields,
          task_source: content,
          task_version: restoredTask.version,
          version_number: newVersion,
          validation: { status: 'valid', errors: [], warnings: [] },
        }),
      });
      if (!isHeadPersisted(restored.head)) throw new Error('Restored task card was not saved.');
      return { version: restored.version_number, content: restoredContent };
    } catch (error) {
      console.warn('[TaskEmbedFullscreen] Restore failed:', error);
      throw new Error($text('embed_user_edits.task_restore_failed'));
    }
  }

  onMount(() => {
    if (!taskId || taskId.startsWith('legacy-')) return;
    void taskDetailAdapter.load(taskId).then((loaded) => {
      task = loaded;
    }).catch((error) => {
      liveLoadFailed = true;
      console.debug('[TaskEmbedFullscreen] Live task load unavailable, using snapshot:', error);
    });
  });

  async function saveTitle(value: string): Promise<void> {
    if (!task) throw new Error('Task is not available for editing.');
    task = await taskDetailAdapter.saveTitle(task, value);
  }

  async function saveDescription(value: string): Promise<void> {
    if (!task) throw new Error('Task is not available for editing.');
    task = await taskDetailAdapter.saveDescription(task, value);
  }
</script>

<UnifiedEmbedFullscreen
  testId="task-embed-fullscreen"
  appId="tasks"
  skillId="task"
  skillIconName="task"
  embedHeaderTitle={title}
  embedHeaderSubtitle={metadata}
  showSkillIcon={true}
  {onClose}
  currentEmbedId={embedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
>
  {#snippet content()}
    <div class="task-detail-shell" data-testid="task-embed-fullscreen-content">
      <WorkspaceDetailHeader
        {title}
        {description}
        {metadata}
        category="productivity"
        icon="task"
        writable={!!task}
        embedded={true}
        alignment="start"
        titleTestId="task-embed-title"
        descriptionTestId="task-embed-description"
        onSaveTitle={saveTitle}
        onSaveDescription={saveDescription}
      />
      {#if validationErrors.length}
        <ul class="validation-errors" data-testid="task-embed-validation-errors">
          {#each validationErrors as error}<li data-testid="task-embed-validation-error">{error}</li>{/each}
        </ul>
      {/if}
      {#if liveLoadFailed}
        <p class="snapshot-note">Snapshot preview. Open the Tasks workspace to edit this task.</p>
      {/if}
    </div>
    {#if embedId && taskSource && versionNumber > 1}
      <EmbedVersionTimeline
        {embedId}
        {chatId}
        {projectId}
        {teamId}
        currentVersion={versionNumber}
        currentContent={taskSource}
        onVersionSelect={() => {}}
        onRestoreVersion={restoreTaskVersion}
      />
    {/if}
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .task-detail-shell {
    width: min(860px, calc(100% - 32px));
    margin: 0 auto;
    padding: var(--spacing-12) 0 120px;
  }

  .validation-errors {
    margin: var(--spacing-8) 0 0;
    color: var(--color-error);
    font-size: var(--font-size-small);
  }

  .snapshot-note {
    margin: var(--spacing-8) 0 0;
    color: var(--color-font-secondary);
    font-size: var(--font-size-small);
  }
</style>
