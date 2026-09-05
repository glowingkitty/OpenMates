<!--
  TasksPage.svelte
  Central Tasks V1 workspace. Loads encrypted user tasks, decrypts them on the
  client, and renders a reusable Kanban board for all task statuses.
-->

<script lang="ts">
  import { onMount, tick } from 'svelte';
  import DailyInspirationBanner from '../DailyInspirationBanner.svelte';
  import TaskBoard from './TaskBoard.svelte';
  import TaskDetailFullscreen from './TaskDetailFullscreen.svelte';
  import WorkflowRunTaskDetail from './WorkflowRunTaskDetail.svelte';
  import WorkspaceHomeShell from '../workspace/WorkspaceHomeShell.svelte';
  import WorkspacePromptComposer from '../workspace/WorkspacePromptComposer.svelte';
  import { loadDefaultInspirations } from '../../demo_chats/loadDefaultInspirations';
  import { featureAvailabilityStore, initializeFeatureAvailability } from '../../stores/appSkillsStore';
  import type { DailyInspiration } from '../../stores/dailyInspirationStore';
  import { notificationStore } from '../../stores/notificationStore';
  import { userProfile } from '../../stores/userProfile';
  import {
    blockUserTask,
    completeUserTask,
    createUserTask,
    deleteUserTask,
    cancelWorkflowRunTaskProjection,
    extractUserTaskProposals,
    isWorkflowRunTaskProjectionViewModel,
    listTaskBoardItems,
    reorderUserTasks,
    skipUserTask,
    startUserTaskWithAI,
    unblockUserTask,
    updateUserTask,
    type ListUserTasksFilters,
    type UserTaskProposal,
    type UserTaskStatus,
    type UserTaskViewModel,
    type TasksBoardItem,
    type WorkflowRunTaskProjectionViewModel,
  } from '../../services/userTaskService';
  import {
    activateUserPlan,
    completeUserPlan,
    createUserPlan,
    listUserPlans,
    type UserPlanViewModel,
  } from '../../services/userPlanService';

  let {
    projectId = null,
    chatId = null,
    compact = false,
    focus = 'tasks',
  }: {
    projectId?: string | null;
    chatId?: string | null;
    compact?: boolean;
    focus?: 'tasks' | 'plans';
  } = $props();

  let tasks = $state<TasksBoardItem[]>([]);
  let plans = $state<UserPlanViewModel[]>([]);
  let isLoading = $state(true);
  let isLoadingPlans = $state(true);
  let isSaving = $state(false);
  let planActionId = $state<string | null>(null);
  let hasLoadError = $state(false);
  let title = $state('');
  let description = $state('');
  let planTitle = $state('');
  let planSummary = $state('');
  let assignToAI = $state(false);
  let transcriptText = $state('');
  let correctedTranscriptText = $state('');
  let taskPromptValue = $state('');
  let pendingTaskDelete = $state<{ task: TasksBoardItem; request: string } | null>(null);
  let isExtracting = $state(false);
  let extractedProposals = $state<UserTaskProposal[]>([]);
  let tasksPageWidth = $state(900);
  let searchTerm = $state('');
  let showTaskSearch = $state(false);
  let showDesktopTaskTags = $state(true);
  let showMobileTaskTags = $state(false);
  let selectedWorkflowRunProjection = $state<WorkflowRunTaskProjectionViewModel | null>(null);
  let selectedTask = $state<UserTaskViewModel | null>(null);
  let taskBoardPanel: HTMLElement | null = $state(null);
  let featureAvailabilityReady = $derived($featureAvailabilityStore.initialized && $featureAvailabilityStore.disabledById !== null);
  let tasksEnabled = $derived(featureAvailabilityReady && $featureAvailabilityStore.disabledById?.['platform:tasks'] !== true);
  let plansEnabled = $derived(featureAvailabilityReady && $featureAvailabilityStore.disabledById?.['platform:plans'] !== true);
  let isCentralTasksWorkspace = $derived(!compact && focus === 'tasks');
  let isNarrowTasksWorkspace = $derived(tasksPageWidth <= 900);

  const totalCount = $derived(tasks.length);
  const activeCount = $derived(tasks.filter((task) => task.status === 'in_progress').length);
  const doneCount = $derived(tasks.filter((task) => task.status === 'done').length);
  const activePlans = $derived(plans.filter((plan) => !['completed', 'archived'].includes(plan.status)));
  const completedPlanCount = $derived(plans.filter((plan) => plan.status === 'completed').length);
  const greetingName = $derived(formatGreetingName($userProfile.username));
  const taskFilterChips = $derived(resolveTaskFilterChips(tasks));
  const visibleTasks = $derived(filterTasks(tasks, searchTerm));

  function formatGreetingName(username: string): string {
    const trimmed = username.trim();
    if (!trimmed) return 'there';
    return trimmed.split(/\s+/)[0];
  }

  function resolveTaskFilterChips(items: TasksBoardItem[]): string[] {
    const tags = Array.from(new Set(items.flatMap((task) => task.tags))).filter(Boolean).slice(0, 3);
    return tags.length > 0 ? tags : ['my-tasks', 'software', 'hardware'];
  }

  function filterTasks(items: TasksBoardItem[], query: string): TasksBoardItem[] {
    const normalized = query.trim().replace(/^#/, '').toLowerCase();
    if (!normalized) return items;
    return items.filter((task) => [
      task.title,
      task.description,
      task.assigneeType,
      ...task.tags,
    ].some((value) => value.toLowerCase().includes(normalized)));
  }

  function findTaskMention(request: string): TasksBoardItem | null {
    const normalized = request.toLowerCase();
    const matches = tasks
      .filter((task) => !isWorkflowRunTaskProjectionViewModel(task) && task.title.trim())
      .filter((task) => normalized.includes(task.title.toLowerCase()))
      .sort((a, b) => b.title.length - a.title.length);
    return matches[0] ?? null;
  }

  async function revealTaskBoardPanel(): Promise<void> {
    if (!isCentralTasksWorkspace || !taskBoardPanel) return;
    await tick();
    taskBoardPanel?.scrollIntoView({ block: isNarrowTasksWorkspace ? 'start' : 'center', inline: 'nearest', behavior: 'auto' });
  }

  function handleSelectTask(task: TasksBoardItem): void {
    if (isWorkflowRunTaskProjectionViewModel(task) && task.workflowRunId) {
      selectedWorkflowRunProjection = task;
      void revealTaskBoardPanel();
      return;
    }
    if (!isWorkflowRunTaskProjectionViewModel(task)) selectedTask = task;
  }

  function parseTaskStatus(request: string): UserTaskStatus | null {
    const normalized = request.toLowerCase();
    if (/\b(done|complete|completed)\b/.test(normalized)) return 'done';
    if (/\b(block|blocked)\b/.test(normalized)) return 'blocked';
    if (/\b(in progress|start|started|working)\b/.test(normalized)) return 'in_progress';
    if (/\b(to do|todo|ready)\b/.test(normalized)) return 'todo';
    if (/\b(backlog|skip|later)\b/.test(normalized)) return 'backlog';
    return null;
  }

  function looksLikeTaskManagementRequest(request: string): boolean {
    return /\b(rename|retitle|edit|update|move|mark|delete|remove|complete|block|start|skip)\b/i.test(request);
  }

  function parseRenameTitle(request: string): string | null {
    if (!/\b(rename|retitle)\b/i.test(request)) return null;
    const index = request.toLowerCase().lastIndexOf(' to ');
    if (index === -1) return null;
    return request.slice(index + 4).trim() || null;
  }

  function parseDescriptionUpdate(request: string): string | null {
    const match = request.match(/\b(?:description|details)\s+(?:to|as)\s+(.+)$/i);
    return match?.[1]?.trim() || null;
  }

  function filters(): ListUserTasksFilters {
    return {
      projectId: projectId ?? undefined,
      chatId: chatId ?? undefined,
    };
  }

  function broadcastTasksChanged(): void {
    if (typeof window === 'undefined') return;
    window.dispatchEvent(new CustomEvent('openmates-user-tasks-changed', {
      detail: { chatId, projectId },
    }));
  }

  function broadcastPlansChanged(): void {
    if (typeof window === 'undefined') return;
    window.dispatchEvent(new CustomEvent('openmates-user-plans-changed', {
      detail: { chatId, projectId },
    }));
  }

  async function refreshTasks(): Promise<void> {
    if (!tasksEnabled) {
      tasks = [];
      isLoading = false;
      return;
    }
    isLoading = true;
    try {
      hasLoadError = false;
      tasks = await listTaskBoardItems(filters());
    } catch (error) {
      hasLoadError = true;
      console.error('[TasksPage] Failed to load tasks:', error);
      notificationStore.error('Failed to load tasks');
    } finally {
      isLoading = false;
    }
  }

  async function refreshPlans(): Promise<void> {
    if (!plansEnabled) {
      plans = [];
      isLoadingPlans = false;
      return;
    }
    isLoadingPlans = true;
    try {
      plans = await listUserPlans({
        projectId: projectId ?? undefined,
        chatId: chatId ?? undefined,
        limit: compact ? 5 : 12,
      });
    } catch (error) {
      console.error('[TasksPage] Failed to load plans:', error);
    } finally {
      isLoadingPlans = false;
    }
  }

  async function handleCreateTask(): Promise<void> {
    const trimmedTitle = title.trim();
    if (!trimmedTitle || isSaving) return;
    isSaving = true;
    try {
      const assignedToAI = assignToAI;
      const task = await createUserTask({
        title: trimmedTitle,
        description: description.trim(),
        assigneeType: assignedToAI ? 'openmates' : 'user',
        assigneeIdentity: assignedToAI ? 'openmates' : null,
        primaryChatId: chatId,
        linkedProjectIds: projectId ? [projectId] : [],
      });
      tasks = [task, ...tasks];
      broadcastTasksChanged();
      title = '';
      description = '';
      assignToAI = false;
      notificationStore.success(assignedToAI ? 'AI task started' : 'Task created');
    } catch (error) {
      console.error('[TasksPage] Failed to create task:', error);
      notificationStore.error('Failed to create task');
    } finally {
      isSaving = false;
    }
  }

  async function handleTaskPromptSubmit(value: string): Promise<void> {
    if (!tasksEnabled || isSaving) return;
    const mentionedTask = findTaskMention(value);
    const normalized = value.toLowerCase();
    if (/\b(delete|remove)\b/.test(normalized)) {
      if (!mentionedTask) {
        notificationStore.error('Name the task to delete first.');
        return;
      }
      pendingTaskDelete = { task: mentionedTask, request: value };
      taskPromptValue = '';
      return;
    }

    if (mentionedTask && !isWorkflowRunTaskProjectionViewModel(mentionedTask)) {
      const renamedTitle = parseRenameTitle(value);
      const description = parseDescriptionUpdate(value);
      const targetStatus = parseTaskStatus(value);
      if (renamedTitle) {
        await updateTaskFromPrompt(mentionedTask, { title: renamedTitle }, 'Task renamed');
        taskPromptValue = '';
        return;
      }
      if (description) {
        await updateTaskFromPrompt(mentionedTask, { description }, 'Task details updated');
        taskPromptValue = '';
        return;
      }
      if (targetStatus) {
        await handleMove(mentionedTask, targetStatus);
        taskPromptValue = '';
        return;
      }
    }

    if (looksLikeTaskManagementRequest(value)) {
      notificationStore.error('I could not find a matching task. Include the exact task title.');
      return;
    }

    await createTaskFromPrompt(value);
    taskPromptValue = '';
  }

  async function createTaskFromPrompt(value: string): Promise<void> {
    isSaving = true;
    try {
      const assignedToAI = /\b(ai|mate)\b/i.test(value) && /\b(assign|start)\b/i.test(value);
      const task = await createUserTask({
        title: value,
        description: value.split(/\s+/).length > 10 ? value : '',
        assigneeType: assignedToAI ? 'openmates' : 'user',
        assigneeIdentity: assignedToAI ? 'openmates' : null,
        primaryChatId: chatId,
        linkedProjectIds: projectId ? [projectId] : [],
      });
      tasks = [task, ...tasks];
      broadcastTasksChanged();
      notificationStore.success(assignedToAI ? 'AI task started' : 'Task created');
    } catch (error) {
      console.error('[TasksPage] Failed to create task from prompt:', error);
      notificationStore.error('Failed to create task');
    } finally {
      isSaving = false;
    }
  }

  async function updateTaskFromPrompt(task: UserTaskViewModel, patch: Parameters<typeof updateUserTask>[1], successMessage: string): Promise<void> {
    try {
      const updated = await updateUserTask(task, patch);
      tasks = tasks.map((candidate) => candidate.task_id === updated.task_id ? updated : candidate);
      broadcastTasksChanged();
      notificationStore.success(successMessage);
    } catch (error) {
      console.error('[TasksPage] Failed to update task from prompt:', error);
      notificationStore.error('Failed to update task');
    }
  }

  async function confirmTaskDelete(): Promise<void> {
    if (!pendingTaskDelete) return;
    const task = pendingTaskDelete.task;
    pendingTaskDelete = null;
    await handleDelete(task);
  }

  function handleStartTaskInspiration(inspiration: DailyInspiration): void {
    taskPromptValue = inspiration.phrase;
    title = inspiration.phrase;
    description = inspiration.assistant_response ?? '';
  }

  async function handleExtractTasks(): Promise<void> {
    const correctedText = (correctedTranscriptText || transcriptText).trim();
    if (!correctedText || isExtracting) return;
    isExtracting = true;
    try {
      extractedProposals = await extractUserTaskProposals({
        correctedText,
        contextChatId: chatId,
        projectIds: projectId ? [projectId] : [],
      });
      if (extractedProposals.length === 0) {
        notificationStore.error('No task proposals found');
      }
    } catch (error) {
      console.error('[TasksPage] Failed to extract task proposals:', error);
      notificationStore.error('Failed to extract task proposals');
    } finally {
      isExtracting = false;
    }
  }

  async function handleAcceptProposal(proposal: UserTaskProposal): Promise<void> {
    if (isSaving) return;
    isSaving = true;
    try {
      const task = await createUserTask({
        title: proposal.title,
        description: proposal.description ?? '',
        status: proposal.status ?? 'todo',
        assigneeType: proposal.assignee_type ?? 'user',
        primaryChatId: chatId,
        linkedProjectIds: projectId ? [projectId] : [],
      });
      tasks = [task, ...tasks];
      extractedProposals = extractedProposals.filter((candidate) => candidate !== proposal);
      broadcastTasksChanged();
      notificationStore.success('Task created from transcript');
    } catch (error) {
      console.error('[TasksPage] Failed to accept task proposal:', error);
      notificationStore.error('Failed to create task from proposal');
    } finally {
      isSaving = false;
    }
  }

  function handleDismissProposal(proposal: UserTaskProposal): void {
    extractedProposals = extractedProposals.filter((candidate) => candidate !== proposal);
  }

  async function handleCreatePlan(): Promise<void> {
    if (!plansEnabled) return;
    const trimmedTitle = planTitle.trim();
    if (!trimmedTitle || isSaving) return;
    isSaving = true;
    try {
      const plan = await createUserPlan({
        title: trimmedTitle,
        summary: planSummary.trim(),
        status: 'draft',
        primaryChatId: chatId,
        linkedProjectIds: projectId ? [projectId] : [],
      });
      plans = [plan, ...plans];
      broadcastPlansChanged();
      planTitle = '';
      planSummary = '';
      notificationStore.success('Plan created');
    } catch (error) {
      console.error('[TasksPage] Failed to create plan:', error);
      notificationStore.error('Failed to create plan');
    } finally {
      isSaving = false;
    }
  }

  async function handleMove(task: TasksBoardItem, status: UserTaskStatus): Promise<void> {
    if (isWorkflowRunTaskProjectionViewModel(task)) return;
    const previous = tasks;
    tasks = tasks.map((candidate) => candidate.task_id === task.task_id ? { ...candidate, status } : candidate);
    try {
      let updated: UserTaskViewModel;
      if (status === 'done' && task.status !== 'done') {
        updated = await completeUserTask(task);
      } else if (status === 'blocked' && task.status !== 'blocked') {
        updated = await blockUserTask(task);
      } else if (task.status === 'blocked' && status !== 'blocked') {
        updated = await unblockUserTask(task);
        if (status !== 'todo') {
          const [moved] = await reorderUserTasks([{ task: updated, status }]);
          if (!moved) throw new Error('Task reorder returned no task');
          updated = moved;
        }
      } else if (status === 'backlog' && task.status !== 'backlog') {
        updated = await skipUserTask(task);
      } else {
        const [moved] = await reorderUserTasks([{ task, status }]);
        if (!moved) throw new Error('Task reorder returned no task');
        updated = moved;
      }
      tasks = tasks.map((candidate) => candidate.task_id === updated.task_id ? updated : candidate);
      broadcastTasksChanged();
    } catch (error) {
      tasks = previous;
      console.error('[TasksPage] Failed to update task:', error);
      notificationStore.error('Failed to update task');
    }
  }

  async function handleSkip(task: TasksBoardItem): Promise<void> {
    if (isWorkflowRunTaskProjectionViewModel(task)) return;
    const previous = tasks;
    tasks = tasks.map((candidate) => candidate.task_id === task.task_id ? { ...candidate, status: 'backlog' } : candidate);
    try {
      const updated = await skipUserTask(task);
      tasks = tasks.map((candidate) => candidate.task_id === updated.task_id ? updated : candidate);
      broadcastTasksChanged();
    } catch (error) {
      tasks = previous;
      console.error('[TasksPage] Failed to skip task:', error);
      notificationStore.error('Failed to skip task');
    }
  }

  async function handleDelete(task: TasksBoardItem): Promise<void> {
    if (isWorkflowRunTaskProjectionViewModel(task) && !task.canDelete) return;
    const previous = tasks;
    tasks = tasks.filter((candidate) => candidate.task_id !== task.task_id);
    try {
      await deleteUserTask(task);
      broadcastTasksChanged();
      notificationStore.success(isWorkflowRunTaskProjectionViewModel(task) ? 'Next workflow run skipped' : 'Task deleted');
    } catch (error) {
      tasks = previous;
      console.error('[TasksPage] Failed to delete task:', error);
      notificationStore.error('Failed to delete task');
    }
  }

  async function handleStartAI(task: TasksBoardItem): Promise<void> {
    if (isWorkflowRunTaskProjectionViewModel(task)) return;
    try {
      const updated = await startUserTaskWithAI(task);
      tasks = tasks.map((candidate) => candidate.task_id === updated.task_id ? updated : candidate);
      broadcastTasksChanged();
      notificationStore.success('AI task queued');
    } catch (error) {
      console.error('[TasksPage] Failed to start AI task:', error);
      notificationStore.error('Failed to start AI task');
    }
  }

  async function handleCancelWorkflowRun(task: TasksBoardItem): Promise<void> {
    if (!isWorkflowRunTaskProjectionViewModel(task)) return;
    try {
      await cancelWorkflowRunTaskProjection(task);
      await refreshTasks();
      notificationStore.success('Workflow run cancellation requested');
    } catch (error) {
      console.error('[TasksPage] Failed to cancel workflow run:', error);
      notificationStore.error('Failed to cancel workflow run');
    }
  }

  async function handleActivatePlan(plan: UserPlanViewModel): Promise<void> {
    if (!plansEnabled) return;
    planActionId = plan.plan_id;
    try {
      const updated = await activateUserPlan(plan);
      plans = plans.map((candidate) => candidate.plan_id === updated.plan_id ? updated : candidate);
      broadcastPlansChanged();
      notificationStore.success('Plan activated');
    } catch (error) {
      console.error('[TasksPage] Failed to activate plan:', error);
      notificationStore.error('Failed to activate plan');
    } finally {
      planActionId = null;
    }
  }

  async function handleCompletePlan(plan: UserPlanViewModel): Promise<void> {
    if (!plansEnabled) return;
    planActionId = plan.plan_id;
    try {
      const updated = await completeUserPlan(plan);
      plans = plans.map((candidate) => candidate.plan_id === updated.plan_id ? updated : candidate);
      broadcastPlansChanged();
      notificationStore.success('Plan completed');
    } catch (error) {
      console.error('[TasksPage] Failed to complete plan:', error);
      notificationStore.error('Plan still has blockers');
    } finally {
      planActionId = null;
    }
  }

  onMount(() => {
    void initializeFeatureAvailability();
    if (!isCentralTasksWorkspace) {
      void loadDefaultInspirations({ surface: 'tasks', allowIndexedDB: false });
    }
  });

  $effect(() => {
    void projectId;
    void chatId;
    void tasksEnabled;
    void plansEnabled;
    if (!$featureAvailabilityStore.initialized) return;
    void refreshTasks();
    void refreshPlans();
  });
</script>

{#if !tasksEnabled && !plansEnabled}
  <section class="tasks-page" class:compact data-testid="tasks-feature-disabled">
    <div class="tasks-state">
      <h2>{focus === 'plans' ? 'Plans unavailable' : 'Tasks unavailable'}</h2>
      <p>{focus === 'plans' ? 'Plans are disabled on this server.' : 'Tasks are disabled on this server.'}</p>
    </div>
  </section>
{:else}
<section class="tasks-page" class:compact class:figma-layout={isCentralTasksWorkspace} data-testid={compact ? 'project-tasks-page' : focus === 'plans' ? 'plans-page' : 'tasks-page'} bind:clientWidth={tasksPageWidth}>
  {#if !compact && !isCentralTasksWorkspace}
    <div class="daily-inspiration-area tasks-daily-inspiration-area" data-testid="tasks-daily-inspiration-area">
      <DailyInspirationBanner
        surface="tasks"
        onStartChat={handleStartTaskInspiration}
        containerWidth={Math.min(tasksPageWidth || 900, 1320)}
      />
    </div>

    <header class="tasks-hero">
      <div>
        <p class="eyebrow">{focus === 'plans' ? 'Plans' : 'Tasks'}</p>
        <h1>{focus === 'plans' ? 'Coordinate complex work with structured plans.' : 'Manage tasks for you and your AI mates.'}</h1>
        <p>{focus === 'plans' ? 'Create private encrypted plans, keep active work aligned, and connect verification tasks when execution starts.' : 'Create private encrypted tasks, move them through a Kanban flow, and hand focused work to AI when it is ready.'}</p>
      </div>
      <div class="task-stats" aria-label="Task summary">
        {#if focus === 'plans'}
          <span><strong>{plans.length}</strong> total</span>
          <span><strong>{activePlans.length}</strong> active</span>
          <span><strong>{completedPlanCount}</strong> done</span>
        {:else}
          <span><strong>{totalCount}</strong> total</span>
          <span><strong>{activeCount}</strong> active</span>
          <span><strong>{doneCount}</strong> done</span>
        {/if}
      </div>
    </header>
  {/if}

  {#if isCentralTasksWorkspace}
    <section class="tasks-figma-workspace" data-testid="tasks-figma-workspace" aria-label="Tasks workspace">
      <WorkspaceHomeShell
          surface="tasks"
          testId="tasks-workspace-home"
          centerTestId="task-greeting"
          contentSlotVisible
          contentSlotTestId="tasks-board-scroll-content"
          heading={`Hey ${greetingName}!`}
          subtitle="What task is next?"
          showReportIssue
          onStartInspiration={handleStartTaskInspiration}
        >
      <section class="task-board-panel" data-testid="tasks-board-workspace" aria-label="Tasks board" bind:this={taskBoardPanel}>
        <div class="task-workspace-toolbar">
          <div class="task-search-cluster" aria-label="Task search and filters">
            <div class="task-search-stack">
              {#if !isNarrowTasksWorkspace}
                {#if showTaskSearch}
                  <label class="task-search-field" for="task-search">
                    <span class="search-icon" aria-hidden="true"></span>
                    <input id="task-search" bind:value={searchTerm} placeholder="Search" data-testid="task-search-input" />
                  </label>
                {:else}
                  <button type="button" class="task-search-link" data-testid="task-search-link" onclick={() => { showTaskSearch = true; }}>Search</button>
                {/if}
                {#if showDesktopTaskTags}
                  <div class="task-filter-chips" data-testid="task-filter-tags" aria-label="Task filters">
                    {#each taskFilterChips as chip}
                      <button type="button" class:active={searchTerm.replace(/^#/, '') === chip} onclick={() => { searchTerm = searchTerm.replace(/^#/, '') === chip ? '' : chip; }}>#{chip}</button>
                    {/each}
                  </div>
                {/if}
              {/if}
            </div>
            <button
              type="button"
              class="task-filter-button"
              class:active={isNarrowTasksWorkspace ? showMobileTaskTags : showDesktopTaskTags}
              data-testid="task-filter-button"
              aria-label="Toggle task filters"
              aria-expanded={isNarrowTasksWorkspace ? showMobileTaskTags : showDesktopTaskTags}
              onclick={() => {
                if (isNarrowTasksWorkspace) showMobileTaskTags = !showMobileTaskTags;
                else showDesktopTaskTags = !showDesktopTaskTags;
              }}
            ><span aria-hidden="true"></span></button>
            {#if isNarrowTasksWorkspace && showMobileTaskTags}
              <div class="task-filter-chips mobile" data-testid="task-filter-tags" aria-label="Task filters">
                {#each taskFilterChips as chip}
                  <button type="button" class:active={searchTerm.replace(/^#/, '') === chip} onclick={() => { searchTerm = searchTerm.replace(/^#/, '') === chip ? '' : chip; }}>#{chip}</button>
                {/each}
              </div>
            {/if}
          </div>
        </div>

        {#if isLoading}
          <div class="tasks-state" data-testid="tasks-loading">Loading tasks...</div>
        {:else if hasLoadError}
          <div class="tasks-state" data-testid="tasks-load-error">
            <p>Tasks could not be loaded.</p>
            <button type="button" onclick={() => void refreshTasks()}>Retry</button>
          </div>
        {:else}
          <div class="task-board-detail-layout" class:split={selectedWorkflowRunProjection && !isNarrowTasksWorkspace}>
            <div class="task-board-stage">
              <TaskBoard
                tasks={visibleTasks}
                onMove={(task, status) => void handleMove(task, status)}
                onStartAI={(task) => void handleStartAI(task)}
                onSkip={(task) => void handleSkip(task)}
                onDelete={(task) => void handleDelete(task)}
                onCancelWorkflowRun={(task) => void handleCancelWorkflowRun(task)}
                onSelect={handleSelectTask}
              />
              {#if visibleTasks.length === 0 && searchTerm.trim()}
                <div class="tasks-filter-empty" data-testid="tasks-filter-empty">No tasks match that filter.</div>
              {:else if visibleTasks.length === 0}
                <div class="tasks-filter-empty" data-testid="tasks-empty">Click above to add your first task.</div>
              {/if}
            </div>
            {#if selectedWorkflowRunProjection}
              <WorkflowRunTaskDetail
                projection={selectedWorkflowRunProjection}
                presentation={isNarrowTasksWorkspace ? 'overlay' : 'split'}
                onClose={() => { selectedWorkflowRunProjection = null; }}
              />
            {/if}
          </div>
        {/if}
      </section>
      <svelte:fragment slot="composer">
        <WorkspacePromptComposer
          surface="tasks"
          bind:value={taskPromptValue}
          placeholder="Click to add or update tasks"
          submitLabel="Send"
          submittingLabel="Saving..."
          disabled={!tasksEnabled || isSaving}
          submitting={isSaving}
          testId="task-workspace-composer"
          inputTestId="task-workspace-input"
          submitTestId="task-workspace-submit"
          micTestId="task-workspace-mic"
          onSubmit={handleTaskPromptSubmit}
          onMicClick={() => { notificationStore.error('Voice task input is not available yet'); }}
        />
        {#if pendingTaskDelete}
          <div class="task-confirmation" data-testid="task-delete-confirmation">
            <span>Delete "{pendingTaskDelete.task.title}"? This cannot be undone.</span>
            <button type="button" onclick={() => void confirmTaskDelete()} data-testid="task-delete-confirm">Delete</button>
            <button type="button" onclick={() => { pendingTaskDelete = null; }} data-testid="task-delete-cancel">Cancel</button>
          </div>
        {/if}
      </svelte:fragment>
      </WorkspaceHomeShell>
    </section>
  {:else}
  {#if plansEnabled}
  <section class="plans-strip" data-testid="linked-plans-section" aria-label="Linked plans">
    <div class="plans-strip-heading">
      <div>
        <p class="eyebrow">Plans</p>
        <h2>{chatId ? 'Chat plan' : projectId ? 'Project plans' : 'Active plans'}</h2>
      </div>
      <span>{activePlans.length}</span>
    </div>
    <form class="plan-create-row" onsubmit={(event) => { event.preventDefault(); void handleCreatePlan(); }} data-testid="plan-create-form">
      <input bind:value={planTitle} placeholder={compact ? 'New project plan' : 'New plan'} data-testid="plan-title-input" />
      <input bind:value={planSummary} placeholder="Optional plan summary" data-testid="plan-summary-input" />
      <button type="submit" disabled={isSaving || !planTitle.trim()} data-testid="plan-create-button">
        {isSaving ? 'Creating...' : 'Create plan'}
      </button>
    </form>
    {#if isLoadingPlans}
      <div class="plans-loading" data-testid="plans-loading">Loading plans...</div>
    {:else if activePlans.length > 0}
      <div class="plan-card-list">
        {#each activePlans as plan (plan.plan_id)}
          <article class="plan-card" data-testid="linked-plan-card" data-plan-status={plan.status}>
            <div>
              <p class="plan-status">{plan.status.replaceAll('_', ' ')}</p>
              <h3>{plan.title || 'Untitled plan'}</h3>
              {#if plan.summary || plan.goal}
                <p>{plan.summary || plan.goal}</p>
              {/if}
            </div>
            <div class="plan-actions">
              <a href={`/plans/${encodeURIComponent(plan.plan_id)}`} data-testid="plan-detail-link">Open</a>
              {#if plan.status === 'draft' || plan.status === 'awaiting_confirmation'}
                <button type="button" disabled={planActionId === plan.plan_id} onclick={() => void handleActivatePlan(plan)} data-testid="plan-activate-button">
                  {planActionId === plan.plan_id ? 'Activating...' : 'Activate'}
                </button>
              {/if}
              <button type="button" disabled={planActionId === plan.plan_id} onclick={() => void handleCompletePlan(plan)} data-testid="plan-complete-button">
                {planActionId === plan.plan_id ? 'Saving...' : 'Complete'}
              </button>
            </div>
          </article>
        {/each}
      </div>
    {:else}
      <div class="plans-empty" data-testid="plans-empty">Create a plan above to coordinate tasks and verification.</div>
    {/if}
  </section>
  {/if}

  <form class="task-create-card" class:compact onsubmit={(event) => { event.preventDefault(); void handleCreateTask(); }} data-testid="task-create-form">
    <div>
      <label for={compact ? 'project-task-title' : 'task-title'}>New task</label>
      <input
        id={compact ? 'project-task-title' : 'task-title'}
        bind:value={title}
        placeholder={compact ? 'Add a project task' : 'What should happen next?'}
        data-testid="task-title-input"
      />
    </div>
    <div>
      <label for={compact ? 'project-task-description' : 'task-description'}>Details</label>
      <textarea
        id={compact ? 'project-task-description' : 'task-description'}
        bind:value={description}
        placeholder="Optional context or instructions"
        rows={compact ? 2 : 3}
        data-testid="task-description-input"
      ></textarea>
    </div>
    <label class="ai-toggle">
      <input type="checkbox" bind:checked={assignToAI} data-testid="task-assign-ai-toggle" />
      <span>Assign to AI now</span>
    </label>
    <button type="submit" disabled={isSaving || !title.trim()} data-testid="task-create-button">
      {isSaving ? 'Creating...' : 'Create task'}
    </button>
  </form>

  <section class="task-extract-card" data-testid="task-extract-card" aria-label="Create tasks from transcript">
    <div class="task-extract-heading">
      <div>
        <p class="eyebrow">Voice transcript</p>
        <h2>Review extracted tasks before saving.</h2>
      </div>
      <button type="button" onclick={() => { correctedTranscriptText = transcriptText; }} disabled={!transcriptText.trim()} data-testid="task-use-transcript-button">
        Use transcript
      </button>
    </div>
    <label for={compact ? 'project-task-transcript' : 'task-transcript'}>Audio transcript or dictated text</label>
    <textarea
      id={compact ? 'project-task-transcript' : 'task-transcript'}
      bind:value={transcriptText}
      placeholder="Paste or dictate the raw transcript here"
      rows={compact ? 2 : 3}
      data-testid="task-transcript-input"
    ></textarea>
    <label for={compact ? 'project-task-corrected-transcript' : 'task-corrected-transcript'}>Corrected transcript</label>
    <textarea
      id={compact ? 'project-task-corrected-transcript' : 'task-corrected-transcript'}
      bind:value={correctedTranscriptText}
      placeholder="Review and correct the transcript before extraction"
      rows={compact ? 2 : 3}
      data-testid="task-corrected-transcript-input"
    ></textarea>
    <button type="button" onclick={() => void handleExtractTasks()} disabled={isExtracting || !(correctedTranscriptText || transcriptText).trim()} data-testid="task-extract-button">
      {isExtracting ? 'Extracting...' : 'Extract task proposals'}
    </button>

    {#if extractedProposals.length > 0}
      <div class="task-proposal-list" data-testid="task-extract-proposals">
        {#each extractedProposals as proposal}
          <article class="task-proposal-card" data-testid="task-extract-proposal">
            <div>
              <strong>{proposal.title}</strong>
              {#if proposal.description}
                <span>{proposal.description}</span>
              {/if}
            </div>
            <div class="task-proposal-actions">
              <button type="button" onclick={() => void handleAcceptProposal(proposal)} disabled={isSaving} data-testid="task-accept-proposal-button">Create</button>
              <button type="button" onclick={() => handleDismissProposal(proposal)} disabled={isSaving} data-testid="task-dismiss-proposal-button">Dismiss</button>
            </div>
          </article>
        {/each}
      </div>
    {/if}
  </section>

  {#if isLoading}
    <div class="tasks-state" data-testid="tasks-loading">Loading tasks...</div>
  {:else if hasLoadError}
    <div class="tasks-state" data-testid="tasks-load-error">
      <p>Tasks could not be loaded.</p>
      <button type="button" onclick={() => void refreshTasks()}>Retry</button>
    </div>
  {:else if tasks.length === 0}
    <div class="tasks-state" data-testid="tasks-empty">
      <h2>No tasks yet</h2>
      <p>Create your first task above to start planning work.</p>
    </div>
  {:else}
    <TaskBoard
      {tasks}
      onMove={(task, status) => void handleMove(task, status)}
      onStartAI={(task) => void handleStartAI(task)}
      onSkip={(task) => void handleSkip(task)}
      onDelete={(task) => void handleDelete(task)}
      onCancelWorkflowRun={(task) => void handleCancelWorkflowRun(task)}
      onSelect={handleSelectTask}
    />
  {/if}
  {/if}
  {#if selectedTask}
    <TaskDetailFullscreen task={selectedTask} onClose={() => { selectedTask = null; }} />
  {/if}
</section>
{/if}

<style>
  .tasks-page {
    position: relative;
    flex: 1;
    min-width: 0;
    height: 100%;
    overflow: auto;
    padding: clamp(18px, 3vw, 34px);
    background: var(--color-grey-0);
    color: var(--color-font-primary);
  }

  .tasks-page > .tasks-figma-workspace,
  .tasks-page > .tasks-figma-workspace :global(.workspace-home-shell) {
    flex: 1;
    min-height: 0;
  }

  .tasks-page.compact {
    padding: 0;
    overflow: visible;
  }

  .tasks-page.figma-layout {
    background: var(--color-grey-20);
    overflow: hidden;
    padding: 0;
  }

  .tasks-hero,
  .plans-strip,
  .task-create-card,
  .task-extract-card,
  .tasks-state {
    border-radius: 32px;
    border: 1px solid var(--color-grey-20);
    background: linear-gradient(135deg, var(--color-grey-10), var(--color-grey-0));
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.08);
  }

  .tasks-hero {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 24px;
    padding: clamp(24px, 5vw, 54px);
    margin-bottom: 18px;
  }

  .tasks-daily-inspiration-area {
    margin-bottom: 18px;
  }

  .tasks-page.figma-layout .tasks-daily-inspiration-area {
    margin-bottom: clamp(18px, 3vw, 34px);
  }

  .tasks-figma-workspace {
    position: relative;
    display: flex;
    height: 100%;
    min-height: 0;
    min-width: 0;
    flex-direction: column;
    gap: 18px;
    overflow: hidden;
    border-radius: 17px;
    background: var(--color-grey-20);
    box-shadow: 0 0 12px rgba(0, 0, 0, 0.25);
  }

  .task-board-panel {
    display: flex;
    min-height: 0;
    flex: 1;
    flex-direction: column;
    gap: var(--spacing-8);
  }

  .task-workspace-toolbar {
    position: relative;
    z-index: 2;
    display: flex;
    align-items: flex-end;
    justify-content: flex-end;
    gap: 18px;
  }

  .task-search-cluster {
    display: flex;
    align-items: flex-start;
    justify-content: flex-end;
    gap: 12px;
  }

  .task-search-stack {
    display: flex;
    min-width: 0;
    flex-direction: column;
    align-items: flex-end;
    gap: 6px;
  }

  .task-search-link {
    border: 0;
    background: transparent;
    padding: 0;
    color: var(--color-font-secondary);
    font: inherit;
    font-size: var(--font-size-small);
    font-weight: 700;
    text-decoration: underline;
    text-underline-offset: 3px;
    box-shadow: none;
  }

  .task-search-field {
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: flex-end;
    gap: 10px;
    min-height: 44px;
    border: 1px solid var(--color-grey-20);
    border-radius: var(--radius-full);
    background: var(--color-grey-10);
    padding: 8px 12px;
    color: var(--color-font-secondary);
  }

  .search-icon {
    position: relative;
    width: 18px;
    height: 18px;
    border: 3px solid currentColor;
    border-radius: 999px;
    opacity: 0.65;
  }

  .search-icon::after {
    content: '';
    position: absolute;
    right: -8px;
    bottom: -7px;
    width: 9px;
    height: 3px;
    border-radius: 999px;
    background: currentColor;
    transform: rotate(45deg);
  }

  .task-search-field input {
    width: min(100%, 190px);
    border: 0;
    background: transparent;
    padding: 6px 0;
    color: var(--color-font-primary);
    font-size: 1.08rem;
    font-weight: 700;
  }

  .task-search-field input::placeholder {
    color: var(--color-font-secondary);
    opacity: 0.9;
  }

  .task-filter-chips {
    display: flex;
    flex-wrap: wrap;
    justify-content: flex-end;
    gap: 8px;
  }

  .task-filter-chips button {
    border-radius: 999px;
    background: var(--color-primary);
    color: var(--color-font-button);
    padding: 5px 12px;
    font-size: 0.85rem;
    font-weight: 700;
    box-shadow: none;
  }

  .task-filter-chips button.active {
    background: var(--color-button-primary);
  }

  .task-filter-button {
    display: grid;
    width: 44px;
    height: 44px;
    flex: 0 0 44px;
    place-items: center;
    border: 0;
    border-radius: var(--radius-full);
    padding: 0;
    background: var(--color-grey-10);
    box-shadow: var(--shadow-md);
    box-sizing: border-box;
    cursor: pointer;
  }

  .task-filter-button span {
    width: 20px;
    height: 20px;
    background: var(--color-font-primary);
    -webkit-mask: url('@openmates/ui/static/icons/filter.svg') center / contain no-repeat;
    mask: url('@openmates/ui/static/icons/filter.svg') center / contain no-repeat;
  }

  .task-filter-button.active {
    background: color-mix(in srgb, var(--color-primary) 16%, var(--color-grey-10));
  }

  .task-board-stage {
    position: relative;
    z-index: 1;
    min-height: 0;
  }

  .task-board-detail-layout { display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--spacing-5); min-width: 0; min-height: 0; }
  .task-board-detail-layout.split { grid-template-columns: minmax(0, 1fr) minmax(360px, 40%); }

  .task-board-stage :global(.task-board) {
    grid-template-columns: repeat(5, minmax(260px, 280px));
    gap: 14px;
    width: 100%;
    min-width: 0;
    max-height: none;
    overflow: auto;
    padding-bottom: 8px;
    -webkit-overflow-scrolling: touch;
  }

  .task-board-stage :global(.task-column) {
    min-height: 410px;
    border: 0;
    border-radius: 26px;
    background: transparent;
    padding: 18px;
  }

  .task-board-stage :global([data-testid='task-column-backlog']) {
    background: var(--color-grey-10);
  }

  .task-board-stage :global(.task-column header p),
  .task-board-stage :global(.task-column header span) {
    display: none;
  }

  .task-board-stage :global(.task-column h2) {
    font-size: clamp(1.25rem, 1.6vw, 1.55rem);
    line-height: 1.1;
    letter-spacing: -0.04em;
  }

  .task-board-stage :global(.task-card) {
    border: 0;
    border-radius: 16px;
    box-shadow: 0 8px 14px rgba(0, 0, 0, 0.16);
  }

  .task-board-stage :global(.task-actions) {
    opacity: 0.78;
  }

  .tasks-filter-empty {
    margin-top: 12px;
    border: 1px dashed var(--color-grey-30);
    border-radius: 20px;
    padding: 12px 16px;
    color: var(--color-font-secondary);
    background: var(--color-grey-0);
  }

  .task-confirmation {
    display: flex;
    max-width: min(620px, calc(100vw - 40px));
    flex-wrap: wrap;
    align-items: center;
    justify-content: center;
    gap: 8px;
    border: 1px solid var(--color-grey-20);
    border-radius: 18px;
    padding: 10px 12px;
    background: color-mix(in srgb, var(--color-grey-0) 92%, transparent);
    box-shadow: 0 10px 24px rgba(0, 0, 0, 0.08);
    color: var(--color-font-primary);
    font-size: var(--font-size-small);
  }

  .task-confirmation button:first-of-type {
    background: var(--color-error, #c83a32);
    color: var(--color-grey-0);
  }

  .plans-strip {
    display: flex;
    flex-direction: column;
    gap: 14px;
    padding: 16px;
    margin-bottom: 18px;
  }

  .tasks-page.compact .plans-strip {
    box-shadow: none;
    margin-bottom: 16px;
  }

  .plans-strip-heading {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
  }

  .plans-strip-heading span {
    display: grid;
    place-items: center;
    min-width: 30px;
    height: 30px;
    border-radius: 999px;
    background: var(--color-grey-0);
    color: var(--color-font-secondary);
    font-size: 0.82rem;
  }

  .plan-create-row {
    display: grid;
    grid-template-columns: minmax(180px, 1fr) minmax(220px, 1.4fr) auto;
    gap: 10px;
    align-items: center;
  }

  .tasks-page.compact .plan-create-row {
    grid-template-columns: 1fr;
  }

  .plans-loading,
  .plans-empty {
    border: 1px dashed var(--color-grey-30);
    border-radius: 20px;
    padding: 16px;
    color: var(--color-font-secondary);
    font-size: 0.88rem;
  }

  .plan-card-list {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    gap: 12px;
  }

  .plan-card {
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    gap: 16px;
    border: 1px solid var(--color-grey-20);
    border-radius: 24px;
    padding: 14px;
    background: var(--color-grey-0);
  }

  .plan-card h3 {
    margin: 0;
    font-size: 1rem;
  }

  .plan-card p:not(.plan-status) {
    margin-top: 6px;
    color: var(--color-font-secondary);
    font-size: 0.86rem;
  }

  .plan-status {
    margin: 0 0 6px;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--color-font-secondary);
    font-size: 0.68rem;
    font-weight: 700;
  }

  .plan-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }

  .plan-actions a {
    display: grid;
    min-width: 44px;
    min-height: 44px;
    place-items: center;
    border-radius: var(--radius-full);
    background: var(--color-grey-10);
    color: var(--color-font-primary);
    font-size: var(--font-size-xs);
  }

  .eyebrow {
    margin: 0 0 8px;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    color: var(--color-font-secondary);
    font-size: 0.75rem;
    font-weight: 700;
  }

  h1,
  h2,
  h3,
  p {
    margin: 0;
  }

  h1 {
    max-width: 980px;
    font-size: clamp(2.6rem, 5.6vw, 5rem);
    line-height: 1.03;
    letter-spacing: -0.055em;
  }

  .tasks-hero p:not(.eyebrow),
  .tasks-state p {
    max-width: 650px;
    margin-top: 12px;
    color: var(--color-font-secondary);
  }

  .task-stats {
    display: flex;
    flex-wrap: wrap;
    justify-content: flex-end;
    gap: 10px;
  }

  .task-stats span {
    border-radius: 999px;
    padding: 8px 12px;
    background: var(--color-grey-0);
    color: var(--color-font-secondary);
    white-space: nowrap;
  }

  .task-stats strong {
    color: var(--color-font-primary);
  }

  .task-create-card {
    display: grid;
    grid-template-columns: minmax(180px, 1.2fr) minmax(220px, 2fr) auto auto;
    align-items: end;
    gap: 12px;
    padding: 16px;
    margin-bottom: 18px;
  }

  .task-extract-card {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 16px;
    margin-bottom: 18px;
  }

  .task-extract-heading {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
  }

  .task-proposal-list {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .task-proposal-card {
    display: flex;
    justify-content: space-between;
    gap: 12px;
    padding: 12px;
    border-radius: 18px;
    background: var(--color-grey-0);
    box-shadow: 0 4px 18px rgba(0, 0, 0, 0.08);
  }

  .task-proposal-card div:first-child {
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-width: 0;
  }

  .task-proposal-card span {
    color: var(--color-font-secondary);
    font-size: var(--font-size-small);
  }

  .task-proposal-actions {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }

  .task-create-card.compact {
    grid-template-columns: 1fr;
    box-shadow: none;
    margin-bottom: 16px;
  }

  label {
    display: flex;
    flex-direction: column;
    gap: 6px;
    color: var(--color-font-secondary);
    font-size: 0.8rem;
  }

  input,
  textarea {
    width: 100%;
    box-sizing: border-box;
    border: 1px solid var(--color-grey-30);
    border-radius: 18px;
    background: var(--color-grey-0);
    color: var(--color-font-primary);
    padding: 11px 13px;
    font: inherit;
  }

  textarea {
    resize: vertical;
  }

  .ai-toggle {
    flex-direction: row;
    align-items: center;
    color: var(--color-font-primary);
    white-space: nowrap;
  }

  button {
    border: 0;
    border-radius: 999px;
    background: var(--color-button-primary);
    color: var(--color-font-button);
    padding: 12px 16px;
    font: inherit;
    cursor: pointer;
  }

  button:disabled {
    opacity: 0.55;
    cursor: not-allowed;
  }

  .tasks-state {
    display: grid;
    place-items: center;
    gap: 10px;
    min-height: 260px;
    padding: 28px;
    text-align: center;
  }

  @media (max-width: 900px) {
    .tasks-hero,
    .task-create-card {
      grid-template-columns: 1fr;
      flex-direction: column;
    }

    .tasks-figma-workspace {
      min-height: 0;
    }

    .task-workspace-toolbar {
      align-items: flex-start;
    }

    .task-search-cluster {
      flex-wrap: wrap;
      justify-content: flex-end;
      width: 100%;
      min-width: 0;
    }

    .task-search-stack {
      display: none;
    }

    .task-filter-chips.mobile {
      width: 100%;
    }

    .task-board-stage :global(.task-board) {
      grid-template-columns: repeat(5, minmax(252px, 270px));
    }

    .task-board-stage :global(.task-column) {
      min-height: auto;
    }

    .task-stats {
      justify-content: flex-start;
    }
  }
</style>
