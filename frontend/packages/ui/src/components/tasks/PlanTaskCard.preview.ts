/** Deterministic task-board Plan card preview. */

import type { UserPlanViewModel } from '../../services/userPlanService';
import type { UserTaskStatus } from '../../services/userTaskService';

const createdAt = 1_788_883_200;

const plan: UserPlanViewModel = {
  plan_id: 'preview-plan',
  title: 'Prepare the OpenMates launch plan',
  goal: 'Coordinate launch readiness, security checks, and release verification.',
  scopeIn: '',
  scopeOut: '',
  userFlows: [],
  assumptions: '',
  openQuestions: '',
  constraints: '',
  decisions: '',
  risks: '',
  status: 'executing',
  primaryChatId: 'preview-chat',
  linkedProjectIds: ['project-openmates'],
  plannerFocusId: null,
  version: 1,
  createdAt,
  updatedAt: createdAt,
  completedAt: null,
  encrypted: {
    plan_id: 'preview-plan',
    encrypted_title: 'preview-ciphertext',
    encrypted_goal: 'preview-ciphertext',
    status: 'executing',
    primary_chat_id: 'preview-chat',
    linked_project_ids: ['project-openmates'],
    version: 1,
    created_at: createdAt,
    updated_at: createdAt,
  },
};

function report(item: UserPlanViewModel, column: UserTaskStatus): void {
  window.dispatchEvent(new CustomEvent('plan-task-card-preview-action', { detail: `${item.plan_id}:${column}` }));
}

const defaultProps = {
  plan,
  column: 'in_progress' as UserTaskStatus,
  actionId: null,
  onMove: report,
  linkedProjectName: 'OpenMates',
};

export default defaultProps;

export const variants = {
  blocked: {
    ...defaultProps,
    plan: { ...plan, status: 'blocked' as const },
    column: 'blocked' as UserTaskStatus,
  },
  done: {
    ...defaultProps,
    plan: { ...plan, status: 'completed' as const, completedAt: createdAt },
    column: 'done' as UserTaskStatus,
  },
};
