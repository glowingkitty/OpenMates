import type { WorkflowRun } from '../../stores/workflowWorkspaceStore';

const CURRENT_RUN_STATUSES = new Set([
  'planned',
  'queued',
  'running',
  'waiting',
  'cancellation_requested',
]);

export function isCurrentWorkflowRun(run: WorkflowRun): boolean {
  return CURRENT_RUN_STATUSES.has(run.status);
}

/** Keep current work before executions ordered by when they ended. */
export function orderWorkflowRunsForTimeline(runs: WorkflowRun[]): WorkflowRun[] {
  return [...runs].sort((left, right) => {
    const leftIsCurrent = isCurrentWorkflowRun(left);
    const rightIsCurrent = isCurrentWorkflowRun(right);
    if (leftIsCurrent !== rightIsCurrent) return leftIsCurrent ? -1 : 1;

    const leftTime = leftIsCurrent
      ? left.started_at ?? 0
      : left.finished_at ?? left.started_at ?? 0;
    const rightTime = rightIsCurrent
      ? right.started_at ?? 0
      : right.finished_at ?? right.started_at ?? 0;
    return rightTime - leftTime;
  });
}
