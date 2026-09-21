import { test } from 'node:test';
import assert from 'node:assert/strict';
import type { WorkflowRun } from '../../../stores/workflowWorkspaceStore';
// @ts-expect-error Node's strip-types test runner requires the source extension.
import {
  isCurrentWorkflowRun,
  orderWorkflowRunsForTimeline,
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
