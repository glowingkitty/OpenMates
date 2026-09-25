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
  import { getApiUrl } from '../../config/api';
  import { getProfileImageBlobUrl } from '../../services/profileImageService';
  import { listProjects } from '../../services/projectService';
  import {
    blockUserTask,
    completeUserTask,
    createUserTask,
    deleteUserTask,
    cancelWorkflowRunTaskProjection,
    extractUserTaskProposals,
    getTaskAssignmentEligibility,
    isWorkflowRunTaskProjectionViewModel,
    listTaskBoardItems,
    reorderUserTasks,
    skipUserTask,
    startUserTaskWithAI,
    unblockUserTask,
    updateUserTask,
    type ListUserTasksFilters,
    type UserTaskProposal,
    type UserTaskAssigneeIdentity,
    type UserTaskAssigneeType,
    type UserTaskStatus,
    type UserTaskViewModel,
    type TasksBoardItem,
    type WorkflowRunTaskProjectionViewModel,
  } from '../../services/userTaskService';
  import {
    activateUserPlan,
    completeUserPlan,
    listUserPlans,
    updateUserPlan,
    type UserPlanStatus,
    type UserPlanViewModel,
  } from '../../services/userPlanService';

  type TaskAssigneeChoice = 'user' | 'openmates' | 'codex' | 'unassigned';

  let {
    projectId = null,
    chatId = null,
    compact = false,
    focus = 'tasks',
    previewTasks = null,
    previewPlans = null,
    previewProjectNames = {},
    previewAssigneeAvatarUrl = null,
  }: {
    projectId?: string | null;
    chatId?: string | null;
    compact?: boolean;
    focus?: 'tasks' | 'plans';
    previewTasks?: TasksBoardItem[] | null;
    previewPlans?: UserPlanViewModel[] | null;
    previewProjectNames?: Record<string, string>;
    previewAssigneeAvatarUrl?: string | null;
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
  let taskAssigneeChoice = $state<TaskAssigneeChoice>('user');
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
  let projectNames = $state<Record<string, string>>({});
  let assigneeAvatarUrl = $state<string | null>(null);
  let featureAvailabilityReady = $derived($featureAvailabilityStore.initialized && $featureAvailabilityStore.disabledById !== null);
  let hasPreviewData = $derived(previewTasks !== null || previewPlans !== null);
  let tasksEnabled = $derived(previewTasks !== null || (featureAvailabilityReady && $featureAvailabilityStore.disabledById?.['platform:tasks'] !== true));
  let plansEnabled = $derived(previewPlans !== null || (!hasPreviewData && featureAvailabilityReady && $featureAvailabilityStore.disabledById?.['platform:plans'] !== true));
  let isCentralTasksWorkspace = $derived(!compact && focus === 'tasks');
  let isNarrowTasksWorkspace = $derived(tasksPageWidth <= 900);

  const boardPlans = $derived(plans.filter((plan) => plan.status !== 'archived'));
  const totalCount = $derived(tasks.length + boardPlans.length);
  const activeCount = $derived(tasks.filter((task) => task.status === 'in_progress').length + plans.filter((plan) => plan.status === 'executing' || plan.status === 'running_checks').length);
  const doneCount = $derived(tasks.filter((task) => task.status === 'done').length + plans.filter((plan) => plan.status === 'completed').length);
  const activePlans = $derived(plans.filter((plan) => !['completed', 'archived'].includes(plan.status)));
  const completedPlanCount = $derived(plans.filter((plan) => plan.status === 'completed').length);
  const greetingName = $derived(formatGreetingName($userProfile.username));
  const taskFilterChips = $derived(resolveTaskFilterChips(tasks));
  const visibleTasks = $derived(filterTasks(tasks, searchTerm));
  const visiblePlans = $derived(filterPlans(boardPlans, searchTerm));
  const isBoardLoading = $derived(isLoading || (plansEnabled && isLoadingPlans));
  let canAssignCodex = $state(false);

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

  function filterPlans(items: UserPlanViewModel[], query: string): UserPlanViewModel[] {
    const normalized = query.trim().replace(/^#/, '').toLowerCase();
    if (!normalized) return items;
    return items.filter((plan) => [
      plan.title,
      plan.goal,
      plan.status,
      plan.status.replaceAll('_', '-'),
      plan.risks,
      ...plan.linkedProjectIds.map((id) => projectNames[id] ?? ''),
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

  function createAssigneeInput(choice: TaskAssigneeChoice): { assigneeType: UserTaskAssigneeType; assigneeIdentity: UserTaskAssigneeIdentity | null } {
    if (choice === 'openmates') return { assigneeType: 'openmates', assigneeIdentity: 'openmates' };
    if (choice === 'codex') return { assigneeType: 'external_ai', assigneeIdentity: 'codex' };
    if (choice === 'unassigned') return { assigneeType: 'unassigned', assigneeIdentity: null };
    return { assigneeType: 'user', assigneeIdentity: null };
  }

  function assigneeSuccessLabel(choice: TaskAssigneeChoice): string {
    if (choice === 'openmates') return 'AI task started';
    if (choice === 'codex') return 'Task assigned to Codex';
    if (choice === 'unassigned') return 'Unassigned task created';
    return 'Task created';
  }

  function assignmentPatchForTask(task: UserTaskViewModel, choice: TaskAssigneeChoice): Parameters<typeof updateUserTask>[1] {
    const assignment = createAssigneeInput(choice);
    return {
      assigneeType: assignment.assigneeType,
      assigneeIdentity: assignment.assigneeIdentity,
      ...(task.externalChat && (choice !== 'codex' || task.externalChat.provider !== 'codex') ? { primaryChatId: task.primaryChatId ?? null } : {}),
    };
  }

  function parseAssigneeUpdate(request: string): TaskAssigneeChoice | null {
    if (!/\b(assign|assigned|handoff|hand off|start)\b/i.test(request)) return null;
    if (/\bcodex\b/i.test(request)) return 'codex';
    if (/\b(openmates|ai mate|ai)\b/i.test(request)) return 'openmates';
    if (/\b(unassigned|no assignee)\b/i.test(request)) return 'unassigned';
    if (/\b(me|myself|user)\b/i.test(request)) return 'user';
    return null;
  }

  function requestedCodexAssignment(request: string): boolean {
    return /\b(assign|assigned|handoff|hand off|start)\b/i.test(request) && /\bcodex\b/i.test(request);
  }

  function handleTaskChange(updated: UserTaskViewModel): void {
    tasks = tasks.map((candidate) => candidate.task_id === updated.task_id ? updated : candidate);
    if (selectedTask?.task_id === updated.task_id) selectedTask = updated;
    broadcastTasksChanged();
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
    return /\b(rename|retitle|edit|update|move|mark|delete|remove|complete|block|start|skip|assign|assigned|handoff|hand off)\b/i.test(request);
  }

  function looksLikeTaskCreationRequest(request: string): boolean {
    return /\b(create|add|new|make)\b/i.test(request) && /\b(task|to do|todo)\b/i.test(request);
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
    canAssignCodex = false;
    if (!tasksEnabled) {
      tasks = [];
      isLoading = false;
      return;
    }
    isLoading = true;
    try {
      hasLoadError = false;
      const [loadedTasks, eligible] = await Promise.all([listTaskBoardItems(filters()), getTaskAssignmentEligibility()]);
      tasks = loadedTasks;
      canAssignCodex = eligible;
    } catch (error) {
      hasLoadError = true;
      console.error('[TasksPage] Failed to load tasks:', error);
      notificationStore.error('Failed to load tasks');
    } finally {
      isLoading = false;
    }
  }

  async function refreshTaskPresentation(): Promise<void> {
    if (previewTasks !== null) {
      projectNames = previewProjectNames;
      assigneeAvatarUrl = previewAssigneeAvatarUrl;
      return;
    }
    try {
      const projects = await listProjects();
      projectNames = Object.fromEntries(projects.map((project) => [project.project_id, project.name]));
    } catch (error) {
      console.error('[TasksPage] Failed to load linked project labels:', error);
      projectNames = {};
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
    if (taskAssigneeChoice === 'codex' && !canAssignCodex) {
      notificationStore.error('Codex must create its first task before it can be assigned work.');
      return;
    }
    isSaving = true;
    try {
      const selectedAssignee = taskAssigneeChoice;
      const assignment = createAssigneeInput(selectedAssignee);
      const task = await createUserTask({
        title: trimmedTitle,
        description: description.trim(),
        assigneeType: assignment.assigneeType,
        assigneeIdentity: assignment.assigneeIdentity,
        primaryChatId: chatId,
        linkedProjectIds: projectId ? [projectId] : [],
      });
      tasks = [task, ...tasks];
      broadcastTasksChanged();
      title = '';
      description = '';
      taskAssigneeChoice = 'user';
      notificationStore.success(assigneeSuccessLabel(selectedAssignee));
    } catch (error) {
      console.error('[TasksPage] Failed to create task:', error);
      notificationStore.error('Failed to create task');
    } finally {
      isSaving = false;
    }
  }

  async function handleTaskPromptSubmit(value: string): Promise<void> {
    if (!tasksEnabled || isSaving) return;
    if (/\bexternal[-\s]?ai\b/i.test(value) && !/\bcodex\b/i.test(value) && /\b(assign|start|handoff|hand off)\b/i.test(value)) {
      notificationStore.error('Name Codex explicitly when assigning work to it.');
      return;
    }
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
      const targetAssignee = parseAssigneeUpdate(value);
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
      if (targetAssignee) {
        if (targetAssignee === 'codex' && !canAssignCodex) {
          notificationStore.error('Codex must create its first task before it can be assigned work.');
        } else if (targetAssignee === 'openmates') {
          await handleStartAI(mentionedTask);
        } else {
          await updateTaskFromPrompt(mentionedTask, assignmentPatchForTask(mentionedTask, targetAssignee), targetAssignee === 'codex' ? 'Task assigned to Codex' : 'Task assignment updated');
        }
        taskPromptValue = '';
        return;
      }
      if (targetStatus) {
        await handleMove(mentionedTask, targetStatus);
        taskPromptValue = '';
        return;
      }
    }

    if (looksLikeTaskManagementRequest(value) && !looksLikeTaskCreationRequest(value)) {
      notificationStore.error('I could not find a matching task. Include the exact task title.');
      return;
    }

    await createTaskFromPrompt(value);
    taskPromptValue = '';
  }

  async function createTaskFromPrompt(value: string): Promise<void> {
    if (requestedCodexAssignment(value) && !canAssignCodex) {
      notificationStore.error('Codex must create its first task before it can be assigned work.');
      return;
    }
    isSaving = true;
    try {
      const selectedAssignee: TaskAssigneeChoice = requestedCodexAssignment(value)
        ? 'codex'
        : /\b(ai|mate)\b/i.test(value) && /\b(assign|start)\b/i.test(value)
          ? 'openmates'
          : 'user';
      const assignment = createAssigneeInput(selectedAssignee);
      const task = await createUserTask({
        title: value,
        description: value.split(/\s+/).length > 10 ? value : '',
        assigneeType: assignment.assigneeType,
        assigneeIdentity: assignment.assigneeIdentity,
        primaryChatId: chatId,
        linkedProjectIds: projectId ? [projectId] : [],
      });
      tasks = [task, ...tasks];
      broadcastTasksChanged();
      notificationStore.success(assigneeSuccessLabel(selectedAssignee));
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

  function planStatusForColumn(status: UserTaskStatus): UserPlanStatus {
    if (status === 'done') return 'completed';
    if (status === 'blocked') return 'blocked';
    if (status === 'in_progress') return 'executing';
    if (status === 'todo') return 'awaiting_confirmation';
    return 'draft';
  }

  async function handleMovePlan(plan: UserPlanViewModel, status: UserTaskStatus): Promise<void> {
    if (!plansEnabled || planActionId) return;
    if ((status === 'in_progress' || status === 'blocked') && !plan.primaryChatId) {
      notificationStore.error(status === 'in_progress' ? 'Link this plan to a chat before starting it.' : 'Link this plan to a chat before blocking it.');
      return;
    }
    const previous = plans;
    plans = plans.map((candidate) => candidate.plan_id === plan.plan_id ? { ...candidate, status: planStatusForColumn(status) } : candidate);
    planActionId = plan.plan_id;
    try {
      let updated: UserPlanViewModel;
      if (status === 'done') {
        updated = await completeUserPlan(plan);
      } else if (status === 'todo') {
        updated = plan.primaryChatId ? await activateUserPlan(plan) : await updateUserPlan(plan, { status: 'awaiting_confirmation' });
      } else if (status === 'in_progress') {
        updated = await updateUserPlan(plan, { status: 'executing' });
      } else if (status === 'blocked') {
        updated = await updateUserPlan(plan, { status: 'blocked' });
      } else {
        updated = await updateUserPlan(plan, { status: 'draft' });
      }
      plans = plans.map((candidate) => candidate.plan_id === updated.plan_id ? updated : candidate);
      broadcastPlansChanged();
      notificationStore.success(status === 'done' ? 'Plan completed' : 'Plan updated');
    } catch (error) {
      plans = previous;
      console.error('[TasksPage] Failed to move plan:', error);
      notificationStore.error(status === 'done' ? 'Plan still has blockers before completion' : error instanceof Error ? error.message : 'Failed to update plan');
    } finally {
      planActionId = null;
    }
  }

  onMount(() => {
    if (hasPreviewData) return;
    void initializeFeatureAvailability();
    if (!isCentralTasksWorkspace) {
      void loadDefaultInspirations({ surface: 'tasks', allowIndexedDB: false });
    }
    void refreshTaskPresentation();
  });

  $effect(() => {
    const profileImageUrl = $userProfile.profile_image_url;
    const userId = $userProfile.user_id;
    if (hasPreviewData) {
      projectNames = previewProjectNames;
      assigneeAvatarUrl = previewAssigneeAvatarUrl;
      return;
    }
    if (!profileImageUrl || !userId) {
      assigneeAvatarUrl = null;
      return;
    }
    let cancelled = false;
    getProfileImageBlobUrl(profileImageUrl, getApiUrl(), userId).then((resolved) => {
      if (!cancelled) assigneeAvatarUrl = resolved;
    });
    return () => { cancelled = true; };
  });

  $effect(() => {
    void projectId;
    void chatId;
    void tasksEnabled;
    void plansEnabled;
    if (hasPreviewData) {
      tasks = previewTasks ?? [];
      plans = previewPlans ?? [];
      isLoading = false;
      isLoadingPlans = false;
      hasLoadError = false;
      return;
    }
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
      <section class="tasks-daily-suggestion" data-testid="tasks-daily-suggestion" aria-label="Daily suggestion">
        <div class="tasks-suggestion-label">
          <span class="tasks-suggestion-book" aria-hidden="true"></span>
          <span data-testid="tasks-suggestion-heading">Daily suggestion</span>
        </div>
        <div class="tasks-suggestion-content">
          <p data-testid="tasks-suggestion-description">Security is essential, especially in the age of AI. Review your public endpoints before launch.</p>
          <article class="tasks-suggestion-card" data-testid="tasks-suggestion-card" aria-label="Suggested task">
            <strong>Double check security and potential risks of FastAPI endpoints.</strong>
            <span>OpenMates</span>
          </article>
        </div>
        <button
          type="button"
          class="tasks-suggestion-create"
          data-testid="tasks-suggestion-create"
          onclick={() => { taskPromptValue = 'Create a task to double check security and potential risks of FastAPI endpoints'; }}
        ><span aria-hidden="true">＋</span> Click to create task</button>
      </section>
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
                  <button type="button" class="task-search-link" data-testid="task-search-link" onclick={() => { showTaskSearch = true; }}><span class="task-search-link-icon" aria-hidden="true"></span>Search</button>
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

        {#if isBoardLoading}
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
                plans={visiblePlans}
                {projectNames}
                {assigneeAvatarUrl}
                {planActionId}
                onMove={(task, status) => void handleMove(task, status)}
                onMovePlan={(plan, status) => void handleMovePlan(plan, status)}
                onStartAI={(task) => void handleStartAI(task)}
                onSkip={(task) => void handleSkip(task)}
                onDelete={(task) => void handleDelete(task)}
                onCancelWorkflowRun={(task) => void handleCancelWorkflowRun(task)}
                onSelect={handleSelectTask}
              />
              {#if visibleTasks.length === 0 && visiblePlans.length === 0 && searchTerm.trim()}
                <div class="tasks-filter-empty" data-testid="tasks-filter-empty">No tasks or plans match that filter.</div>
              {:else if visibleTasks.length === 0 && visiblePlans.length === 0}
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
  {#if !compact}
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
    <label class="assignee-select">
      <span>Assigned to</span>
      <select bind:value={taskAssigneeChoice} data-testid="task-assignee-select">
        <option value="user">Me</option>
        <option value="unassigned">Unassigned</option>
        <option value="openmates">OpenMates</option>
        {#if canAssignCodex}<option value="codex">Codex</option>{/if}
      </select>
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
  {/if}

  {#if compact}
    <div class="compact-task-toolbar" data-testid="project-task-toolbar">
      <label class="compact-task-search" for="project-task-search">
        <span class="search-icon" aria-hidden="true"></span>
        <input id="project-task-search" bind:value={searchTerm} placeholder="Search" data-testid="project-task-search-input" />
      </label>
      <div class="task-filter-chips compact-filters" data-testid="project-task-filter-tags" aria-label="Project task filters">
        {#each taskFilterChips as chip}
          <button type="button" class:active={searchTerm.replace(/^#/, '') === chip} onclick={() => { searchTerm = searchTerm.replace(/^#/, '') === chip ? '' : chip; }}>#{chip}</button>
        {/each}
      </div>
      <button type="button" class="task-filter-button" data-testid="project-task-filter-button" aria-label="Task filters"><span aria-hidden="true"></span></button>
    </div>
  {/if}

  {#if isBoardLoading}
    <div class="tasks-state" data-testid="tasks-loading">Loading tasks...</div>
  {:else if hasLoadError}
    <div class="tasks-state" data-testid="tasks-load-error">
      <p>Tasks could not be loaded.</p>
      <button type="button" onclick={() => void refreshTasks()}>Retry</button>
    </div>
  {:else if tasks.length === 0 && boardPlans.length === 0}
    <div class="tasks-state" data-testid="tasks-empty">
      <h2>No tasks or plans yet</h2>
      <p>{compact ? 'Add your first task or plan to start planning work.' : 'Create your first task above to start planning work.'}</p>
    </div>
  {:else}
    <TaskBoard
      tasks={compact ? visibleTasks : tasks}
      plans={compact ? visiblePlans : boardPlans}
      {projectNames}
      {assigneeAvatarUrl}
      {planActionId}
      onMove={(task, status) => void handleMove(task, status)}
      onMovePlan={(plan, status) => void handleMovePlan(plan, status)}
      onStartAI={(task) => void handleStartAI(task)}
      onSkip={(task) => void handleSkip(task)}
      onDelete={(task) => void handleDelete(task)}
      onCancelWorkflowRun={(task) => void handleCancelWorkflowRun(task)}
      onSelect={handleSelectTask}
    />
  {/if}
  {#if compact}
    <div class="compact-task-composer" data-testid="project-task-composer-shell">
      <WorkspacePromptComposer
        surface="tasks"
        bind:value={taskPromptValue}
        placeholder="Click here to add or update tasks"
        submitLabel="Send"
        submittingLabel="Saving..."
        disabled={!tasksEnabled || isSaving}
        submitting={isSaving}
        testId="project-task-workspace-composer"
        inputTestId="project-task-workspace-input"
        submitTestId="project-task-workspace-submit"
        micTestId="project-task-workspace-mic"
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
    </div>
  {/if}
  {/if}
  {#if selectedTask}
    <TaskDetailFullscreen task={selectedTask} {canAssignCodex} onTaskChange={handleTaskChange} onClose={() => { selectedTask = null; }} />
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

  .compact-task-composer {
    position: absolute;
    z-index: 4;
    bottom: var(--spacing-4);
    left: 50%;
    width: min(42rem, calc(100% - 2 * var(--spacing-8)));
    margin: var(--spacing-8) auto 0;
    transform: translateX(-50%);
  }

  .compact-task-toolbar {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: var(--spacing-3);
    margin: 0 var(--spacing-8) var(--spacing-6);
  }

  .compact-task-search {
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: 6px;
    width: min(78px, 24vw);
    min-height: 20px;
    padding: 0;
    color: var(--color-font-secondary);
  }

  .compact-task-search input {
    min-width: 0;
    border: 0;
    background: transparent;
    padding: 0;
    color: var(--color-font-secondary);
    font-size: var(--font-size-p);
    font-weight: 700;
    line-height: 20px;
    box-shadow: none;
  }

  .compact-task-search input::placeholder {
    color: var(--color-font-secondary);
    opacity: 1;
  }

  .compact-task-search .search-icon {
    width: 16px;
    height: 16px;
    flex: 0 0 16px;
  }

  .compact-filters {
    flex-wrap: nowrap;
  }


  .tasks-page.figma-layout {
    display: flex;
    flex-direction: column;
    background: var(--color-grey-20);
    overflow: hidden;
    padding: 0;
    max-height: 100dvh;
    box-sizing: border-box;
  }

  .tasks-hero,
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
    gap: 0;
    overflow: hidden;
    border-radius: 17px;
    background: var(--color-grey-20);
    box-shadow: 0 0 12px rgba(0, 0, 0, 0.25);
  }

  .tasks-daily-suggestion {
    position: relative;
    z-index: 2;
    flex: 0 0 clamp(180px, 33dvh, 322px);
    box-sizing: border-box;
    overflow: hidden;
    border-radius: 17px;
    padding: clamp(18px, 3vh, 28px) clamp(28px, 8vw, 250px);
    background:
      radial-gradient(circle at 72% 130%, color-mix(in srgb, var(--color-app-business-end) 72%, transparent), transparent 46%),
      linear-gradient(135deg, var(--color-app-business-start), color-mix(in srgb, var(--color-app-business-start) 38%, var(--color-app-business-end)), var(--color-app-business-end));
    color: var(--color-font-button);
    box-shadow: 0 2px 5px rgba(0, 0, 0, 0.3);
  }

  .tasks-suggestion-label {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: var(--spacing-3);
    color: color-mix(in srgb, var(--color-font-button) 58%, transparent);
    font-size: var(--font-size-p);
    font-weight: 700;
  }

  .tasks-suggestion-book {
    width: 20px;
    height: 18px;
    border: 3px solid currentColor;
    border-block-start: 0;
    border-radius: 2px;
    box-sizing: border-box;
  }

  .tasks-suggestion-content {
    display: grid;
    grid-template-columns: minmax(220px, 1fr) minmax(210px, 0.72fr);
    align-items: center;
    gap: clamp(28px, 7vw, 110px);
    width: min(100%, 680px);
    margin: clamp(22px, 4vh, 42px) auto 0;
  }

  .tasks-suggestion-content > p {
    margin: 0;
    font-size: var(--font-size-p);
    font-weight: 600;
    line-height: 1.25;
  }

  .tasks-suggestion-card {
    display: grid;
    gap: var(--spacing-3);
    padding: 14px 16px;
    border-radius: var(--radius-5);
    background: var(--color-grey-0);
    color: var(--color-font-primary);
    box-shadow: var(--shadow-lg);
  }

  .tasks-suggestion-card strong {
    font-size: var(--font-size-p);
    line-height: 1.22;
  }

  .tasks-suggestion-card span {
    width: fit-content;
    padding: 2px 7px;
    border-radius: var(--radius-full);
    background: var(--color-app-business-end);
    color: var(--color-font-button);
    font-size: var(--font-size-xxs);
  }

  .tasks-suggestion-create {
    display: flex;
    align-items: center;
    gap: var(--spacing-2);
    margin: clamp(18px, 3vh, 34px) auto 0;
    border: 0;
    background: transparent;
    color: color-mix(in srgb, var(--color-font-button) 58%, transparent);
    font: inherit;
    font-size: var(--font-size-p);
    font-weight: 700;
    cursor: pointer;
  }

  .tasks-suggestion-create:hover,
  .tasks-suggestion-create:focus-visible {
    color: var(--color-font-button);
  }

  .tasks-figma-workspace :global(.workspace-daily-inspiration-area) {
    display: none;
  }

  .tasks-figma-workspace :global(.workspace-home-shell) {
    height: auto;
    min-height: 0;
    flex: 1;
    border-radius: 0 0 17px 17px;
    box-shadow: none;
  }

  .tasks-figma-workspace :global(.workspace-center-content.center-content) {
    margin-top: var(--spacing-12);
  }

  .tasks-figma-workspace :global(.workspace-content-slot) {
    margin-top: var(--spacing-12);
  }

  .tasks-figma-workspace :global(.workspace-composer-slot) {
    z-index: var(--z-index-raised-2, 20);
  }

  .task-board-panel {
    display: flex;
    min-height: 0;
    flex: 1;
    flex-direction: column;
    gap: var(--spacing-8);
  }

  .task-workspace-toolbar {
    position: absolute;
    inset-block-start: var(--spacing-8);
    inset-inline: 22px;
    z-index: 2;
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 18px;
  }

  .task-search-cluster {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 32px;
  }

  .task-search-stack {
    display: flex;
    min-width: 0;
    flex-direction: row;
    align-items: center;
    gap: 6px;
  }

  .task-search-link {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
    height: 20px;
    min-height: 20px;
    border: 0;
    background: transparent;
    padding: 0;
    color: var(--color-font-secondary);
    font: inherit;
    font-weight: 700;
    font-size: var(--font-size-p);
    line-height: 20px;
    text-decoration: none;
    box-shadow: none;
  }

  .task-search-link-icon {
    width: 16px;
    height: 16px;
    flex: 0 0 16px;
    background: currentColor;
    -webkit-mask: url('@openmates/ui/static/icons/search.svg') center / contain no-repeat;
    mask: url('@openmates/ui/static/icons/search.svg') center / contain no-repeat;
  }

  .task-search-field {
    display: flex;
    box-sizing: border-box;
    flex-direction: row;
    align-items: center;
    justify-content: flex-end;
    gap: 8px;
    min-height: 32px;
    border: 1px solid var(--color-grey-20);
    border-radius: var(--radius-full);
    background: var(--color-grey-10);
    padding: 4px 10px;
    color: var(--color-font-secondary);
  }

  .search-icon {
    position: relative;
    width: 14px;
    height: 14px;
    border: 2px solid currentColor;
    border-radius: 999px;
    opacity: 0.65;
  }

  .search-icon::after {
    content: '';
    position: absolute;
    right: -6px;
    bottom: -5px;
    width: 7px;
    height: 2px;
    border-radius: 999px;
    background: currentColor;
    transform: rotate(45deg);
  }

  .task-search-field input {
    width: min(100%, 160px);
    border: 0;
    background: transparent;
    padding: 2px 0;
    color: var(--color-font-primary);
    font-size: var(--font-size-small);
    font-weight: 700;
  }

  .task-search-field input::placeholder {
    color: var(--color-font-secondary);
    opacity: 0.9;
  }

  .task-filter-chips {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: flex-end;
    gap: 6px;
  }

  .task-filter-chips button {
    min-width: 0;
    height: 20px;
    min-height: 20px;
    border-radius: 999px;
    background: var(--color-primary);
    color: var(--color-font-button);
    padding: 2px 9px 3px;
    font-size: var(--font-size-xxs);
    font-weight: 500;
    line-height: 15px;
    box-shadow: none;
  }

  .task-filter-chips button.active {
    background: var(--color-button-primary);
  }

  .task-filter-button {
    display: grid;
    width: 40px;
    min-width: 40px;
    height: 40px;
    min-height: 40px;
    flex: 0 0 40px;
    place-items: center;
    border: 0;
    border-radius: var(--radius-full);
    padding: 0;
    margin: 0;
    background: var(--color-grey-0);
    box-shadow: var(--shadow-md);
    filter: none;
    box-sizing: border-box;
    cursor: pointer;
  }

  .task-filter-button span {
    width: 24px;
    height: 24px;
    background: var(--color-primary);
    -webkit-mask: url('@openmates/ui/static/icons/filter.svg') center / contain no-repeat;
    mask: url('@openmates/ui/static/icons/filter.svg') center / contain no-repeat;
  }

  .task-filter-button.active {
    background: var(--color-grey-0);
    box-shadow: var(--shadow-md);
  }

  .task-board-stage {
    position: relative;
    z-index: 1;
    min-height: 0;
  }

  .task-board-detail-layout { display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--spacing-5); min-width: 0; min-height: 0; }
  .task-board-detail-layout.split { grid-template-columns: minmax(0, 1fr) minmax(360px, 40%); }

  .task-board-stage :global(.task-board) {
    grid-template-columns: repeat(5, minmax(230px, 1fr));
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
    border-radius: var(--radius-8);
    background: transparent;
    padding: var(--spacing-8) var(--spacing-6);
  }

  .task-board-stage :global([data-testid='task-column-blocked']) {
    background: var(--color-grey-25);
  }

  .task-board-stage :global(.task-column h2) {
    font-size: var(--font-size-h3);
    line-height: 1.25;
    letter-spacing: -0.02em;
  }

  .task-board-stage :global(.task-card) {
    border-radius: var(--radius-5);
    box-shadow: var(--shadow-md);
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

  .assignee-select select {
    min-height: 44px;
    border: 1px solid var(--color-grey-30);
    border-radius: 18px;
    background: var(--color-grey-0);
    color: var(--color-font-primary);
    padding: 10px 12px;
    font: inherit;
    font-weight: 700;
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

    .tasks-daily-suggestion {
      flex-basis: 182px;
      padding: 16px 22px;
    }

    .compact-task-toolbar {
      margin-inline: var(--spacing-4);
    }

    .compact-task-search {
      width: min(12rem, 64vw);
    }

    .compact-filters {
      display: none;
    }

    .tasks-suggestion-label {
      justify-content: flex-start;
      font-size: var(--font-size-small);
    }

    .tasks-suggestion-content {
      display: block;
      margin-top: 18px;
    }

    .tasks-suggestion-content > p {
      padding-inline-end: 24px;
      font-size: var(--font-size-small);
      line-height: 1.3;
    }

    .tasks-suggestion-card {
      display: none;
    }

    .tasks-suggestion-create {
      margin: 17px 0 0;
      padding: 0;
      font-size: var(--font-size-small);
    }

    .task-workspace-toolbar {
      inset-block-start: var(--spacing-5);
      inset-inline-end: var(--spacing-5);
      inset-inline-start: auto;
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
      grid-template-columns: repeat(5, minmax(15rem, 16rem));
    }

    .task-board-stage :global(.task-column) {
      min-height: auto;
    }

    .task-stats {
      justify-content: flex-start;
    }
  }
</style>
