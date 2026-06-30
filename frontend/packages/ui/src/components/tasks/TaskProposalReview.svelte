<!--
  TaskProposalReview.svelte
  Review-only Tasks V1 proposal card. Assistant-produced plaintext proposals are
  transient until the user accepts them; accepted items are encrypted client-side
  by userTaskService before /v1/user-tasks persistence.
-->

<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import { notificationStore } from '../../stores/notificationStore';
  import {
    createUserTask,
    listUserTasks,
    updateUserTask,
    type UserTaskProposal,
    type UserTaskUpdateProposal,
  } from '../../services/userTaskService';

  let {
    chatId,
    proposals = [],
    updateProposals = [],
  }: {
    chatId: string;
    proposals?: UserTaskProposal[];
    updateProposals?: UserTaskUpdateProposal[];
  } = $props();

  const dispatch = createEventDispatcher<{ accepted: void; dismissed: void }>();
  let isSaving = $state(false);

  const hasProposals = $derived(proposals.length > 0 || updateProposals.length > 0);

  function broadcastTasksChanged(): void {
    if (typeof window === 'undefined') return;
    window.dispatchEvent(new CustomEvent('openmates-user-tasks-changed', { detail: { chatId } }));
  }

  async function acceptProposals(): Promise<void> {
    if (isSaving) return;
    isSaving = true;
    try {
      for (const proposal of proposals) {
        await createUserTask({
          title: proposal.title,
          description: proposal.description ?? '',
          status: proposal.status ?? 'todo',
          assigneeType: proposal.assignee_type ?? 'user',
          primaryChatId: chatId,
        });
      }

      if (updateProposals.length > 0) {
        const currentTasks = await listUserTasks({ chatId });
        for (const proposal of updateProposals) {
          const task = currentTasks.find((candidate) => candidate.task_id === proposal.task_id);
          if (!task) continue;
          await updateUserTask(task, {
            ...(proposal.title !== undefined ? { title: proposal.title ?? '' } : {}),
            ...(proposal.description !== undefined ? { description: proposal.description ?? '' } : {}),
            ...(proposal.status ? { status: proposal.status } : {}),
            ...(proposal.assignee_type ? { assigneeType: proposal.assignee_type } : {}),
          });
        }
      }

      broadcastTasksChanged();
      notificationStore.success('Task proposal saved');
      dispatch('accepted');
    } catch (error) {
      console.error('[TaskProposalReview] Failed to accept task proposal:', error);
      notificationStore.error('Failed to save task proposal');
    } finally {
      isSaving = false;
    }
  }

  function dismissProposals(): void {
    dispatch('dismissed');
  }
</script>

{#if hasProposals}
  <section class="task-proposal-review" data-testid="task-proposal-review" aria-label="Task proposals">
    <div class="proposal-copy">
      <p class="proposal-eyebrow">Suggested tasks</p>
      <h2>Save this work as tasks?</h2>
      <p>Review first. Accepted tasks are encrypted locally before they are saved.</p>
    </div>

    {#if proposals.length > 0}
      <div class="proposal-list" data-testid="task-proposal-list">
        {#each proposals as proposal}
          <article class="proposal-item" data-testid="task-proposal-item">
            <strong>{proposal.title}</strong>
            {#if proposal.description}
              <span>{proposal.description}</span>
            {/if}
          </article>
        {/each}
      </div>
    {/if}

    {#if updateProposals.length > 0}
      <div class="proposal-list" data-testid="task-update-proposal-list">
        {#each updateProposals as proposal}
          <article class="proposal-item" data-testid="task-update-proposal-item">
            <strong>Update task {proposal.task_id}</strong>
            <span>{proposal.title || proposal.description || proposal.status || proposal.assignee_type}</span>
          </article>
        {/each}
      </div>
    {/if}

    <div class="proposal-actions">
      <button type="button" class="secondary" onclick={dismissProposals} data-testid="task-proposal-dismiss">Dismiss</button>
      <button type="button" onclick={() => void acceptProposals()} disabled={isSaving} data-testid="task-proposal-accept">
        {isSaving ? 'Saving...' : 'Save tasks'}
      </button>
    </div>
  </section>
{/if}

<style>
  .task-proposal-review {
    width: min(1000px, calc(100% - 32px));
    margin: 0 auto 16px;
    padding: 18px;
    border-radius: 28px;
    border: 1px solid var(--color-grey-20);
    background: linear-gradient(135deg, var(--color-grey-10), var(--color-grey-0));
    box-shadow: 0 8px 28px rgba(0, 0, 0, 0.08);
    color: var(--color-font-primary);
  }

  .proposal-copy,
  .proposal-list,
  .proposal-actions {
    display: flex;
    gap: 10px;
  }

  .proposal-copy {
    flex-direction: column;
  }

  .proposal-eyebrow,
  h2,
  p {
    margin: 0;
  }

  .proposal-eyebrow {
    color: var(--color-font-secondary);
    font-size: 0.75rem;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
  }

  h2 {
    font-size: 1.15rem;
  }

  p,
  .proposal-item span {
    color: var(--color-font-secondary);
    font-size: 0.9rem;
  }

  .proposal-list {
    flex-direction: column;
    margin-top: 14px;
  }

  .proposal-item {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 12px;
    border-radius: 18px;
    background: var(--color-grey-0);
    border: 1px solid var(--color-grey-20);
  }

  .proposal-actions {
    justify-content: flex-end;
    flex-wrap: wrap;
    margin-top: 14px;
  }

  button {
    border: 0;
    border-radius: 999px;
    background: var(--color-button-primary);
    color: var(--color-font-button);
    padding: 9px 14px;
    font: inherit;
    font-weight: 700;
    cursor: pointer;
  }

  button.secondary {
    background: var(--color-grey-10);
    color: var(--color-font-primary);
  }

  button:disabled {
    cursor: wait;
    opacity: 0.7;
  }
</style>
