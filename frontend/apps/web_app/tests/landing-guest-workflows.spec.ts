import { expect, test } from './helpers/cookie-audit';

// eslint-disable-next-line @typescript-eslint/no-require-imports -- Existing E2E URL helper uses CommonJS exports.
const { getE2EDebugUrl } = require('./signup-flow-helpers');
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

test.use({ timezoneId: 'America/New_York' });

const guestWorkflowsProof = defineVideoProof({
  id: 'landing-guest-workflows', title: 'Explore a workflow template from the landing page', surface: 'web',
  devices: ['web-phone', 'web-laptop'], domain: 'landing.dev.openmates.org',
  transcript: [
    { id: 'workspace', text: 'Guests see Daily Inspiration and five tested templates under Continue where you left off.', checkpoint: 'workspace', devices: ['web-phone', 'web-laptop'] },
    { id: 'template', text: 'Guests can inspect the weekly Berlin AI events workflow without running or editing it.', checkpoint: 'template', devices: ['web-phone', 'web-laptop'] },
  ],
  assertions: [
    { id: 'landing.guest-workflow-home', checkpoint: 'workspace', visual: 'Daily Inspiration and the template continuation row appear in the regular workflow workspace.', devices: ['web-phone', 'web-laptop'] },
    { id: 'landing.guest-workflow-template', checkpoint: 'template', visual: 'The template graph is visible and read-only in the app workspace.', devices: ['web-phone', 'web-laptop'] },
  ],
  tutorial: { readingWordsPerSecond: 3, minimumHoldMs: 900, maximumHoldMs: 2500 },
});

for (const [width, height, device] of [[390, 844, 'web-phone'], [1440, 900, 'web-laptop']] as const) {
// contract-test: direct surface=gui.web assertions=marketing-landing.destinations,workflows-ui.workspace.guest-template-preview,workflows-ui.workspace.recommendation-led-composition
test(`landing Explore Workflows opens the real guest template workspace and read-only detail (${width}px)`, async ({ page }, testInfo) => {
  test.setTimeout(90_000);
  let proofPage = page;
  const proof = createVideoProofRuntime(guestWorkflowsProof, { device, attach: testInfo.attach.bind(testInfo), captureFrame: () => proofPage.screenshot() });
  await page.setViewportSize({ width, height });
  const ownedRequests: string[] = [];
  page.context().on('request', request => {
    if (/\/v1\/workflows(?:\/|\?|$)/.test(new URL(request.url()).pathname)) ownedRequests.push(request.url());
  });

  await page.goto(getE2EDebugUrl('/landing'), { waitUntil: 'domcontentloaded' });
  const workflowsLink = page.getByTestId('landing-explore-workflows');
  const origin = new URL(page.url()).origin;
  await expect(workflowsLink).toHaveAttribute('href', `${origin}/#workflows`);
  await expect(workflowsLink).toHaveAttribute('target', '_blank');
  await expect(workflowsLink).toHaveAttribute('rel', /noopener/);
  const [popup] = await Promise.all([page.waitForEvent('popup'), workflowsLink.click()]);
  proofPage = popup;
  await expect(popup).toHaveURL(/\/#workflows$/);
  await expect(popup.getByTestId('workflows-page')).toBeVisible({ timeout: 30_000 });
  await expect(popup.getByTestId('workflows-start-screen')).toBeVisible();
  await expect(popup.getByTestId('all-workflows-view')).toHaveCount(0);
  await expect(popup.getByTestId('workflows-show-all')).toHaveCount(0);
  await expect(popup.getByTestId('workflows-daily-inspiration-area').getByTestId('daily-inspiration-phrase')).toBeVisible();
  const continuation = popup.getByTestId('workflows-workspace-continue');
  const cards = continuation.getByTestId('workflow-landing-card');
  await expect(continuation).toContainText('Continue where you left off');
  await expect(cards).toHaveCount(5);
  await expect(popup.getByTestId('workflow-input-composer')).toHaveCount(0);
  await expect(popup.getByTestId('workflow-import-button')).toHaveCount(0);
  await expect(popup.getByTestId('login-wrapper')).toHaveCount(0);
  await expect(popup.getByTestId('signup-modal')).toHaveCount(0);

  await proof.assert('landing.guest-workflow-home', async () => {
    await expect(continuation).toBeVisible();
    await expect(cards).toHaveCount(5);
  });
  await proof.checkpoint('workspace');
  await popup.getByTestId('workflows-show-templates').click();
  await expect(popup.getByTestId('all-workflows-grid').getByTestId('workflow-landing-card')).toHaveCount(5);
  await popup.getByTestId('workflows-back-to-recent').click();
  await expect(continuation).toBeVisible();
  await cards.filter({ hasText: 'Weekly Berlin AI events' }).click();
  await expect(popup.getByTestId('workflow-management')).toBeVisible();
  await expect(popup.getByTestId('workflow-detail')).toBeVisible();
  await expect(popup.getByTestId('workspace-detail-header')).toBeVisible();
  await expect(popup.getByTestId('workspace-detail-title')).toHaveText('Weekly Berlin AI events');
  await expect(popup.getByTestId('workspace-detail-header')).toHaveAttribute('data-category', 'science');
  await expect(popup.getByTestId('workspace-detail-header')).toHaveAttribute('data-icon', 'calendar-days');
  await expect(popup.getByTestId('workflow-template-panel')).toBeVisible();
  const graph = popup.getByTestId('workflow-graph-renderer');
  await expect(graph).toHaveAttribute('data-read-only', 'true');
  const nodes = graph.getByTestId('workflow-node-card');
  await expect(nodes).toHaveCount(3);
  await expect(nodes.first()).toHaveAttribute('data-node-type', 'schedule_trigger');
  await expect(nodes.last()).toHaveAttribute('data-node-type', 'send_chat_message');
  await nodes.first().getByTestId('workflow-node-summary').click();
  await expect(nodes.first().getByTestId('workflow-node-expanded')).toBeVisible();
  await expect(nodes.first().getByTestId('workflow-node-expanded')).toContainText('Europe/Berlin');
  await expect(popup.getByTestId('toggle-workflow')).toBeDisabled();
  for (const id of ['workflow-input-composer', 'workflow-import-button', 'workflow-add-step', 'workflow-node-save', 'workflow-test-action', 'run-workflow', 'delete-workflow', 'workflow-share', 'workflow-export']) {
    await expect(popup.getByTestId(id)).toHaveCount(0);
  }
  await popup.getByTestId('workspace-detail-title').click();
  await expect(popup.getByRole('textbox', { name: 'Workflow name' })).toHaveCount(0);
  await expect(popup.getByTestId('login-wrapper')).toHaveCount(0);
  await expect(popup.getByTestId('signup-modal')).toHaveCount(0);
  expect(ownedRequests).toEqual([]);
  await proof.assert('landing.guest-workflow-template', async () => {
    await expect(graph).toHaveAttribute('data-read-only', 'true');
    await expect(nodes).toHaveCount(3);
  });
  await proof.checkpoint('template');
  await proof.attach();
  const video = popup.video();
  await popup.close();
  if (video) {
    const path = testInfo.outputPath('guest-workflow-app.webm');
    await video.saveAs(path);
    await testInfo.attach('guest-workflow-app-video', { path, contentType: 'video/webm' });
  }
});
}
