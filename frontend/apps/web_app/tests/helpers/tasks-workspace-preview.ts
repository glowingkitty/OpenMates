import type { Page, Route } from '@playwright/test';

const workflowId = 'weather-report';
const runId = 'weather-report-run';
const graph = {
  version: 1,
  trigger_node_id: 'daily-trigger',
  nodes: [
    { id: 'daily-trigger', type: 'schedule_trigger', title: 'Every morning', config: { schedule: { type: 'daily', time: '09:00', timezone: 'UTC' } } },
    { id: 'notify', type: 'send_notification', title: 'Send weather report', config: { title: 'Daily weather report', body: 'Forecast ready' } },
    { id: 'end', type: 'end', title: 'Done', config: {} },
  ],
  edges: [{ from: 'daily-trigger', to: 'notify' }, { from: 'notify', to: 'end' }],
};
const run = {
  id: runId,
  workflow_id: workflowId,
  version_id: 'weather-report-v1',
  status: 'completed',
  trigger_type: 'schedule',
  started_at: 1783054800,
  finished_at: 1783054802,
  node_runs: [
    { id: 'weather-trigger-node-run', run_id: runId, workflow_id: workflowId, node_id: 'daily-trigger', node_type: 'schedule_trigger', status: 'completed' },
    { id: 'weather-notify-node-run', run_id: runId, workflow_id: workflowId, node_id: 'notify', node_type: 'send_notification', status: 'completed' },
  ],
};
const workflow = {
  id: workflowId,
  title: 'Daily Weather Report',
  status: 'active',
  enabled: true,
  current_version_id: run.version_id,
  graph,
};

async function fulfillPreview(route: Route, json: unknown): Promise<void> {
  const origin = route.request().headers().origin ?? '*';
  const headers = {
    'access-control-allow-origin': origin,
    'access-control-allow-credentials': 'true',
    'access-control-allow-methods': 'GET, OPTIONS',
    'access-control-allow-headers': 'Accept, Content-Type',
  };
  if (route.request().method() === 'OPTIONS') {
    await route.fulfill({ status: 204, headers });
  } else {
    await route.fulfill({ status: 200, headers, json });
  }
}

/** Account-free responses for the Workflow run projection in TasksPage.preview.ts. */
export async function installTasksWorkspacePreviewWorkflow(page: Page): Promise<void> {
  await page.route('**/v1/workflows/weather-report/runs/weather-report-run', route => fulfillPreview(route, { run }));
  await page.route('**/v1/workflows/weather-report/runs', route => fulfillPreview(route, { runs: [run] }));
  await page.route('**/v1/workflows/weather-report', route => fulfillPreview(route, { workflow }));
  await page.route('**/v1/workflows/capabilities', route => fulfillPreview(route, { capabilities: [] }));
}
