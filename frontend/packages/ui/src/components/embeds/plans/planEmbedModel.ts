/**
 * Pure view-model helpers shared by the Plan embed, its fullscreen view, the
 * Plan detail page and the chat Plan panel. No I/O: callers pass decrypted
 * Plan data in and render the derived summaries.
 */
import type {
  UserPlanAssumptionViewModel,
  UserPlanCriterionViewModel,
  UserPlanVerificationViewModel,
  UserPlanViewModel,
} from '../../../services/userPlanService';
import type { UserTaskStatus } from '../../../services/userTaskService';

export type PlanApprovalKind = 'draft' | 'approved' | 'changed';
export type PlanCheckAggregateStatus =
  | 'pending' | 'passed' | 'failed' | 'passed_unexpectedly' | 'skipped' | 'waived'
  | 'waiting_for_confirmation' | 'stale';
export type PlanTone = 'neutral' | 'success' | 'warning' | 'danger' | 'info';

/** Minimal Task projection a Plan shows; the parent maps Task view models to it. */
export interface PlanLinkedTask {
  taskId: string;
  title: string;
  status: UserTaskStatus;
}

/** Everything a Plan surface needs, already decrypted. */
export interface PlanEmbedData {
  plan: UserPlanViewModel;
  tasks: PlanLinkedTask[];
  assumptions: UserPlanAssumptionViewModel[];
  criteria: UserPlanCriterionViewModel[];
  checks: UserPlanVerificationViewModel[];
  /** Revision currently proposed for approval; falls back to plan.submittedRevisionId. */
  revisionId?: string | null;
  /** Human revision number ("rev 2"). */
  revisionNumber?: number | null;
}

export interface PlanApprovalSummary {
  kind: PlanApprovalKind;
  revisionId: string | null;
  revisionNumber: number | null;
  canApprove: boolean;
}

export interface PlanChecksSummary {
  total: number;
  required: number;
  requiredGreen: number;
  waiting: number;
  failed: number;
  stale: number;
}

export interface PlanProgressSummary {
  done: number;
  total: number;
  blocked: number;
  inProgress: number;
}

export function derivePlanApproval(data: Pick<PlanEmbedData, 'plan' | 'revisionId' | 'revisionNumber'>): PlanApprovalSummary {
  const { plan } = data;
  const revisionId = data.revisionId ?? plan.submittedRevisionId ?? null;
  const approvedId = plan.approvedRevisionId ?? null;
  let kind: PlanApprovalKind = 'draft';
  if (approvedId) kind = approvedId === revisionId || !revisionId ? 'approved' : 'changed';
  return {
    kind,
    revisionId,
    revisionNumber: data.revisionNumber ?? null,
    canApprove: kind !== 'approved' && revisionId !== null,
  };
}

/** Checks report waiting/stale through their lifecycle; everything else is the run status. */
export function checkAggregateStatus(check: UserPlanVerificationViewModel): PlanCheckAggregateStatus {
  if (check.lifecycleStatus === 'stale' || check.lifecycleStatus === 'waiting_for_confirmation') {
    return check.lifecycleStatus;
  }
  return check.status;
}

export function summarizeChecks(checks: UserPlanVerificationViewModel[]): PlanChecksSummary {
  const required = checks.filter((check) => check.requiredForDone);
  return {
    total: checks.length,
    required: required.length,
    requiredGreen: required.filter((check) => checkAggregateStatus(check) === 'passed').length,
    waiting: checks.filter((check) => checkAggregateStatus(check) === 'waiting_for_confirmation').length,
    failed: checks.filter((check) => checkAggregateStatus(check) === 'failed').length,
    stale: checks.filter((check) => checkAggregateStatus(check) === 'stale').length,
  };
}

export function summarizeProgress(tasks: PlanLinkedTask[]): PlanProgressSummary {
  return {
    done: tasks.filter((task) => task.status === 'done').length,
    total: tasks.length,
    blocked: tasks.filter((task) => task.status === 'blocked').length,
    inProgress: tasks.filter((task) => task.status === 'in_progress').length,
  };
}

export function countOpenAssumptions(assumptions: UserPlanAssumptionViewModel[]): number {
  return assumptions.filter((item) => item.status !== 'confirmed' && item.status !== 'corrected' && item.status !== 'waived').length;
}

export function checkLabel(check: UserPlanVerificationViewModel): string {
  return check.description || check.command || check.kind;
}

export function checksCoveringCriterion(
  criterion: UserPlanCriterionViewModel,
  checks: UserPlanVerificationViewModel[],
): UserPlanVerificationViewModel[] {
  return checks.filter((check) => criterion.verificationIds.includes(check.verificationId) || check.covers.includes(criterion.criterionId));
}

export function planStatusTone(status: string): PlanTone {
  if (status === 'completed' || status === 'active') return 'success';
  if (status === 'blocked') return 'danger';
  if (status === 'executing' || status === 'running_checks' || status === 'checking_assumptions') return 'info';
  if (status === 'awaiting_confirmation') return 'warning';
  return 'neutral';
}

export function taskStatusTone(status: UserTaskStatus): PlanTone {
  if (status === 'done') return 'success';
  if (status === 'blocked') return 'danger';
  if (status === 'in_progress') return 'info';
  return 'neutral';
}

export function checkStatusTone(status: PlanCheckAggregateStatus): PlanTone {
  if (status === 'passed') return 'success';
  if (status === 'failed' || status === 'passed_unexpectedly') return 'danger';
  if (status === 'waiting_for_confirmation' || status === 'stale') return 'warning';
  return 'neutral';
}

export function assumptionStatusTone(status: string): PlanTone {
  if (status === 'confirmed') return 'success';
  if (status === 'corrected') return 'info';
  if (status === 'blocked') return 'danger';
  if (status === 'checking') return 'warning';
  return 'neutral';
}
