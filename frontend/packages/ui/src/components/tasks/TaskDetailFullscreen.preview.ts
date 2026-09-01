/**
 * Deterministic preview fixture for the read-only Task detail fullscreen.
 * Includes every Figma-referenced section without API or IndexedDB reads.
 * Access path: /dev/preview/tasks/TaskDetailFullscreen.
 * Product contract: contracts/features/tasks/contract.yml.
 */

import type { UserTaskViewModel } from '../../services/userTaskService';

const createdAt = 1_788_883_200;
const dueAt = 1_792_627_200;

const task = {
  task_id: 'preview-task-detail',
  title: 'Design 3D model',
  description: 'Creating a 3D model for the ball pit. Requirements:\n- fits 2-3 people',
  tags: ['software', 'marketing'],
  latestInstruction: '',
  status: 'todo',
  assigneeType: 'ai',
  primaryChatId: 'preview-chat',
  linkedProjectIds: ['preview-project'],
  planId: 'preview-plan',
  dueAt,
  priority: 4,
  position: 1,
  version: 1,
  createdAt,
  updatedAt: createdAt,
  blockedReasonCode: 'waiting_for_dependency',
  aiExecutionState: null,
  encrypted: {
    task_id: 'preview-task-detail',
    encrypted_title: 'preview-ciphertext',
    status: 'todo',
    assignee_type: 'ai',
    primary_chat_id: 'preview-chat',
    plan_id: 'preview-plan',
    due_at: dueAt,
    priority: 4,
    position: 1,
    version: 1,
    created_at: createdAt,
    updated_at: createdAt,
  },
} satisfies UserTaskViewModel;

const related = {
  projects: [{ id: 'preview-project', title: 'Research project', description: 'Privacy and user interests focused AI research.' }],
  plan: { id: 'preview-plan', title: 'Research launch plan', description: 'Coordinate research, design, and launch.' },
  chat: { id: 'preview-chat', title: '3D model planning' },
  dependencies: [{
    edgeId: 'preview-edge',
    targetRef: 'task:preview-blocker',
    targetKind: 'task' as const,
    targetId: 'preview-blocker',
    targetStatus: 'in_progress',
    satisfied: false,
    title: 'Prepare research brief',
  }],
};

export default { task, related, onClose: () => {} };
