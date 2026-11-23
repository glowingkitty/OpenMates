/**
 * Pure helpers linking a Specification or Check to the Plan created from it.
 * The parent loads the Plan and its Tasks (userPlanService / Tasks services),
 * maps them to these shapes and passes them in; nothing here does I/O.
 * Matching: a Plan's assumption belongs to a Specification assumption by exact
 * text; a Check shows the Tasks whose description names a covered requirement id.
 */
export type SpecPlanAssumptionStatus = 'open' | 'checking' | 'confirmed' | 'corrected' | 'blocked' | 'waived';

export interface SpecPlanAssumption {
  text: string;
  status: SpecPlanAssumptionStatus | string;
  /** Sub-chat checking this assumption. */
  linkedSubChatId: string | null;
}

export interface SpecPlanTask {
  taskId: string;
  title: string;
  description: string;
  status: string;
  /** Sub-chat working on this Task. */
  linkedSubChatId: string | null;
}

export interface SpecPlanLinks {
  planId: string;
  assumptions: SpecPlanAssumption[];
  tasks: SpecPlanTask[];
}

export function findPlanAssumption(plan: SpecPlanLinks | undefined, text: string): SpecPlanAssumption | undefined {
  return plan?.assumptions.find((item) => item.text === text);
}

/** Tasks of the Plan whose description mentions any of the given requirement ids. */
export function tasksForRequirementIds(tasks: SpecPlanTask[], requirementIds: string[]): SpecPlanTask[] {
  const ids = requirementIds.map((id) => id.trim().toLowerCase()).filter(Boolean);
  if (ids.length === 0) return [];
  return tasks.filter((task) => {
    const description = task.description.toLowerCase();
    return ids.some((id) => description.includes(id));
  });
}

/** Compact preview counts (assumptions still open or being checked only), or null when the Plan has nothing to show. */
export function summarizePlanLinks(plan: SpecPlanLinks | undefined): { checking: number; tasks: number } | null {
  if (!plan) return null;
  const checking = plan.assumptions.filter((item) => item.status === 'checking' || item.status === 'unchecked' || item.status === 'open').length;
  if (checking === 0 && plan.tasks.length === 0) return null;
  return { checking, tasks: plan.tasks.length };
}
