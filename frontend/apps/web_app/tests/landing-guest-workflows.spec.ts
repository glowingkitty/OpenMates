import { expect, test } from './helpers/cookie-audit';

// eslint-disable-next-line @typescript-eslint/no-require-imports -- Existing E2E URL helper uses CommonJS exports.
const { getE2EDebugUrl } = require('./signup-flow-helpers');

// contract-test: direct surface=gui.web assertions=marketing-landing.destinations,workflows-ui.workspace.guest-template-preview
test('landing Workflows header opens the real guest template workspace and read-only detail', async ({ page }) => {
  test.setTimeout(90_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  const ownedRequests: string[] = [];
  page.on('request', request => {
    if (/\/v1\/workflows(?:\/|\?|$)/.test(new URL(request.url()).pathname)) ownedRequests.push(request.url());
  });

  await page.goto(getE2EDebugUrl('/landing'), { waitUntil: 'domcontentloaded' });
  const workflowsLink = page.getByTestId('landing-nav-workflows');
  const origin = new URL(page.url()).origin;
  await expect(workflowsLink).toHaveAttribute('href', `${origin}/#workflows`);
  await workflowsLink.click();
  await expect(page).toHaveURL(/\/#workflows$/);
  await expect(page.getByTestId('workflows-page')).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('workflows-start-screen')).toBeVisible();
  await expect(page.getByTestId('all-workflows-view')).toBeVisible();
  const cards = page.getByTestId('all-workflows-grid').getByTestId('workflow-landing-card');
  await expect(cards).toHaveCount(3);
  await expect(page.getByTestId('workflow-input-composer')).toHaveCount(0);
  await expect(page.getByTestId('workflow-import-button')).toHaveCount(0);
  await expect(page.getByTestId('login-wrapper')).toHaveCount(0);
  await expect(page.getByTestId('signup-modal')).toHaveCount(0);

  await cards.filter({ hasText: 'Daily planning reminder' }).click();
  await expect(page.getByTestId('workflow-management')).toBeVisible();
  await expect(page.getByTestId('workflow-detail')).toBeVisible();
  await expect(page.getByTestId('workspace-detail-header')).toBeVisible();
  await expect(page.getByTestId('workspace-detail-title')).toHaveText('Daily planning reminder');
  await expect(page.getByTestId('workflow-template-panel')).toBeVisible();
  const graph = page.getByTestId('workflow-graph-renderer');
  await expect(graph).toHaveAttribute('data-read-only', 'true');
  const nodes = graph.getByTestId('workflow-node-card');
  await expect(nodes).toHaveCount(2);
  await expect(nodes.first()).toHaveAttribute('data-node-type', 'schedule_trigger');
  await expect(nodes.last()).toHaveAttribute('data-node-type', 'send_chat_message');
  await nodes.first().getByTestId('workflow-node-summary').click();
  await expect(nodes.first().getByTestId('workflow-node-expanded')).toBeVisible();
  await expect(page.getByTestId('toggle-workflow')).toBeDisabled();
  for (const id of ['workflow-input-composer', 'workflow-import-button', 'workflow-add-step', 'workflow-node-save', 'workflow-test-action', 'run-workflow', 'delete-workflow', 'workflow-share', 'workflow-export']) {
    await expect(page.getByTestId(id)).toHaveCount(0);
  }
  await page.getByTestId('workspace-detail-title').click();
  await expect(page.getByRole('textbox', { name: 'Workflow name' })).toHaveCount(0);
  await expect(page.getByTestId('login-wrapper')).toHaveCount(0);
  await expect(page.getByTestId('signup-modal')).toHaveCount(0);
  expect(ownedRequests).toEqual([]);
});
