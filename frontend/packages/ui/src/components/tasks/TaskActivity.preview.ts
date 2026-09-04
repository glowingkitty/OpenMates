/**
 * Deterministic Task Activity preview with no API or IndexedDB dependency.
 * Shows stable chronological comments, client attribution, lifecycle events,
 * and deletion tombstones while keeping composer interactions functional.
 * Access path: /dev/preview/tasks/TaskActivity?chrome=0.
 */

import type { CreateUserTaskActivityInput, UserTaskActivityEntry, UserTaskViewModel } from '../../services/userTaskService';

const createdAt = 1_788_883_200;
const avatar = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="64" height="64"%3E%3Crect width="64" height="64" rx="32" fill="%236c5ce7"/%3E%3Ccircle cx="32" cy="25" r="12" fill="white"/%3E%3Cpath d="M12 58c2-14 11-21 20-21s18 7 20 21" fill="white"/%3E%3C/svg%3E';

const task = {
  task_id: 'preview-task-activity', title: 'Prepare launch brief', description: '', tags: [], latestInstruction: '',
  status: 'in_progress', assigneeType: 'user', primaryChatId: null, externalChat: null, linkedProjectIds: [], planId: null,
  dueAt: null, priority: 2, position: 1, version: 1, createdAt, updatedAt: createdAt, blockedReasonCode: null,
  blockedReason: '', aiExecutionState: null,
  encrypted: { task_id: 'preview-task-activity', encrypted_task_key: 'preview-key', encrypted_title: 'preview-ciphertext', status: 'in_progress', assignee_type: 'user', version: 1, created_at: createdAt, updated_at: createdAt },
} satisfies UserTaskViewModel;

const base: Pick<UserTaskActivityEntry, 'taskId' | 'actorHash' | 'authorHash' | 'deletedAt' | 'deletedByHash' | 'deletedByDisplayName' | 'embedRefs'> = {
  taskId: task.task_id,
  actorHash: 'actor-hash',
  authorHash: 'actor-hash',
  deletedAt: null,
  deletedByHash: null,
  deletedByDisplayName: null,
  embedRefs: [],
};

const initialEntries: UserTaskActivityEntry[] = [
  { ...base, entryId: 'cli', kind: 'comment', actorType: 'user', actorDisplayName: 'Sam Rivera', actorProfileImageUrl: avatar, eventType: 'comment_added', sourceSurface: 'cli', createdAt: createdAt + 20, message: 'Validated the rollout checklist from the terminal.' },
  { ...base, entryId: 'web', kind: 'comment', actorType: 'user', actorDisplayName: 'Alice Weber', actorProfileImageUrl: avatar, eventType: 'comment_added', sourceSurface: 'web', createdAt: createdAt + 10, message: 'I added the launch milestones and owner notes.' },
  { ...base, entryId: 'sdk', kind: 'comment', actorType: 'user', actorDisplayName: 'Sam Rivera', actorProfileImageUrl: avatar, eventType: 'comment_added', sourceSurface: 'sdk_npm', createdAt: createdAt + 30, message: 'Synced the external release status.' },
  { ...base, entryId: 'mate', kind: 'comment', actorType: 'ai', actorDisplayName: null, actorProfileImageUrl: null, eventType: 'comment_added', sourceSurface: 'system', createdAt: createdAt + 40, message: 'OpenMates completed the dependency review.' },
  { ...base, entryId: 'lifecycle', kind: 'lifecycle_update', actorType: 'system', actorDisplayName: null, actorProfileImageUrl: null, eventType: 'task_started', sourceSurface: 'system', createdAt: createdAt + 50 },
  { ...base, entryId: 'deleted-user', kind: 'tombstone', actorType: 'user', actorDisplayName: 'Alice Weber', actorProfileImageUrl: avatar, eventType: 'comment_deleted', sourceSurface: 'web', createdAt: createdAt + 60, deletedAt: createdAt + 70, deletedByDisplayName: 'Sam Rivera' },
  { ...base, entryId: 'deleted-mate', kind: 'tombstone', actorType: 'ai', actorDisplayName: null, actorProfileImageUrl: null, eventType: 'comment_deleted', sourceSurface: 'web', createdAt: createdAt + 80, deletedAt: createdAt + 90, deletedByDisplayName: 'Alice Weber' },
];

async function onCreate(input: CreateUserTaskActivityInput): Promise<UserTaskActivityEntry> {
  return {
    ...base,
    entryId: 'created-preview-comment',
    kind: 'comment',
    actorType: 'user',
    actorDisplayName: 'Alice Weber',
    actorProfileImageUrl: avatar,
    eventType: 'comment_added',
    sourceSurface: 'web',
    createdAt: createdAt + 100,
    message: input.message.trim() || 'First line\nSecond line',
  };
}

async function onDelete(entryId: string): Promise<UserTaskActivityEntry> {
  const original = initialEntries.find((entry) => entry.entryId === entryId) ?? initialEntries[0];
  return { ...original, kind: 'tombstone', message: undefined, embedKeyMaterial: undefined, embedRefs: [], deletedAt: createdAt + 110, deletedByDisplayName: 'Alice Weber' };
}

export default { task, teamId: 'preview-team', initialEntries, onCreate, onDelete };

export const variants = {
  uploading: { task, teamId: 'preview-team', initialEntries, previewProcessingState: 'uploading', onCreate, onDelete },
  transcribing: { task, teamId: 'preview-team', initialEntries, previewProcessingState: 'transcribing', onCreate, onDelete },
  error: { task, teamId: 'preview-team', initialEntries, previewProcessingState: 'error', onCreate, onDelete },
};
