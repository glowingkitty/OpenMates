export type WorkflowSortMode = 'recent' | 'running-next';

export type SortableWorkflow = {
  id: string;
  created_at?: number | null;
  updated_at?: number | null;
  next_run_at?: number | null;
  enabled: boolean;
};

const MINUTE = 60;
const DAY = 24 * 60 * MINUTE;

function latestEdit(item: SortableWorkflow): number {
  return Math.max(item.created_at ?? 0, item.updated_at ?? 0);
}

function futureRun(item: SortableWorkflow, now: number): number | null {
  const next = item.next_run_at;
  return item.enabled && next != null && next > now ? next : null;
}

function recency(left: SortableWorkflow, right: SortableWorkflow): number {
  return latestEdit(right) - latestEdit(left) || left.id.localeCompare(right.id);
}

/** API workflow timestamps are Unix seconds; `nowMs` remains a JS clock value. */
export function sortWorkflowContinue<T extends SortableWorkflow>(items: readonly T[], nowMs = Date.now()): T[] {
  const now = nowMs / 1000;
  const bucket = (item: T): number => {
    const editAge = now - latestEdit(item);
    const run = futureRun(item, now);
    if (editAge >= 0 && editAge <= 30 * MINUTE) return 0;
    if (run !== null && run - now <= 30 * MINUTE) return 1;
    if (editAge >= 0 && editAge <= DAY) return 2;
    if (run !== null && run - now <= DAY) return 3;
    return 4;
  };
  return [...items].sort((left, right) => {
    const leftBucket = bucket(left);
    const rightBucket = bucket(right);
    if (leftBucket !== rightBucket) return leftBucket - rightBucket;
    if (leftBucket === 1 || leftBucket === 3) {
      return futureRun(left, now)! - futureRun(right, now)! || recency(left, right);
    }
    return recency(left, right);
  });
}

export function sortAllWorkflows<T extends SortableWorkflow>(items: readonly T[], mode: WorkflowSortMode = 'recent', nowMs = Date.now()): T[] {
  const now = nowMs / 1000;
  return [...items].sort((left, right) => {
    if (mode === 'running-next') {
      const leftRun = futureRun(left, now);
      const rightRun = futureRun(right, now);
      if (leftRun !== null && rightRun !== null) return leftRun - rightRun || recency(left, right);
      if (leftRun !== null) return -1;
      if (rightRun !== null) return 1;
    }
    return recency(left, right);
  });
}
