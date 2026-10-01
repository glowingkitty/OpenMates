import { test } from 'node:test';
import assert from 'node:assert/strict';
import type { WorkflowNodeRun, WorkflowRun } from '../../../stores/workflowWorkspaceStore';
// @ts-expect-error Node's strip-types test runner requires the source extension.
import {
  isCurrentWorkflowRun,
  orderWorkflowRunsForTimeline,
  shouldPollWorkflowRunDetail,
  workflowRunDeliveryState,
  workflowNodePresentationStatus,
  workflowSendDeliveryStatus,
} from '../workflowRunTimeline.ts';

function run(
  id: string,
  status: string,
  startedAt: number,
  finishedAt: number | null = null,
): WorkflowRun {
  return {
    id,
    workflow_id: 'workflow-1',
    version_id: 'version-1',
    trigger_type: 'schedule',
    status,
    started_at: startedAt,
    finished_at: finishedAt,
  };
}

// contract-test: supporting surface=gui.web assertions=workflows-ui.runs.timeline-execution-detail
test('orders current work before ended runs and ended runs by finish time', () => {
  const ordered = orderWorkflowRunsForTimeline([
    run('ended-latest', 'completed', 500, 900),
    run('current', 'running', 100),
    run('ended-earlier', 'failed', 700, 800),
  ]);

  assert.deepEqual(ordered.map(({ id }) => id), [
    'current',
    'ended-latest',
    'ended-earlier',
  ]);
});

// contract-test: supporting surface=gui.web assertions=workflows-ui.runs.timeline-execution-detail
test('treats every pending execution state as current', () => {
  for (const status of ['planned', 'queued', 'running', 'waiting', 'cancellation_requested']) {
    assert.equal(isCurrentWorkflowRun(run(status, status, 100)), true);
  }
  assert.equal(isCurrentWorkflowRun(run('completed', 'completed', 100, 200)), false);
});

function send(status: string, deliveryStatus?: string): WorkflowNodeRun {
  return {
    id: 'node-run-send', run_id: 'run-send', workflow_id: 'workflow-1',
    node_id: 'send', node_type: 'send_chat_message', status,
    output_summary: { delivery_id: 'delivery-1', ...(deliveryStatus ? { status: deliveryStatus } : {}) },
  };
}

// contract-test: supporting surface=gui.web assertions=workflows-ui.runs.timeline-execution-detail,workflows.chat-delivery.sync-projection
test('Send remains current until the canonical delivery is acknowledged', () => {
  for (const deliveryStatus of [undefined, 'delivery_pending', 'claimed']) {
    const nodeRun = send('completed', deliveryStatus);
    const execution = { ...run('run-send', 'completed', 100, 200), node_runs: [nodeRun] };
    assert.equal(workflowSendDeliveryStatus(nodeRun), deliveryStatus ?? 'delivery_pending');
    assert.equal(workflowRunDeliveryState(execution), 'pending');
    assert.equal(isCurrentWorkflowRun(execution), true);
  }
  const acknowledged = { ...run('run-send', 'completed', 100, 200), node_runs: [send('completed', 'acknowledged')] };
  assert.equal(workflowSendDeliveryStatus(acknowledged.node_runs[0]), 'acknowledged');
  assert.equal(workflowRunDeliveryState(acknowledged), null);
  assert.equal(isCurrentWorkflowRun(acknowledged), false);
});

// contract-test: supporting surface=gui.web assertions=workflows-ui.runs.timeline-execution-detail,workflows.chat-delivery.sync-projection
test('Send distinguishes no results and terminal delivery failure', () => {
  assert.equal(workflowSendDeliveryStatus(send('completed', 'no_new_results')), 'no_new_results');
  assert.equal(workflowRunDeliveryState({ ...run('no-results', 'completed', 100), node_runs: [send('completed', 'no_new_results')] }), null);
  for (const deliveryStatus of ['expired', 'cancelled', 'failed']) {
    const execution = { ...run(deliveryStatus, 'completed', 100), node_runs: [send('completed', deliveryStatus)] };
    assert.equal(workflowRunDeliveryState(execution), 'failed');
    assert.equal(isCurrentWorkflowRun(execution), false);
  }
});

