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
  import { normalizeTaskResult, taskAssigneeLabel, taskStatusLabel } from './taskEmbedData';

  interface Props {
    data: EmbedFullscreenRawData;
    embedId?: string;
    onClose: () => void;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
  }

  let { data, embedId, onClose, hasPreviousEmbed = false, hasNextEmbed = false, onNavigatePrevious, onNavigateNext }: Props = $props();

  let snapshot = $derived(normalizeTaskResult(embedId || 'task', data.decodedContent ?? {}));
  let task = $state<UserTaskViewModel | null>(null);
  let liveLoadFailed = $state(false);
  let taskId = $derived(snapshot.task_id || snapshot.embed_id);
  let title = $derived(task?.title || snapshot.title || 'Untitled task');
  let description = $derived(task?.description || snapshot.description || '');
  let metadata = $derived(`${taskStatusLabel(task?.status || snapshot.status)} · ${taskAssigneeLabel(snapshot.assignee || task?.assigneeType)}`);

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
      {#if liveLoadFailed}
        <p class="snapshot-note">Snapshot preview. Open the Tasks workspace to edit this task.</p>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .task-detail-shell {
    width: min(860px, calc(100% - 32px));
    margin: 0 auto;
    padding: var(--spacing-12) 0 120px;
  }

  .snapshot-note {
    margin: var(--spacing-8) 0 0;
    color: var(--color-font-secondary);
    font-size: var(--font-size-small);
  }
</style>
