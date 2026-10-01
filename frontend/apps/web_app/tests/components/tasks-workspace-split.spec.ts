import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
import { installTasksWorkspacePreviewWorkflow } from '../helpers/tasks-workspace-preview';

// playwright-account: not_required reason=isolated_component_preview
const preview = (width: number) => `/dev/preview/tasks/TasksPage?theme=light&background=%23f3f3f3&width=${width}&chrome=0`;

test.beforeEach(async ({ page }) => {
  await installTasksWorkspacePreviewWorkflow(page);
});

// contract-test: direct surface=gui.web assertions=tasks.detail.embed-responsive,tasks.surface.semantic-parity
test('task and Workflow run details split the full Tasks workspace', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1512, height: 921 });
  await page.goto(preview(1320));
  await waitForComponentPreview(page);

  const workspace = page.getByTestId('tasks-figma-workspace');
  const composer = page.getByTestId('task-workspace-composer');
  const board = page.getByTestId('task-board');
  const boardNode = await board.elementHandle();
  await page.getByTestId('task-card').filter({ hasText: 'Design 3D model' }).getByTestId('task-card-open').click();

  const detail = page.getByTestId('task-detail-panel');
  await expect(detail).toBeVisible();
  await expect(page.getByTestId('tasks-workspace-layout')).toHaveClass(/split/);
  const [workspaceBox, detailBox, composerBox] = await Promise.all([
    workspace.boundingBox(), detail.boundingBox(), composer.boundingBox(),
  ]);
  expect(workspaceBox && detailBox && composerBox).toBeTruthy();
  expect(Math.abs(workspaceBox!.y - detailBox!.y)).toBeLessThanOrEqual(2);
  expect(Math.abs(workspaceBox!.height - detailBox!.height)).toBeLessThanOrEqual(2);
  expect(workspaceBox!.x + workspaceBox!.width).toBeLessThan(detailBox!.x);
  expect(composerBox!.x).toBeGreaterThanOrEqual(workspaceBox!.x);
  expect(composerBox!.x + composerBox!.width).toBeLessThanOrEqual(workspaceBox!.x + workspaceBox!.width + 1);
  await expect(page.getByTestId('task-greeting')).toBeVisible();
  await expect(page.getByTestId('tasks-daily-inspiration-area')).toBeAttached();
  await expect(detail.getByRole('alert')).toHaveCount(0);
  await testInfo.attach('tasks-workspace-task-split', { body: await page.getByTestId('tasks-workspace-layout').screenshot(), contentType: 'image/png' });

  await page.getByTestId('task-detail-minimize').click();
  await expect(detail).toHaveCount(0);
  await expect(page.getByTestId('tasks-workspace-layout')).not.toHaveClass(/split/);
  expect(await board.evaluate((node, original) => node === original, boardNode)).toBe(true);

  await board.evaluate((element) => { element.scrollLeft = element.scrollWidth; });
  await page.getByTestId('workflow-run-projection').click();
  await expect(detail).toBeVisible();
  await expect(page.getByTestId('workflow-run-projection-detail')).toHaveAttribute('data-presentation', 'split');
  await expect(page.getByTestId('workflow-run-detail-live-status')).toHaveAttribute('data-status', 'completed');
  await expect(page.getByTestId('workflow-run-task-graph').getByTestId('workflow-node-card')).toHaveCount(2);
  await expect(detail.getByRole('alert')).toHaveCount(0);
  const runBox = await detail.boundingBox();
  const workspaceRunBox = await workspace.boundingBox();
  expect(Math.abs(runBox!.y - workspaceRunBox!.y)).toBeLessThanOrEqual(2);
  expect(runBox!.x).toBeGreaterThan(workspaceRunBox!.x + workspaceRunBox!.width);
  await testInfo.attach('tasks-workspace-workflow-run-split', { body: await page.getByTestId('tasks-workspace-layout').screenshot(), contentType: 'image/png' });
  await page.getByTestId('task-detail-close').click();
  await expect(detail).toHaveCount(0);
});

// contract-test: supporting surface=gui.web assertions=tasks.detail.embed-responsive
test('compact Tasks workspace opens detail over the board', async ({ page }) => {
  await page.setViewportSize({ width: 393, height: 652 });
  await page.goto(preview(393));
  await waitForComponentPreview(page);
  await page.getByTestId('task-card').filter({ hasText: 'Design 3D model' }).getByTestId('task-card-open').click();
  await expect(page.getByTestId('task-detail-fullscreen')).toBeVisible();
  await expect(page.getByTestId('task-detail-panel')).toHaveCount(0);
  await expect(page.getByTestId('tasks-workspace-layout')).not.toHaveClass(/split/);
  await page.getByTestId('task-detail-minimize').click();
  await expect(page.getByTestId('task-board')).toBeVisible();
});
