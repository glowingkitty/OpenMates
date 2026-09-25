/**
 * Deterministic five-status task board for Figma and responsive component proof.
 * Access path: /dev/preview/tasks/TaskBoard.
 */

import type { TasksBoardItem, UserTaskStatus, UserTaskViewModel, WorkflowRunTaskProjectionViewModel } from '../../services/userTaskService';
import type { UserPlanStatus, UserPlanViewModel } from '../../services/userPlanService';
import assigneeAvatarUrl from '../../../static/images/placeholders/userprofileimage.jpeg?url';

const createdAt = 1_788_883_200;

function task(id: string, title: string, status: UserTaskStatus, position: number, overrides: Partial<UserTaskViewModel> = {}): UserTaskViewModel {
  return {
    task_id: id,
    title,
    description: '',
    tags: ['OpenMates'],
    latestInstruction: '',
    status,
    assigneeType: 'openmates',
    assigneeIdentity: 'openmates',
    primaryChatId: null,
    externalChat: null,
    linkedProjectIds: [],
    planId: null,
    dueAt: null,
    priority: 3,
    position,
    version: 1,
    createdAt,
    updatedAt: createdAt,
    blockedReasonCode: null,
    blockedReason: '',
    aiExecutionState: null,
    encrypted: {
      task_id: id,
      encrypted_title: 'preview-ciphertext',
      status,
      assignee_type: 'openmates',
      assignee_identity: 'openmates',
      created_at: createdAt,
      updated_at: createdAt,
      position,
    },
    ...overrides,
  };
}

const workflowTask: WorkflowRunTaskProjectionViewModel = {
  task_id: 'preview-workflow',
  source: 'workflow_run',
  projectionKind: 'next_run',
  workflowId: 'weather-report',
  workflowRunId: 'weather-report-run',
  triggerId: 'daily-trigger',
  title: 'Daily Weather Report — July 3 2026',
  description: '',
  tags: [],
  latestInstruction: '',
  status: 'done',
  assigneeType: 'openmates',
  assigneeIdentity: 'openmates',
  primaryChatId: null,
  linkedProjectIds: [],
  dueAt: null,
  priority: 3,
  position: 0,
  version: 0,
  canCancel: false,
  canDelete: false,
  readOnly: true,
};

const tasks: TasksBoardItem[] = [
  task('preview-backlog-1', 'Research how expensive hoverboard motors are to carry 2–3 people', 'backlog', 0, { tags: ['Self driving ballpit'], linkedProjectIds: ['project-ballpit'] }),
  task('preview-backlog-2', 'Teams feature', 'backlog', 1, { tags: ['OpenMates'], linkedProjectIds: ['project-openmates'] }),
  task('preview-todo', 'Design 3D model', 'todo', 0, { tags: ['Self driving ballpit'], linkedProjectIds: ['project-ballpit'], assigneeType: 'user', assigneeIdentity: null }),
  task('preview-active', 'Research open source accounting software alternatives', 'in_progress', 0, { tags: ['OpenMates'], linkedProjectIds: ['project-openmates'], primaryChatId: 'preview-chat' }),
  task('preview-blocked', 'Confirm launch requirements', 'blocked', 0, { tags: [], linkedProjectIds: [], assigneeType: 'unassigned', assigneeIdentity: null, blockedReasonCode: 'needs_user_input', blockedReason: 'Waiting for confirmation.' }),
  workflowTask,
];

function plan(id: string, title: string, status: UserPlanStatus, overrides: Partial<UserPlanViewModel> = {}): UserPlanViewModel {
  return {
    plan_id: id,
    title,
    goal: 'Coordinate the work and verify the outcome before completion.',
    scopeIn: '',
    scopeOut: '',
    userFlows: [],
    assumptions: '',
    openQuestions: '',
    constraints: '',
    decisions: '',
    risks: '',
    status,
    primaryChatId: status === 'completed' ? 'preview-plan-chat' : null,
    linkedProjectIds: ['project-openmates'],
    plannerFocusId: null,
    version: 1,
    createdAt,
    updatedAt: createdAt,
    completedAt: status === 'completed' ? createdAt : null,
    encrypted: {
      plan_id: id,
      encrypted_title: 'preview-ciphertext',
      encrypted_goal: 'preview-ciphertext',
      status,
      primary_chat_id: status === 'completed' ? 'preview-plan-chat' : null,
      linked_project_ids: ['project-openmates'],
      version: 1,
      created_at: createdAt,
      updated_at: createdAt,
      completed_at: status === 'completed' ? createdAt : null,
    },
    ...overrides,
  };
}

const plans: UserPlanViewModel[] = [
  plan('preview-plan-draft', 'Prepare the OpenMates launch plan', 'draft'),
  plan('preview-plan-completed', 'Verify production launch readiness', 'completed'),
];

function report(action: string): void {
  window.dispatchEvent(new CustomEvent('task-board-preview-action', { detail: action }));
}

const defaultProps = {
  tasks,
  plans,
  projectNames: {
    'project-ballpit': 'Self driving ballpit',
    'project-openmates': 'OpenMates',
  },
  assigneeAvatarUrl,
  onMove: (item: TasksBoardItem, status: UserTaskStatus) => report(`move:${item.task_id}:${status}`),
  onMovePlan: (item: UserPlanViewModel, status: UserTaskStatus) => report(`move-plan:${item.plan_id}:${status}`),
  onStartAI: (item: TasksBoardItem) => report(`start:${item.task_id}`),
  onSkip: (item: TasksBoardItem) => report(`skip:${item.task_id}`),
  onDelete: (item: TasksBoardItem) => report(`delete:${item.task_id}`),
  onCancelWorkflowRun: (item: TasksBoardItem) => report(`cancel:${item.task_id}`),
  onSelect: (item: TasksBoardItem) => report(`select:${item.task_id}`),
};

export default defaultProps;

export const variants = {
  emptyDone: {
    ...defaultProps,
    tasks: tasks.filter((item) => item.status !== 'done'),
    plans: plans.filter((item) => item.status !== 'completed'),
  },
};
