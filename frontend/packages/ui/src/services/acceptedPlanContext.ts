/** Existing approved Plan context for one foreground request; no durable plaintext. */
import { getFreshUserPlan, listFreshUserPlanRecords, type EncryptedUserPlanRecord, type UserPlanViewModel } from './userPlanService';
import { listUserTasks } from './userTaskService';
import { getWorkspaceCacheIdentity } from './workspaceQueryCache';

export interface AcceptedPlanContext {
  plan_id: string;
  version: number;
  approved_revision_id: string;
  summary: string;
  linked_task_id?: string;
}

const ACTIVE_PLAN_STATUSES = new Set(['active', 'executing', 'running_checks', 'blocked']);
const OPEN_TASK_STATUSES = new Set(['todo', 'backlog', 'in_progress', 'blocked', 'pending']);
const MAX_PLAN_CANDIDATES = 24;
const MAX_SELECTED_READS = 4;

function accepted(record: EncryptedUserPlanRecord): boolean {
  return ACTIVE_PLAN_STATUSES.has(record.status) && record.approval_state === 'approved'
    && typeof record.approved_revision_id === 'string' && !!record.approved_revision_id
    && record.submitted_revision_id === record.approved_revision_id
    && Number.isSafeInteger(record.version) && (record.version ?? 0) >= 1;
}

/** Keep the approved goal, both scope boundaries and constraints in fixed order. */
export function acceptedPlanSummary(plan: UserPlanViewModel): string {
  const text = (value: string, limit: number) => value.replace(/\s+/g, ' ').trim().slice(0, limit);
  return [`Plan: ${text(plan.title, 200)}`, `Goal: ${text(plan.goal, 1_200)}`,
    `In scope: ${text(plan.scopeIn, 900)}`, `Out of scope: ${text(plan.scopeOut, 600)}`,
    `Constraints: ${text(plan.constraints, 900)}`].join('\n').slice(0, 4_000);
}

export async function collectAcceptedPlanContext(input: { chatId: string; teamId?: string | null }): Promise<AcceptedPlanContext | null> {
  const scope = getWorkspaceCacheIdentity();
  if (!scope || !input.chatId) return null;
  const collected = await Promise.allSettled([
    listFreshUserPlanRecords({ chatId: input.chatId, activeOnly: true, limit: 12 }, input.teamId),
    // The existing active_only listing excludes running_checks; retain its
    // established lifecycle semantics rather than changing the API here.
    listFreshUserPlanRecords({ chatId: input.chatId, status: 'running_checks', limit: 12 }, input.teamId),
    listUserTasks({ chatId: input.chatId, ...(input.teamId ? { teamId: input.teamId } : {}) }),
  ]);
  if (scope !== getWorkspaceCacheIdentity()) return null;
  const records = collected.slice(0, 2).flatMap((result) => result.status === 'fulfilled'
    ? result.value as EncryptedUserPlanRecord[] : []).filter((record) => record.primary_chat_id === input.chatId && accepted(record))
    .sort((a, b) => b.updated_at - a.updated_at || a.plan_id.localeCompare(b.plan_id)).slice(0, MAX_PLAN_CANDIDATES);
  const tasks = collected[2].status === 'fulfilled' ? collected[2].value : [];
  const links = tasks.filter((task) => task.primaryChatId === input.chatId && task.planId && OPEN_TASK_STATUSES.has(task.status))
    .sort((a, b) => b.updatedAt - a.updatedAt || a.task_id.localeCompare(b.task_id)).slice(0, MAX_PLAN_CANDIDATES);
  const candidates = [...records.map((record) => ({ planId: record.plan_id, taskId: undefined as string | undefined })),
    ...links.map((task) => ({ planId: task.planId!, taskId: task.task_id }))];
  const seen = new Set<string>();
  let reads = 0;
  for (const candidate of candidates) {
    if (seen.has(candidate.planId)) continue;
    seen.add(candidate.planId);
    if (reads++ >= MAX_SELECTED_READS) break;
    try {
      const plan = await getFreshUserPlan(candidate.planId, input.teamId);
      if (scope !== getWorkspaceCacheIdentity()) return null;
      if (plan.plan_id !== candidate.planId || !accepted(plan.encrypted)) continue;
      const direct = plan.primaryChatId === input.chatId;
      if (!direct && !candidate.taskId) continue;
      return { plan_id: plan.plan_id, version: plan.version,
        approved_revision_id: plan.encrypted.approved_revision_id!, summary: acceptedPlanSummary(plan),
        ...(!direct && candidate.taskId ? { linked_task_id: candidate.taskId } : {}) };
    } catch {
      // Missing, revoked or undecryptable context is uncertainty, not acceptance.
    }
  }
  return null;
}
