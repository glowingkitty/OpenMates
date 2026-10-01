import type { WorkflowNodeRun, WorkflowRun } from '../../stores/workflowWorkspaceStore';

const CURRENT_RUN_STATUSES = new Set([
  'planned',
  'queued',
  'running',
  'waiting',
  'cancellation_requested',
]);
const MESSAGE_NODE_TYPES = new Set(['send_chat_message', 'start_new_chat', 'create_chat_report']);
const PENDING_DELIVERY_STATUSES = new Set(['delivery_pending', 'claimed']);
const TERMINAL_DELIVERY_STATUSES = new Set(['acknowledged', 'no_new_results', 'expired', 'cancelled', 'failed']);

/** A completed runner step is still pending until the chat delivery is acknowledged. */
export function workflowSendDeliveryStatus(nodeRun: WorkflowNodeRun): string {
  if (['failed', 'cancelled', 'skipped'].includes(nodeRun.status)) return nodeRun.status;
  const deliveryStatus = nodeRun.output_summary?.status;
  if (typeof deliveryStatus === 'string' && [
    'acknowledged', 'no_new_results', 'delivery_pending', 'claimed', 'expired', 'cancelled', 'failed',
  ].includes(deliveryStatus)) {
    if ((PENDING_DELIVERY_STATUSES.has(deliveryStatus) || deliveryStatus === 'acknowledged')
      && !nodeRun.output_summary?.delivery_id) return 'failed';
    return deliveryStatus;
  }
  if (nodeRun.status === 'completed' && MESSAGE_NODE_TYPES.has(nodeRun.node_type)) {
    return nodeRun.output_summary?.delivery_id ? 'delivery_pending' : 'failed';
  }
  return nodeRun.status;
}

const TERMINAL_RUN_STATUSES = new Set(['completed', 'failed', 'cancelled', 'skipped', 'skipped_by_user']);
const UNFINISHED_NODE_STATUSES = new Set(['planned', 'queued', 'running', 'waiting', 'cancellation_requested']);

/** A terminal execution cannot leave a stale unfinished node looking active. */
export function workflowNodePresentationStatus(nodeRun: WorkflowNodeRun, isMessage: boolean, runStatus?: string | null): string {
  const status = isMessage ? workflowSendDeliveryStatus(nodeRun) : nodeRun.status;
  if (!runStatus || !TERMINAL_RUN_STATUSES.has(runStatus)) return status;
  if (isMessage && PENDING_DELIVERY_STATUSES.has(status)) return status;
  if (UNFINISHED_NODE_STATUSES.has(status)) return runStatus === 'cancelled' ? 'cancelled' : 'failed';
  return status;
}

function deliveryStatusesByNode(run: WorkflowRun): Map<string, string> {
  const statuses = new Map<string, string>();
  for (const nodeRun of run.node_runs ?? []) {
    if (MESSAGE_NODE_TYPES.has(nodeRun.node_type)) statuses.set(nodeRun.node_id, workflowSendDeliveryStatus(nodeRun));
  }
  const deliveries = run.output_summary?.deliveries;
  const deliveryRecords = deliveries && typeof deliveries === 'object'
    ? deliveries as Record<string, { status?: unknown; delivery_id?: unknown }>
    : {};
  for (const [nodeId, delivery] of Object.entries(deliveryRecords)) {
    if (typeof delivery?.status !== 'string') continue;
    if ((PENDING_DELIVERY_STATUSES.has(delivery.status) || delivery.status === 'acknowledged')
      && !delivery.delivery_id) statuses.set(nodeId, 'failed');
    else statuses.set(nodeId, delivery.status);
  }
  return statuses;
}

/** Terminal delivery outcomes win over an older pending response from either poll. */
export function workflowRunDeliveryState(run: WorkflowRun, selectedDetail?: WorkflowRun | null): 'pending' | 'failed' | null {
  const statusesByNode = deliveryStatusesByNode(run);
  if (selectedDetail && selectedDetail.id === run.id) {
    for (const [nodeId, status] of deliveryStatusesByNode(selectedDetail)) {
      const previous = statusesByNode.get(nodeId);
      if (!previous || TERMINAL_DELIVERY_STATUSES.has(status) || !TERMINAL_DELIVERY_STATUSES.has(previous)) statusesByNode.set(nodeId, status);
    }
  }
  const statuses = [...statusesByNode.values()];
  if (statuses.some(status => PENDING_DELIVERY_STATUSES.has(status))) return 'pending';
  if (statuses.some(status => ['expired', 'cancelled', 'failed'].includes(status))) return 'failed';
  return null;
}

export function shouldPollWorkflowRunDetail(runId: string, selectedRunId: string | null, detail: WorkflowRun | null): boolean {
  if (selectedRunId !== runId) return false;
  return detail === null || !TERMINAL_RUN_STATUSES.has(detail.status) || workflowRunDeliveryState(detail) === 'pending';
}

export function isCurrentWorkflowRun(run: WorkflowRun): boolean {
  if (['failed', 'cancelled', 'skipped', 'skipped_by_user'].includes(run.status)) return false;
  return CURRENT_RUN_STATUSES.has(run.status) || workflowRunDeliveryState(run) === 'pending';
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
