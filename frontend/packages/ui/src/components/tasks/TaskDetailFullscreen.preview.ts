/**
 * Deterministic preview fixture for the read-only Task detail fullscreen.
 * Includes every Figma-referenced section without API or IndexedDB reads.
 * Access path: /dev/preview/tasks/TaskDetailFullscreen.
 * Product contract: contracts/features/tasks/contract.yml.
 */

import type { UserTaskActivityEntry, UserTaskViewModel } from '../../services/userTaskService';

const createdAt = 1_788_883_200;
const dueAt = 1_792_627_200;

const task = {
  task_id: 'preview-task-detail',
  title: 'Design 3D model',
  description: 'Creating a 3D model for the ball pit. Requirements:\n- fits 2-3 people',
  tags: ['software', 'marketing'],
  latestInstruction: '',
  status: 'blocked',
  assigneeType: 'ai',
  primaryChatId: null,
  externalChat: { provider: 'opencode', id: 'ses_preview_task_bridge', title: 'OpenCode task bridge' },
  linkedProjectIds: ['preview-project'],
  planId: 'preview-plan',
  dueAt,
  priority: 4,
  position: 1,
  version: 1,
  createdAt,
  updatedAt: createdAt,
  blockedReasonCode: 'missing_credentials',
  blockedReason: 'A repository write token is required before this task can continue. The credential must be created with repository write access and stored in the approved local secret manager before the verification run can resume.',
  aiExecutionState: null,
  encrypted: {
    task_id: 'preview-task-detail',
    encrypted_title: 'preview-ciphertext',
    status: 'blocked',
    assignee_type: 'ai',
    primary_chat_id: null,
    external_chat_provider: 'opencode',
    external_chat_lookup_hash: 'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc',
    encrypted_external_chat_id: 'preview-ciphertext',
    encrypted_external_chat_title: 'preview-ciphertext',
    encrypted_blocked_reason: 'preview-ciphertext',
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
  chat: null,
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

const activityEntries: UserTaskActivityEntry[] = [{
  entryId: 'preview-activity', taskId: task.task_id, kind: 'lifecycle_update', actorType: 'ai', actorHash: null,
  actorDisplayName: null, actorProfileImageUrl: null, authorHash: null, eventType: 'task_blocked', sourceSurface: 'system',
  createdAt: createdAt + 60, deletedAt: null, deletedByHash: null, deletedByDisplayName: null, embedRefs: [],
}];

export default { task, related, activityEntries, onClose: () => {} };

export const variants = {
  codeFallback: {
    task: {
      ...task,
      blockedReason: '',
      encrypted: { ...task.encrypted, encrypted_blocked_reason: null },
    },
  },
};