// contract-test: supporting surface=gui.web assertions=workflows-ui.runs.timeline-execution-detail,workflows.chat-delivery.sync-projection
test('a terminal run cannot leave unverified or stale nodes waiting', () => {
  const noDelivery = { ...send('completed'), output_summary: {} };
  const pendingWithoutId = { ...send('completed', 'delivery_pending'), output_summary: { status: 'delivery_pending' } };
  const acknowledgedWithoutId = { ...send('completed', 'acknowledged'), output_summary: { status: 'acknowledged' } };
  assert.equal(workflowSendDeliveryStatus(noDelivery), 'failed');
  assert.equal(workflowSendDeliveryStatus(pendingWithoutId), 'failed');
  assert.equal(workflowSendDeliveryStatus(acknowledgedWithoutId), 'failed');
  assert.equal(workflowRunDeliveryState({ ...run('unverified', 'completed', 100), node_runs: [noDelivery] }), 'failed');
  assert.equal(workflowRunDeliveryState({ ...run('unverified-summary', 'completed', 100), output_summary: { deliveries: { send: { status: 'delivery_pending' } } } }), 'failed');
  for (const terminal of ['completed', 'failed', 'cancelled', 'skipped_by_user']) {
    const staleAction: WorkflowNodeRun = { ...send('running'), node_type: 'app_skill_action' };
    assert.equal(workflowNodePresentationStatus(staleAction, false, terminal), terminal === 'cancelled' ? 'cancelled' : 'failed');
    assert.equal(workflowNodePresentationStatus(send('completed', 'claimed'), true, terminal), 'claimed');
  }
  assert.equal(workflowNodePresentationStatus(send('running'), true, 'running'), 'running');
});

// contract-test: supporting surface=gui.web assertions=workflows-ui.runs.timeline-execution-detail
test('an unselected completed run with pending Send sorts with current work', () => {
  const pending = { ...run('pending-send', 'completed', 100, 200), output_summary: { deliveries: { send: { delivery_id: 'delivery-1', status: 'delivery_pending' } } } };
  const ended = run('ended', 'completed', 300, 400);
  assert.deepEqual(orderWorkflowRunsForTimeline([ended, pending]).map(item => item.id), ['pending-send', 'ended']);
});

// contract-test: supporting surface=gui.web assertions=workflows-ui.runs.timeline-execution-detail
test('a failed execution stays failed even if an earlier Send is still pending', () => {
  const execution = { ...run('failed-after-send', 'failed', 100, 200), node_runs: [send('completed', 'delivery_pending')] };
  assert.equal(workflowRunDeliveryState(execution), 'pending');
  assert.equal(isCurrentWorkflowRun(execution), false);
});

// contract-test: supporting surface=gui.web assertions=workflows-ui.runs.timeline-execution-detail
test('a transient run-detail failure retries only while that run remains selected', () => {
  assert.equal(shouldPollWorkflowRunDetail('run-send', 'run-send', null), true);
  assert.equal(shouldPollWorkflowRunDetail('run-send', 'another-run', null), false);
  const pending = { ...run('run-send', 'completed', 100), node_runs: [send('completed', 'claimed')] };
  const delivered = { ...run('run-send', 'completed', 100), node_runs: [send('completed', 'acknowledged')] };
  assert.equal(shouldPollWorkflowRunDetail('run-send', 'run-send', pending), true);
  assert.equal(shouldPollWorkflowRunDetail('run-send', 'run-send', delivered), false);
});

// contract-test: supporting surface=gui.web assertions=workflows-ui.runs.timeline-execution-detail
test('a fresh terminal delivery from either poll wins over stale selected detail', () => {
  const pending = { ...run('run-send', 'completed', 100), node_runs: [send('completed', 'delivery_pending')] };
  const delivered = { ...run('run-send', 'completed', 100), node_runs: [send('completed', 'acknowledged')] };
  assert.equal(workflowRunDeliveryState(delivered, pending), null);
  assert.equal(workflowRunDeliveryState(pending, delivered), null);
  const failed = { ...run('run-send', 'completed', 100), node_runs: [send('completed', 'expired')] };
  assert.equal(workflowRunDeliveryState(failed, pending), 'failed');
  assert.equal(workflowRunDeliveryState(pending, failed), 'failed');
});
