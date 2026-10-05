<!--
  TasksPage.svelte
  Central Tasks V1 workspace. Loads encrypted user tasks, decrypts them on the
  client, and renders a reusable Kanban board for all task statuses.
-->

<script lang="ts">
  import { onMount, tick } from 'svelte';
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
  import { getWorkspaceCacheIdentity } from '../../services/workspaceQueryCache';
  import { listProjects } from '../../services/projectService';
  import {
    blockUserTask,
    completeUserTask,
    createUserTask,
    createTaskMoveSequencer,
    deleteUserTask,
    cancelWorkflowRunTaskProjection,
    extractUserTaskProposals,
    getTaskAssignmentEligibility,
    isWorkflowRunTaskProjectionViewModel,
    listTaskBoardItems,
    peekTaskBoardItems,
    peekUserTask,
    prependTaskBoardItem,
    peekTaskAssignmentEligibility,
    subscribeUserTasks,
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
    peekUserPlans,
    subscribeUserPlans,
    updateUserPlan,
    type UserPlanStatus,
    type UserPlanViewModel,
  } from '../../services/userPlanService';

  type TaskAssigneeChoice = 'user' | 'openmates' | 'codex' | 'unassigned';

  let {
    projectId = null,
    chatId = null,
    compact = false,
    previewTasks = null,
    previewPlans = null,
    previewProjectNames = {},
    previewAssigneeAvatarUrl = null,
    onOpenTask = null,
  }: {
    projectId?: string | null;
    chatId?: string | null;
    compact?: boolean;
    previewTasks?: TasksBoardItem[] | null;
    previewPlans?: UserPlanViewModel[] | null;
    previewProjectNames?: Record<string, string>;
    previewAssigneeAvatarUrl?: string | null;
    onOpenTask?: ((task: UserTaskViewModel, canAssignCodex: boolean, onTaskChange: (task: UserTaskViewModel) => void) => void) | null;
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
  let taskComposerFocused = $state(false);
  let pendingTaskDelete = $state<{ task: TasksBoardItem; request: string; scope: string | null } | null>(null);
  let isExtracting = $state(false);
  let extractedProposals = $state<UserTaskProposal[]>([]);
  let tasksPageWidth = $state(900);
  let tasksWorkspaceWidth = $state(900);
  let searchTerm = $state('');
  let showTaskSearch = $state(false);
  let showDesktopTaskTags = $state(true);
  let showMobileTaskTags = $state(false);
  let selectedWorkflowRunProjection = $state<WorkflowRunTaskProjectionViewModel | null>(null);
  let selectedTask = $state<UserTaskViewModel | null>(null);
  let selectedTaskChange = $state<(updated: UserTaskViewModel) => void>(() => {});
  let taskBoardPanel: HTMLElement | null = $state(null);
  let projectNames = $state<Record<string, string>>({});
  let assigneeAvatarUrl = $state<string | null>(null);
  let featureAvailabilityReady = $derived($featureAvailabilityStore.initialized && $featureAvailabilityStore.disabledById !== null);
  let hasPreviewData = $derived(previewTasks !== null || previewPlans !== null);
  let tasksEnabled = $derived(previewTasks !== null || (featureAvailabilityReady && $featureAvailabilityStore.disabledById?.['platform:tasks'] !== true));
  let plansEnabled = $derived(previewPlans !== null || (!hasPreviewData && featureAvailabilityReady && $featureAvailabilityStore.disabledById?.['platform:plans'] !== true));
  let isCentralTasksWorkspace = $derived(!compact);
  let isNarrowTasksWorkspace = $derived(tasksWorkspaceWidth <= 900);
  let canSplitTaskDetail = $derived(tasksPageWidth >= 1100);
  let showSplitTaskDetail = $derived(isCentralTasksWorkspace && canSplitTaskDetail && !!(selectedTask || selectedWorkflowRunProjection));
  const selectedTaskPreviewRelated = $derived(hasPreviewData && selectedTask ? {
    projects: selectedTask.linkedProjectIds.map((id) => ({ id, title: projectNames[id] || 'Project', description: '' })),
    plan: null,
    chat: null,
    dependencies: [],
  } : undefined);

  const boardPlans = $derived(plans.filter((plan) => plan.status !== 'archived'));
  const greetingName = $derived(formatGreetingName($userProfile.username));
  const taskFilterChips = $derived(resolveTaskFilterChips(tasks));
  const visibleTasks = $derived(filterTasks(tasks, searchTerm));
  const visiblePlans = $derived(filterPlans(boardPlans, searchTerm));
  const isBoardLoading = $derived(isLoading || (plansEnabled && isLoadingPlans));
  let canAssignCodex = $state(false);
  let taskRequestGeneration = 0;
  let planRequestGeneration = 0;
  const runTaskMove = createTaskMoveSequencer();

  function scopeIsCurrent(requestedScope: string | null): boolean {
    return requestedScope === getWorkspaceCacheIdentity();
  }

  function clearSensitiveTaskState(): void {
    tasks = [];
    plans = [];
    title = '';
    description = '';
    taskAssigneeChoice = 'user';
    transcriptText = '';
    correctedTranscriptText = '';
    taskPromptValue = '';
    taskComposerFocused = false;
    extractedProposals = [];
    searchTerm = '';
    selectedTask = null;
    selectedTaskChange = () => {};
    selectedWorkflowRunProjection = null;
    pendingTaskDelete = null;
    canAssignCodex = false;
    isSaving = false;
    isExtracting = false;
    planActionId = null;
    hasLoadError = false;
    projectNames = {};
  }

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

  function handleTaskChange(updated: UserTaskViewModel, requestedScope: string | null): void {
    if (!scopeIsCurrent(requestedScope)) return;
    tasks = tasks.map((candidate) => candidate.task_id === updated.task_id ? updated : candidate);
    if (selectedTask?.task_id === updated.task_id) selectedTask = updated;
    broadcastTasksChanged();
  }

  async function revealTaskBoardPanel(): Promise<void> {
    if (!isCentralTasksWorkspace || !taskBoardPanel || canSplitTaskDetail) return;
    const requestedScope = getWorkspaceCacheIdentity();
    await tick();
    if (!scopeIsCurrent(requestedScope)) return;
    taskBoardPanel?.scrollIntoView({ block: isNarrowTasksWorkspace ? 'start' : 'center', inline: 'nearest', behavior: 'auto' });
  }

  function handleSelectTask(task: TasksBoardItem): void {
    if (isWorkflowRunTaskProjectionViewModel(task) && task.workflowRunId) {
      selectedTask = null;
      selectedWorkflowRunProjection = task;
      void revealTaskBoardPanel();
      return;
    }
    if (!isWorkflowRunTaskProjectionViewModel(task)) {
      selectedWorkflowRunProjection = null;
      if (onOpenTask) {
        const requestedScope = getWorkspaceCacheIdentity();
        onOpenTask(task, canAssignCodex, (updated) => handleTaskChange(updated, requestedScope));
      }
      else {
        const requestedScope = getWorkspaceCacheIdentity();
        selectedTaskChange = (updated) => handleTaskChange(updated, requestedScope);
        selectedTask = task;
        void revealTaskBoardPanel();
      }
    }
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
    const generation = ++taskRequestGeneration;
    const requestedScope = getWorkspaceCacheIdentity();
    const requestedFilters = filters();
    if (!tasksEnabled) {
      tasks = [];
      isLoading = false;
      return;
    }
    const cached = peekTaskBoardItems(requestedFilters);
    if (cached) tasks = cached;
    canAssignCodex = peekTaskAssignmentEligibility() ?? canAssignCodex;
    isLoading = !cached;
    try {
      hasLoadError = false;
      const loaded = await listTaskBoardItems(requestedFilters);
      if (generation !== taskRequestGeneration || !scopeIsCurrent(requestedScope)) return;
      tasks = loaded;
      const eligible = peekTaskAssignmentEligibility() ?? await getTaskAssignmentEligibility();
      if (generation === taskRequestGeneration && scopeIsCurrent(requestedScope)) canAssignCodex = eligible;
    } catch (error) {
      if (generation !== taskRequestGeneration || !scopeIsCurrent(requestedScope)) return;
      hasLoadError = peekTaskBoardItems(requestedFilters) === undefined;
      console.error('[TasksPage] Failed to load tasks:', error);
      notificationStore.error('Failed to load tasks');
    } finally {
      if (generation === taskRequestGeneration && scopeIsCurrent(requestedScope)) isLoading = false;
    }
  }

  async function refreshTaskPresentation(): Promise<void> {
    if (previewTasks !== null) {
      projectNames = previewProjectNames;
      assigneeAvatarUrl = previewAssigneeAvatarUrl;
      return;
    }
    const requestedScope = getWorkspaceCacheIdentity();
    try {
      const projects = await listProjects();
      if (!scopeIsCurrent(requestedScope)) return;
      projectNames = Object.fromEntries(projects.map((project) => [project.project_id, project.name]));
    } catch (error) {
      if (!scopeIsCurrent(requestedScope)) return;
      console.error('[TasksPage] Failed to load linked project labels:', error);
      projectNames = {};
    }
  }

  async function refreshPlans(): Promise<void> {
    const generation = ++planRequestGeneration;
    const requestedScope = getWorkspaceCacheIdentity();
    if (!plansEnabled) {
      plans = [];
      isLoadingPlans = false;
      return;
    }
    const planFilters = { projectId: projectId ?? undefined, chatId: chatId ?? undefined };
    const cached = peekUserPlans(planFilters);
    if (cached) plans = cached;
    isLoadingPlans = !cached;
    try {
      const loaded = await listUserPlans(planFilters);
      if (generation === planRequestGeneration && scopeIsCurrent(requestedScope)) plans = loaded;
    } catch (error) {
      if (generation !== planRequestGeneration || !scopeIsCurrent(requestedScope)) return;
      console.error('[TasksPage] Failed to load plans:', error);
    } finally {
      if (generation === planRequestGeneration && scopeIsCurrent(requestedScope)) isLoadingPlans = false;
    }
  }

  async function handleCreateTask(): Promise<void> {
    const trimmedTitle = title.trim();
    if (!trimmedTitle || isSaving) return;
    if (taskAssigneeChoice === 'codex' && !canAssignCodex) {
      notificationStore.error('Codex must create its first task before it can be assigned work.');
      return;
    }
    const requestedScope = getWorkspaceCacheIdentity();
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
      if (!scopeIsCurrent(requestedScope)) return;
      tasks = prependTaskBoardItem(tasks, task);
      broadcastTasksChanged();
      title = '';
      description = '';
      taskAssigneeChoice = 'user';
      notificationStore.success(assigneeSuccessLabel(selectedAssignee));
    } catch (error) {
      if (!scopeIsCurrent(requestedScope)) return;
      console.error('[TasksPage] Failed to create task:', error);
      notificationStore.error('Failed to create task');
    } finally {
      if (scopeIsCurrent(requestedScope)) isSaving = false;
    }
  }

  async function handleTaskPromptSubmit(value: string): Promise<boolean> {
    if (!tasksEnabled || isSaving) return false;
    const requestedScope = getWorkspaceCacheIdentity();
    if (/\bexternal[-\s]?ai\b/i.test(value) && !/\bcodex\b/i.test(value) && /\b(assign|start|handoff|hand off)\b/i.test(value)) {
      notificationStore.error('Name Codex explicitly when assigning work to it.');
      return false;
    }
    const mentionedTask = findTaskMention(value);
    const normalized = value.toLowerCase();
    if (/\b(delete|remove)\b/.test(normalized)) {
      if (!mentionedTask) {
        notificationStore.error('Name the task to delete first.');
        return false;
      }
      pendingTaskDelete = { task: mentionedTask, request: value, scope: requestedScope };
      taskPromptValue = '';
      return true;
    }

    if (mentionedTask && !isWorkflowRunTaskProjectionViewModel(mentionedTask)) {
      const renamedTitle = parseRenameTitle(value);
      const description = parseDescriptionUpdate(value);
      const targetAssignee = parseAssigneeUpdate(value);
      const targetStatus = parseTaskStatus(value);
      if (renamedTitle) {
        if (!await updateTaskFromPrompt(mentionedTask, { title: renamedTitle }, 'Task renamed')) return false;
        if (!scopeIsCurrent(requestedScope)) return false;
        taskPromptValue = '';
        return true;
      }
      if (description) {
        if (!await updateTaskFromPrompt(mentionedTask, { description }, 'Task details updated')) return false;
        if (!scopeIsCurrent(requestedScope)) return false;
        taskPromptValue = '';
        return true;
      }
      if (targetAssignee) {
        if (targetAssignee === 'codex' && !canAssignCodex) {
          notificationStore.error('Codex must create its first task before it can be assigned work.');
          return false;
        } else if (targetAssignee === 'openmates') {
          if (!await handleStartAI(mentionedTask)) return false;
        } else {
          if (!await updateTaskFromPrompt(mentionedTask, assignmentPatchForTask(mentionedTask, targetAssignee), targetAssignee === 'codex' ? 'Task assigned to Codex' : 'Task assignment updated')) return false;
        }
        if (!scopeIsCurrent(requestedScope)) return false;
        taskPromptValue = '';
        return true;
      }
      if (targetStatus) {
        if (!await handleMove(mentionedTask, targetStatus)) return false;
        if (!scopeIsCurrent(requestedScope)) return false;
        taskPromptValue = '';
        return true;
      }
    }

    if (looksLikeTaskManagementRequest(value) && !looksLikeTaskCreationRequest(value)) {
      notificationStore.error('I could not find a matching task. Include the exact task title.');
      return false;
    }

    if (!await createTaskFromPrompt(value)) return false;
    if (!scopeIsCurrent(requestedScope)) return false;
    taskPromptValue = '';
    return true;
  }

  async function createTaskFromPrompt(value: string): Promise<boolean> {
    if (requestedCodexAssignment(value) && !canAssignCodex) {
      notificationStore.error('Codex must create its first task before it can be assigned work.');
      return false;
    }
    const requestedScope = getWorkspaceCacheIdentity();
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
      if (!scopeIsCurrent(requestedScope)) return false;
      tasks = prependTaskBoardItem(tasks, task);
      broadcastTasksChanged();
      notificationStore.success(assigneeSuccessLabel(selectedAssignee));
      return true;
    } catch (error) {
      if (!scopeIsCurrent(requestedScope)) return false;
      console.error('[TasksPage] Failed to create task from prompt:', error);
      notificationStore.error('Failed to create task');
      return false;
    } finally {
      if (scopeIsCurrent(requestedScope)) isSaving = false;
    }
  }

  async function updateTaskFromPrompt(task: UserTaskViewModel, patch: Parameters<typeof updateUserTask>[1], successMessage: string): Promise<boolean> {
    const requestedScope = getWorkspaceCacheIdentity();
    try {
      const updated = await updateUserTask(task, patch);
      if (!scopeIsCurrent(requestedScope)) return false;
      tasks = tasks.map((candidate) => candidate.task_id === updated.task_id ? updated : candidate);
      broadcastTasksChanged();
      notificationStore.success(successMessage);
      return true;
    } catch (error) {
      if (!scopeIsCurrent(requestedScope)) return false;
      console.error('[TasksPage] Failed to update task from prompt:', error);
      notificationStore.error('Failed to update task');
      return false;
    }
  }

  async function confirmTaskDelete(): Promise<void> {
    if (!pendingTaskDelete) return;
    if (!scopeIsCurrent(pendingTaskDelete.scope)) { pendingTaskDelete = null; return; }
    const task = pendingTaskDelete.task;
    pendingTaskDelete = null;
    await handleDelete(task);
  }

  function handleStartTaskInspiration(inspiration: DailyInspiration): void {
    taskPromptValue = inspiration.phrase;
    taskComposerFocused = true;
    title = inspiration.phrase;
    description = inspiration.assistant_response ?? '';
  }

  async function handleExtractTasks(): Promise<void> {
    const correctedText = (correctedTranscriptText || transcriptText).trim();
    if (!correctedText || isExtracting) return;
    const requestedScope = getWorkspaceCacheIdentity();
    isExtracting = true;
    try {
      const proposals = await extractUserTaskProposals({
        correctedText,
        contextChatId: chatId,
        projectIds: projectId ? [projectId] : [],
      });
      if (!scopeIsCurrent(requestedScope)) return;
      extractedProposals = proposals;
      if (extractedProposals.length === 0) {
        notificationStore.error('No task proposals found');
      }
    } catch (error) {
      if (!scopeIsCurrent(requestedScope)) return;
      console.error('[TasksPage] Failed to extract task proposals:', error);
      notificationStore.error('Failed to extract task proposals');
    } finally {
      if (scopeIsCurrent(requestedScope)) isExtracting = false;
    }
  }

  async function handleAcceptProposal(proposal: UserTaskProposal): Promise<void> {
    if (isSaving) return;
    const requestedScope = getWorkspaceCacheIdentity();
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
      if (!scopeIsCurrent(requestedScope)) return;
      tasks = prependTaskBoardItem(tasks, task);
      extractedProposals = extractedProposals.filter((candidate) => candidate !== proposal);
      broadcastTasksChanged();
      notificationStore.success('Task created from transcript');
    } catch (error) {
      if (!scopeIsCurrent(requestedScope)) return;
      console.error('[TasksPage] Failed to accept task proposal:', error);
      notificationStore.error('Failed to create task from proposal');
    } finally {
      if (scopeIsCurrent(requestedScope)) isSaving = false;
    }
  }

  function handleDismissProposal(proposal: UserTaskProposal): void {
    extractedProposals = extractedProposals.filter((candidate) => candidate !== proposal);
  }

  function firstPositionIn(status: UserTaskStatus, movedTaskId: string, items: TasksBoardItem[]): number {
    const positions = items.filter((candidate) => candidate.task_id !== movedTaskId && candidate.status === status).map((candidate) => candidate.position);
    return Math.min(0, ...positions) - 1;
  }

  async function persistMove(task: UserTaskViewModel, status: UserTaskStatus, position: number, requestedScope: string | null): Promise<UserTaskViewModel | null> {
    if (requestedScope !== getWorkspaceCacheIdentity()) return null;
    let updated = task;
    if (status === 'done' && task.status !== 'done') updated = await completeUserTask(task);
    else if (status === 'blocked' && task.status !== 'blocked') updated = await blockUserTask(task);
    else if (task.status === 'blocked' && status !== 'blocked') updated = await unblockUserTask(task);
    else if (status === 'backlog' && task.status !== 'backlog') updated = await skipUserTask(task);
    if (requestedScope !== getWorkspaceCacheIdentity()) return null;

    const [moved] = await reorderUserTasks([{ task: updated, status, position }]);
    if (!moved) throw new Error('Task reorder returned no task');
    return moved;
  }

  async function handleMove(task: TasksBoardItem, status: UserTaskStatus): Promise<boolean> {
    if (isWorkflowRunTaskProjectionViewModel(task)) return false;
    const requestedScope = getWorkspaceCacheIdentity();
    let succeeded = false;
    await runTaskMove(task.task_id, async () => {
      if (requestedScope !== getWorkspaceCacheIdentity()) return;
      const displayed = tasks.find((candidate) => candidate.task_id === task.task_id);
      if (!displayed || isWorkflowRunTaskProjectionViewModel(displayed)) return;
      const cached = peekUserTask(task.task_id);
      const current = cached && (cached.version > displayed.version || (cached.version === displayed.version && cached.updatedAt > displayed.updatedAt))
        ? cached : displayed;
      if (current.status === status) { succeeded = true; return; }
      succeeded = await persistBoardMove(current, status, requestedScope);
    });
    return succeeded;
  }

  async function persistBoardMove(task: UserTaskViewModel, status: UserTaskStatus, requestedScope: string | null): Promise<boolean> {
    const scopeIsCurrent = () => requestedScope === getWorkspaceCacheIdentity();
    if (!scopeIsCurrent()) return false;
    const previous = tasks;
    const position = firstPositionIn(status, task.task_id, previous);
    tasks = tasks.map((candidate) => candidate.task_id === task.task_id ? { ...candidate, status, position } : candidate);
    try {
      let updated: UserTaskViewModel | null;
      try {
        updated = await persistMove(task, status, position, requestedScope);
      } catch (error) {
        if (!scopeIsCurrent()) return false;
        if (!(error instanceof Error) || !error.message.includes('Tasks API failed (409)')) throw error;
        // Another client may have changed this task since the board loaded.
        const latest = await listTaskBoardItems(filters(), { force: true });
        if (!scopeIsCurrent()) return false;
        const current = latest.find((candidate) => candidate.task_id === task.task_id);
        if (!current || isWorkflowRunTaskProjectionViewModel(current)) throw error;
        tasks = latest.map((candidate) => candidate.task_id === task.task_id ? { ...candidate, status, position } : candidate);
        updated = await persistMove(current, status, position, requestedScope);
      }
      if (!scopeIsCurrent() || !updated) return false;
      tasks = tasks.map((candidate) => candidate.task_id === updated.task_id ? updated : candidate);
      broadcastTasksChanged();
      return true;
    } catch (error) {
      if (!scopeIsCurrent()) return false;
      try {
        const latest = await listTaskBoardItems(filters(), { force: true });
        if (!scopeIsCurrent()) return false;
        tasks = latest;
      } catch {
        if (!scopeIsCurrent()) return false;
        tasks = previous;
      }
      if (!scopeIsCurrent()) return false;
      console.error('[TasksPage] Failed to update task:', error);
      notificationStore.error('Failed to update task');
      return false;
    }
  }

  async function handleSkip(task: TasksBoardItem): Promise<void> {
    if (isWorkflowRunTaskProjectionViewModel(task)) return;
    const requestedScope = getWorkspaceCacheIdentity();
    const previous = tasks;
    tasks = tasks.map((candidate) => candidate.task_id === task.task_id ? { ...candidate, status: 'backlog' } : candidate);
    try {
      const updated = await skipUserTask(task);
      if (requestedScope !== getWorkspaceCacheIdentity()) return;
      tasks = tasks.map((candidate) => candidate.task_id === updated.task_id ? updated : candidate);
      broadcastTasksChanged();
    } catch (error) {
      if (requestedScope !== getWorkspaceCacheIdentity()) return;
      tasks = previous;
      console.error('[TasksPage] Failed to skip task:', error);
      notificationStore.error('Failed to skip task');
    }
  }

  async function handleDelete(task: TasksBoardItem): Promise<void> {
    if (isWorkflowRunTaskProjectionViewModel(task) && !task.canDelete) return;
    const requestedScope = getWorkspaceCacheIdentity();
    const previous = tasks;
    tasks = tasks.filter((candidate) => candidate.task_id !== task.task_id);
    try {
      await deleteUserTask(task);
      if (!scopeIsCurrent(requestedScope)) return;
      broadcastTasksChanged();
      notificationStore.success(isWorkflowRunTaskProjectionViewModel(task) ? 'Next workflow run skipped' : 'Task deleted');
    } catch (error) {
      if (!scopeIsCurrent(requestedScope)) return;
      tasks = previous;
      console.error('[TasksPage] Failed to delete task:', error);
      notificationStore.error('Failed to delete task');
    }
  }

  async function handleStartAI(task: TasksBoardItem): Promise<boolean> {
    if (isWorkflowRunTaskProjectionViewModel(task)) return false;
    const requestedScope = getWorkspaceCacheIdentity();
    try {
      const updated = await startUserTaskWithAI(task);
      if (!scopeIsCurrent(requestedScope)) return false;
      tasks = tasks.map((candidate) => candidate.task_id === updated.task_id ? updated : candidate);
      broadcastTasksChanged();
      notificationStore.success('AI task queued');
      return true;
    } catch (error) {
      if (!scopeIsCurrent(requestedScope)) return false;
      console.error('[TasksPage] Failed to start AI task:', error);
      notificationStore.error('Failed to start AI task');
      return false;
    }
  }

  async function handleCancelWorkflowRun(task: TasksBoardItem): Promise<void> {
    if (!isWorkflowRunTaskProjectionViewModel(task)) return;
    const requestedScope = getWorkspaceCacheIdentity();
    try {
      await cancelWorkflowRunTaskProjection(task);
      if (!scopeIsCurrent(requestedScope)) return;
      await refreshTasks();
      if (!scopeIsCurrent(requestedScope)) return;
      notificationStore.success('Workflow run cancellation requested');
    } catch (error) {
      if (!scopeIsCurrent(requestedScope)) return;
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
    const requestedScope = getWorkspaceCacheIdentity();
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
      if (!scopeIsCurrent(requestedScope)) return;
      plans = plans.map((candidate) => candidate.plan_id === updated.plan_id ? updated : candidate);
      broadcastPlansChanged();
      notificationStore.success(status === 'done' ? 'Plan completed' : 'Plan updated');
    } catch (error) {
      if (!scopeIsCurrent(requestedScope)) return;
      plans = previous;
      console.error('[TasksPage] Failed to move plan:', error);
      notificationStore.error(status === 'done' ? 'Plan still has blockers before completion' : error instanceof Error ? error.message : 'Failed to update plan');
    } finally {
      if (scopeIsCurrent(requestedScope)) planActionId = null;
    }
  }

  onMount(() => {
    if (hasPreviewData) return;
    let displayedScope = getWorkspaceCacheIdentity();
    let displayedUserId = $userProfile.user_id;
    const clearOnScopeChange = () => {
      const scope = getWorkspaceCacheIdentity();
      if (scope === displayedScope) return;
      displayedScope = scope;
      const userId = $userProfile.user_id;
      taskRequestGeneration += 1;
      planRequestGeneration += 1;
      clearSensitiveTaskState();
      if (userId !== displayedUserId) assigneeAvatarUrl = null;
      displayedUserId = userId;
      if (scope) {
        void refreshTasks();
        void refreshPlans();
        void refreshTaskPresentation();
      }
    };
    const unsubscribeTasks = subscribeUserTasks(() => {
      clearOnScopeChange();
      const cached = peekTaskBoardItems(filters());
      if (cached) tasks = cached;
      canAssignCodex = peekTaskAssignmentEligibility() ?? canAssignCodex;
    });
    const unsubscribePlans = subscribeUserPlans(() => {
      clearOnScopeChange();
      const cached = peekUserPlans({ projectId: projectId ?? undefined, chatId: chatId ?? undefined });
      if (cached) plans = cached;
    });
    void initializeFeatureAvailability();
    if (!isCentralTasksWorkspace) {
      void loadDefaultInspirations({ surface: 'tasks', allowIndexedDB: false });
    }
    void refreshTaskPresentation();
    return () => { unsubscribeTasks(); unsubscribePlans(); };
  });

  $effect(() => {
    const profileImageUrl = $userProfile.profile_image_url;
    const userId = $userProfile.user_id;
    const requestedScope = getWorkspaceCacheIdentity();
    if (hasPreviewData) {
      projectNames = previewProjectNames;
      assigneeAvatarUrl = previewAssigneeAvatarUrl;
      return;
    }
    if (!userId) {
      assigneeAvatarUrl = null;
      return;
    }
    let cancelled = false;
    getProfileImageBlobUrl(profileImageUrl, getApiUrl(), userId).then((resolved) => {
      if (!cancelled && scopeIsCurrent(requestedScope)) assigneeAvatarUrl = resolved;
    });
    return () => { cancelled = true; };
  });

  $effect(() => {
    const userId = $userProfile.user_id;
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
    if (!userId) {
      taskRequestGeneration += 1;
      planRequestGeneration += 1;
      clearSensitiveTaskState();
      isLoading = false;
      isLoadingPlans = false;
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
      <h2>Tasks unavailable</h2>
      <p>Tasks and Plans are disabled on this server.</p>
    </div>
  </section>
{:else}
<section class="tasks-page" class:compact class:figma-layout={isCentralTasksWorkspace} data-testid={compact ? 'project-tasks-page' : 'tasks-page'} bind:clientWidth={tasksPageWidth}>

  {#if isCentralTasksWorkspace}
    <div class="tasks-workspace-layout" class:split={showSplitTaskDetail} data-testid="tasks-workspace-layout">
    <section class="tasks-figma-workspace" data-testid="tasks-figma-workspace" aria-label="Tasks workspace" bind:clientWidth={tasksWorkspaceWidth}>
      <WorkspaceHomeShell
        composerFocused={taskComposerFocused}
        onComposerDismiss={() => { taskComposerFocused = false; }}
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
      <svelte:fragment slot="top-right">
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
      </svelte:fragment>
      <section class="task-board-panel" data-testid="tasks-board-workspace" aria-label="Tasks board" bind:this={taskBoardPanel}>
        {#if isBoardLoading}
          <div class="tasks-state" data-testid="tasks-loading">Loading tasks...</div>
        {:else if hasLoadError}
          <div class="tasks-state" data-testid="tasks-load-error">
            <p>Tasks could not be loaded.</p>
            <button type="button" onclick={() => void refreshTasks()}>Retry</button>
          </div>
        {:else}
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
        {/if}
      </section>
      <svelte:fragment slot="composer">
        <WorkspacePromptComposer
          surface="tasks"
          bind:value={taskPromptValue}
          bind:focusActive={taskComposerFocused}
          placeholder="Click to add or update tasks"
          submitLabel="Send"
          submittingLabel="Saving..."
          disabled={!tasksEnabled}
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
    {#if showSplitTaskDetail}
      <div class="task-detail-panel" data-testid="task-detail-panel">
        {#if selectedTask}
          <TaskDetailFullscreen
            task={selectedTask}
            {canAssignCodex}
            presentation="split"
            related={selectedTaskPreviewRelated}
            activityEntries={hasPreviewData ? [] : undefined}
            onTaskChange={selectedTaskChange}
            onClose={() => { selectedTask = null; }}
          />
        {:else if selectedWorkflowRunProjection}
          <WorkflowRunTaskDetail
            projection={selectedWorkflowRunProjection}
            presentation="split"
            onClose={() => { selectedWorkflowRunProjection = null; }}
          />
        {/if}
      </div>
    {/if}
    </div>
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

  <div class="compact-task-background" class:dimmed={compact && taskComposerFocused} inert={compact && taskComposerFocused} data-testid={compact ? 'project-task-background' : undefined}>
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
  </div>
  {#if compact}
    {#if taskComposerFocused}<button type="button" class="compact-task-backdrop" data-testid="project-task-composer-backdrop" aria-label="Dismiss task editor" onpointerdown={(event) => event.preventDefault()} onclick={() => { taskComposerFocused = false; }}></button>{/if}
    <div class="compact-task-composer" data-testid="project-task-composer-shell">
      <WorkspacePromptComposer
        surface="tasks"
        bind:value={taskPromptValue}
        bind:focusActive={taskComposerFocused}
        placeholder="Click here to add or update tasks"
        submitLabel="Send"
        submittingLabel="Saving..."
        disabled={!tasksEnabled}
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
  {#if selectedTask && (!isCentralTasksWorkspace || !canSplitTaskDetail)}
    <TaskDetailFullscreen task={selectedTask} {canAssignCodex} related={selectedTaskPreviewRelated} activityEntries={hasPreviewData ? [] : undefined} onTaskChange={selectedTaskChange} onClose={() => { selectedTask = null; }} />
  {/if}
  {#if selectedWorkflowRunProjection && (!isCentralTasksWorkspace || !canSplitTaskDetail)}
    <WorkflowRunTaskDetail projection={selectedWorkflowRunProjection} presentation="overlay" onClose={() => { selectedWorkflowRunProjection = null; }} />
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

  .tasks-workspace-layout,
  .tasks-figma-workspace :global(.workspace-home-shell) {
    flex: 1;
    min-height: 0;
  }

  .tasks-workspace-layout {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: var(--spacing-5);
    min-width: 0;
    height: 100%;
  }

  .tasks-workspace-layout.split {
    grid-template-columns: minmax(340px, 32%) minmax(0, 1fr);
  }

  .tasks-page.compact {
    padding: 0;
    overflow: visible;
  }

  .compact-task-background { visibility: visible; transition: opacity var(--duration-normal) var(--easing-default), visibility 0s; }
  .compact-task-background.dimmed { opacity: 0; visibility: hidden; transition-delay: 0s, var(--duration-normal); }
  @media (prefers-reduced-motion: reduce) {
    .compact-task-background, .compact-task-background.dimmed { transition: none; }
  }
  .compact-task-backdrop { position: absolute; inset: 0; z-index: 3; width: 100%; height: 100%; min-width: 0; margin: 0; padding: 0; border: 0; border-radius: 0; box-shadow: none; filter: none; scale: none; transform: none; transition: none; background: transparent; cursor: default; }
  .compact-task-backdrop:hover, .compact-task-backdrop:active { background: transparent; scale: none; transform: none; filter: none; }

  @media (prefers-reduced-motion: reduce) {
    .compact-task-background { transition: none; }
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
    height: 100dvh;
    max-height: 100%;
    box-sizing: border-box;
  }

  .task-create-card,
  .task-extract-card,
  .tasks-state {
    border-radius: 32px;
    border: 1px solid var(--color-grey-20);
    background: linear-gradient(135deg, var(--color-grey-10), var(--color-grey-0));
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.08);
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

  .task-detail-panel {
    position: relative;
    min-width: 0;
    min-height: 0;
    height: 100%;
    overflow: hidden;
    border-radius: 17px;
  }

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

  h2,
  p {
    margin: 0;
  }

  .tasks-state p {
    max-width: 650px;
    margin-top: 12px;
    color: var(--color-font-secondary);
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
    .task-create-card {
      grid-template-columns: 1fr;
      flex-direction: column;
    }

    .tasks-figma-workspace {
      min-height: 0;
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
  }
</style>
