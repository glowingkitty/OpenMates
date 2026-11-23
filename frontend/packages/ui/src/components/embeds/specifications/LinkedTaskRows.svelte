<!--
  LinkedTaskRows.svelte
  Plan Tasks with a "Working chat" button opening each Task's working sub-chat.
  Shared by the Specification and Check fullscreen views; props-driven.
-->
<script lang="ts">
  import { text } from '../../../i18n/translations';
  import OpenChatButton from './OpenChatButton.svelte';
  import type { SpecPlanTask } from './specPlanLinks';

  let { tasks, rowTestId, buttonTestId, onOpenChat }: {
    tasks: SpecPlanTask[];
    rowTestId: string;
    buttonTestId: string;
    onOpenChat: (chatId: string) => void;
  } = $props();
</script>

<ul class="linked-tasks">
  {#each tasks as task (task.taskId)}
    <li data-testid={rowTestId} data-status={task.status}>
      <span class="task-title">{task.title}</span>
      <span class="task-status">{$text(`plan_embeds.status.task.${task.status}`)}</span>
      {#if task.linkedSubChatId}
        {@const chatId = task.linkedSubChatId}
        <OpenChatButton testId={buttonTestId} label={$text('specifications.fullscreen.working_chat')} onclick={() => onOpenChat(chatId)} />
      {/if}
    </li>
  {/each}
</ul>

<style>
  .linked-tasks { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--spacing-3); }
  li { display: flex; flex-wrap: wrap; align-items: center; gap: var(--spacing-3) var(--spacing-6); }
  .task-title { color: var(--color-font-primary); font-weight: 600; }
  .task-status { color: var(--color-font-secondary); font-size: var(--font-size-xs); }
</style>
