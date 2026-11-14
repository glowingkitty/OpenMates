/**
 * Loads the decrypted detail data (linked Tasks, assumptions, criteria, checks)
 * that the chat settings active-Plan panel shows for each active Plan.
 * Uses the existing Plan service (Rust work ops behind it); no client logic here.
 * A Plan's Tasks need not be linked to this chat, so the owner's Task list
 * (the Tasks board query, force-refreshed: Plan Tasks are often added from the
 * CLI or another device while this tab's board cache is still fresh) is merged
 * with the chat's Tasks.
 */
import { loadUserPlanDetailState, type UserPlanViewModel } from '../../services/userPlanService';
import { listTaskBoardItems, isWorkflowRunTaskProjectionViewModel, type UserTaskViewModel } from '../../services/userTaskService';
import type { PlanEmbedData } from '../embeds/plans/planEmbedModel';

export type ChatPlanDetails = Record<string, Omit<PlanEmbedData, 'plan'>>;

export async function loadChatPlanDetails(plans: UserPlanViewModel[], chatTasks: UserTaskViewModel[]): Promise<ChatPlanDetails> {
  if (plans.length === 0) return {};
  const byId = new Map<string, UserTaskViewModel>();
  const ownerTasks = (await listTaskBoardItems({}, { force: true }))
    .filter((task): task is UserTaskViewModel => !isWorkflowRunTaskProjectionViewModel(task));
  for (const task of [...chatTasks, ...ownerTasks]) byId.set(task.task_id, task);
  const allTasks = [...byId.values()];
  const entries = await Promise.all(plans.map(async (plan) => {
    const state = await loadUserPlanDetailState(plan);
    const tasks = allTasks
      .filter((task) => task.planId === plan.plan_id)
      .map((task) => ({ taskId: task.task_id, title: task.title, status: task.status }));
    return [plan.plan_id, {
      tasks,
      assumptions: state.assumptions,
      criteria: state.criteria,
      checks: state.verifications,
    }] as const;
  }));
  return Object.fromEntries(entries);
}
