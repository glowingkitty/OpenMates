import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
import type { Page } from '@playwright/test';

// playwright-account: not_required reason=isolated_component_preview
const preview = (width: number) => `/dev/preview/tasks/TaskBoard?theme=light&background=%23f3f3f3&width=${width}&chrome=0`;
const workspacePreview = (width: number) => `/dev/preview/tasks/TasksPage?theme=light&background=%23f3f3f3&width=${width}&chrome=0`;
const statuses = ['backlog', 'todo', 'in_progress', 'blocked', 'done'];
const previewColumnCounts: Record<string, string> = { backlog: '(3)', todo: '(1)', in_progress: '(1)', blocked: '(1)', done: '(2)' };

async function expectPreviewColumnCounts(page: Page): Promise<void> {
  for (const [status, count] of Object.entries(previewColumnCounts)) {
    await expect(page.getByTestId(`task-column-count-${status}`)).toHaveText(count);
  }
}

async function expectLexendReady(page: Page): Promise<void> {
  await expect.poll(() => page.evaluate(() => document.documentElement.dataset.uiFont)).toBe('lexend');
  const loaded = await page.evaluate(async () => {
    const faces = await document.fonts.load('500 16px "Lexend Deca Variable"');
    return { count: faces.length, ready: document.fonts.check('500 16px "Lexend Deca Variable"') };
  });
  expect(loaded.count).toBeGreaterThan(0);
  expect(loaded.ready).toBe(true);
}

async function expectComposerInFront(page: Page): Promise<void> {
  const composer = page.getByTestId('task-workspace-composer');
  const workspace = page.getByTestId('tasks-page');
  const composerBox = await composer.boundingBox();
  const workspaceBox = await workspace.boundingBox();
  expect(composerBox, 'composer should be measurable').not.toBeNull();
  expect(workspaceBox, 'workspace should be measurable').not.toBeNull();
  expect(composerBox!.y + composerBox!.height).toBeLessThanOrEqual(workspaceBox!.y + workspaceBox!.height + 1);
  const isInFront = await page.evaluate(({ x, y }) => {
    return Boolean(document.elementFromPoint(x, y)?.closest('[data-testid="task-workspace-composer"]'));
  }, {
    x: composerBox!.x + composerBox!.width / 2,
    y: composerBox!.y + composerBox!.height / 2,
  });
  expect(isInFront, 'composer should paint above the task board').toBe(true);
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    window.addEventListener('task-board-preview-action', (event) => {
      document.documentElement.dataset.taskBoardAction = String((event as CustomEvent<string>).detail);
    });
  });
});

// contract-test: supporting surface=gui.web assertions=tasks.surface.semantic-parity,tasks.lifecycle.visible
test('matches the five-column Figma board and keeps actions keyboard reachable', async ({ page }, testInfo) => {
  const fontRequestFailures: string[] = [];
  page.on('requestfailed', (request) => {
    if (/lexend|\.woff2?(?:\?|$)/i.test(request.url())) fontRequestFailures.push(request.url());
  });
  await page.setViewportSize({ width: 1512, height: 921 });
  await page.goto(preview(1320));
  await waitForComponentPreview(page);
  await expectLexendReady(page);

  const board = page.getByTestId('task-board');
  await expect(board).toBeVisible();
  expect(await board.evaluate((element) => getComputedStyle(element).fontFamily)).toContain('Lexend Deca');
  expect(fontRequestFailures).toEqual([]);
  for (const status of statuses) await expect(page.getByTestId(`task-column-${status}`)).toBeVisible();
  await expectPreviewColumnCounts(page);
  await expect(page.getByTestId('task-column-blocked')).toContainText('Confirm launch requirements');
  const draftPlan = page.getByTestId('task-board-plan-card').filter({ hasText: 'Prepare the OpenMates launch plan' });
  const completedPlan = page.getByTestId('task-board-plan-card').filter({ hasText: 'Verify production launch readiness' });
  await expect(draftPlan).toHaveAttribute('data-plan-column', 'backlog');
  await expect(completedPlan).toHaveAttribute('data-plan-column', 'done');
  await expect(draftPlan.getByTestId('plan-project-pill')).toHaveText(/OpenMates/);
  await expect(draftPlan.locator('h3')).toHaveCSS('font-size', '16px');
  expect(await draftPlan.locator('h3').evaluate((element) => getComputedStyle(element).webkitLineClamp)).toBe('3');
  await expect(draftPlan.getByTestId('task-board-plan-open')).toHaveAttribute('href', '/plans/preview-plan-draft');
  await expect(draftPlan.locator('.plan-label, .status-pill, .plan-card-main p')).toHaveCount(0);
  const openPlan = draftPlan.getByTestId('task-board-plan-link');
  await expect(openPlan).toHaveText('Open plan');
  await expect(openPlan.locator('span')).toBeVisible();

  const backlog = page.getByTestId('task-column-backlog');
  const todo = page.getByTestId('task-column-todo');
  const backlogBox = await backlog.boundingBox();
  const todoBox = await todo.boundingBox();
  expect(backlogBox).not.toBeNull();
  expect(todoBox).not.toBeNull();
  expect(backlogBox!.x).toBeLessThan(todoBox!.x);
  expect(backlogBox!.width).toBeGreaterThanOrEqual(220);
  const backlogTitle = backlog.getByTestId('task-card').first().locator('h3');
  await expect(backlogTitle).toHaveCSS('font-size', '16px');
  expect(await backlogTitle.evaluate((element) => getComputedStyle(element).webkitLineClamp)).toBe('3');
  const lightColumnBackgrounds = await Promise.all(
    ['backlog', 'todo', 'in_progress', 'done'].map((status) =>
      page.getByTestId(`task-column-${status}`).evaluate((element) => getComputedStyle(element).backgroundColor),
    ),
  );
  const blockedBackground = await page.getByTestId('task-column-blocked').evaluate((element) => getComputedStyle(element).backgroundColor);
  expect(new Set(lightColumnBackgrounds)).toEqual(new Set(['rgba(0, 0, 0, 0)']));
  expect(blockedBackground).not.toBe(lightColumnBackgrounds[0]);

  const open = page.getByTestId('task-card').filter({ hasText: 'Design 3D model' }).getByTestId('task-card-open');
  await open.focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('html')).toHaveAttribute('data-task-board-action', 'select:preview-todo');
  const todoCard = page.getByTestId('task-card').filter({ hasText: 'Design 3D model' });
  const todoCardBox = await todoCard.boundingBox();
  expect(todoCardBox).not.toBeNull();
  expect(todoCardBox!.height).toBeLessThan(90);
  await expect(page.getByTestId('task-done-toggle')).toHaveCount(0);
  await expect(todoCard.getByTestId('task-project-pill')).toHaveText(/Self driving ballpit/);
  await expect(todoCard.getByTestId('task-assignment-user')).toBeVisible();
  await expect(todoCard.locator('img[data-testid="task-assignment-user"]')).toHaveAttribute('src', /userprofileimage\.jpeg/);
  await expect(todoCard.getByTestId('task-open-chat')).toHaveCount(0);

  const aiCard = page.getByTestId('task-card').filter({ hasText: 'Research open source accounting software alternatives' });
  await expect(aiCard.getByTestId('task-project-pill')).toHaveText(/OpenMates/);
  await expect(aiCard.getByTestId('task-assignment-ai')).toBeVisible();
  await expect(aiCard.getByTestId('task-open-chat')).toBeVisible();
  const quietActionStyles = await Promise.all([
    aiCard.getByTestId('task-open-chat').evaluate((element) => {
      const style = getComputedStyle(element);
      return [style.fontSize, style.color, style.fontWeight, style.lineHeight, style.gap];
    }),
    openPlan.evaluate((element) => {
      const style = getComputedStyle(element);
      return [style.fontSize, style.color, style.fontWeight, style.lineHeight, style.gap];
    }),
  ]);
  expect(quietActionStyles[1]).toEqual(quietActionStyles[0]);
  await expect(page.getByTestId('task-card').filter({ hasText: 'Confirm launch requirements' }).getByTestId('task-project-pill')).toHaveCount(0);
  await expect(page.getByTestId('task-card').filter({ hasText: 'Confirm launch requirements' }).locator('[data-testid^="task-assignment-"]')).toHaveCount(0);
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await page.mouse.move(0, 0);
  await testInfo.attach('task-card-user-assigned', { body: await todoCard.screenshot(), contentType: 'image/png' });
  await testInfo.attach('task-card-ai-assigned', { body: await aiCard.screenshot(), contentType: 'image/png' });
  await testInfo.attach('task-board-plan-card', { body: await draftPlan.screenshot(), contentType: 'image/png' });

  await todoCard.evaluate((element) => {
    const dataTransfer = new DataTransfer();
    dataTransfer.setDragImage = (image) => {
      (window as unknown as { taskCardPreviewDragImageTransform: string }).taskCardPreviewDragImageTransform = getComputedStyle(image).transform;
    };
    (window as unknown as { taskCardPreviewDataTransfer: DataTransfer }).taskCardPreviewDataTransfer = dataTransfer;
    element.dispatchEvent(new DragEvent('dragstart', { bubbles: true, cancelable: true, dataTransfer }));
  });
  await expect(todoCard).toHaveAttribute('data-drag-state', 'picked-up');
  const readPickedUpAngle = () => todoCard.evaluate((element) => {
    const matrix = new DOMMatrix(getComputedStyle(element).transform);
    return Math.round(Math.atan2(matrix.b, matrix.a) * 180 / Math.PI);
  });
  await expect.poll(readPickedUpAngle).toBeGreaterThanOrEqual(9);
  expect(await readPickedUpAngle()).toBeLessThanOrEqual(11);
  const dragImageAngle = await page.evaluate(() => {
    const transform = (window as unknown as { taskCardPreviewDragImageTransform: string }).taskCardPreviewDragImageTransform;
    const matrix = new DOMMatrix(transform);
    return Math.round(Math.atan2(matrix.b, matrix.a) * 180 / Math.PI);
  });
  expect(dragImageAngle).toBeGreaterThanOrEqual(9);
  expect(dragImageAngle).toBeLessThanOrEqual(11);
  await testInfo.attach('task-card-picked-up', { body: await todoCard.screenshot(), contentType: 'image/png' });
  await page.getByTestId('task-column-in_progress').evaluate((element) => {
    const dataTransfer = (window as unknown as { taskCardPreviewDataTransfer: DataTransfer }).taskCardPreviewDataTransfer;
    element.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer }));
  });
  await todoCard.evaluate((element) => element.dispatchEvent(new DragEvent('dragend', { bubbles: true })));
  await expect(page.locator('html')).toHaveAttribute('data-task-board-action', 'move:preview-todo:in_progress');
  await expect(todoCard).toHaveAttribute('data-drag-state', 'settled');
  await expect.poll(() => todoCard.evaluate((element) => getComputedStyle(element).transform)).toBe('none');

  await expect(todoCard.getByTestId('task-move-in_progress')).not.toBeVisible();
  await todoCard.getByTestId('task-actions-more').click();
  await expect(todoCard.getByTestId('task-detail-link')).toBeVisible();
  await expect(todoCard.getByTestId('task-start-ai')).toBeVisible();
  const move = todoCard.getByTestId('task-move-in_progress');
  await expect(move).toBeVisible();
  await testInfo.attach('task-board-actions-open', { body: await todoCard.screenshot(), contentType: 'image/png' });
  await move.click();
  await expect(page.locator('html')).toHaveAttribute('data-task-board-action', 'move:preview-todo:in_progress');
  await todoCard.getByTestId('task-actions-more').click();

  await page.mouse.move(0, 0);
  await testInfo.attach('task-board-figma-desktop', { body: await board.screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=tasks.surface.semantic-parity,tasks.lifecycle.visible
test('uses a contained horizontal board on phone while retaining every status', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 393, height: 652 });
  await page.goto(preview(393));
  await waitForComponentPreview(page);
  await expectLexendReady(page);

  const board = page.getByTestId('task-board');
  await expect(board).toBeVisible();
  const metrics = await board.evaluate((element) => ({ clientWidth: element.clientWidth, scrollWidth: element.scrollWidth }));
  expect(metrics.scrollWidth).toBeGreaterThan(metrics.clientWidth);
  for (const status of statuses) await expect(page.getByTestId(`task-column-${status}`)).toBeAttached();

  await board.evaluate((element) => { element.scrollLeft = element.scrollWidth; });
  await expect(page.getByTestId('task-column-done')).toBeVisible();
  await expect(page.getByTestId('workflow-run-open')).toBeVisible();
  await expect(page.getByTestId('workflow-open')).toHaveCount(0);
  const quietActionStyles = await Promise.all([
    page.getByTestId('task-open-chat').evaluate((element) => {
      const style = getComputedStyle(element);
      return [style.fontSize, style.color, style.fontWeight, style.lineHeight, style.gap];
    }),
    page.getByTestId('workflow-run-open').evaluate((element) => {
      const style = getComputedStyle(element);
      return [style.fontSize, style.color, style.fontWeight, style.lineHeight, style.gap];
    }),
  ]);
  expect(quietActionStyles[1]).toEqual(quietActionStyles[0]);
  await testInfo.attach('task-board-figma-mobile', { body: await board.screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=tasks.surface.semantic-parity,tasks.lifecycle.visible
test('shows zero beside an empty task category', async ({ page }) => {
  await page.setViewportSize({ width: 1512, height: 921 });
  await page.goto(`${preview(1320)}&variant=emptyDone`);
  await waitForComponentPreview(page);

  await expect(page.getByTestId('task-column-count-done')).toHaveText('(0)');
  await expect(page.getByTestId('task-column-done').getByTestId('task-column-empty')).toBeAttached();
});

// contract-test: supporting surface=gui.web assertions=tasks.surface.semantic-parity
test('keeps task titles and the Blocked column readable in dark mode', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1512, height: 921 });
  await page.goto(`/dev/preview/tasks/TaskBoard?theme=dark&background=%23131313&width=1320&chrome=0`);
  await waitForComponentPreview(page);

  const userCard = page.getByTestId('task-card').filter({ hasText: 'Design 3D model' });
  const titleColor = await userCard.locator('h3').evaluate((element) => getComputedStyle(element).color);
  const cardBackground = await userCard.evaluate((element) => getComputedStyle(element).backgroundColor);
  const blockedBackground = await page.getByTestId('task-column-blocked').evaluate((element) => getComputedStyle(element).backgroundColor);
  const todoBackground = await page.getByTestId('task-column-todo').evaluate((element) => getComputedStyle(element).backgroundColor);
  expect(titleColor).toBe('rgb(255, 255, 255)');
  expect(cardBackground).toBe('rgb(23, 23, 23)');
  expect(blockedBackground).not.toBe(todoBackground);
  await expect(page.getByTestId('task-card').filter({ hasText: 'Confirm launch requirements' }).locator('[data-testid^="task-assignment-"]')).toHaveCount(0);
  await testInfo.attach('task-board-figma-dark', { body: await page.getByTestId('task-board').screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=tasks.surface.semantic-parity,tasks.lifecycle.visible
test('renders the complete Figma Tasks workspace on desktop', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1512, height: 921 });
  await page.goto(workspacePreview(1320));
  await waitForComponentPreview(page);
  await expectLexendReady(page);

  const workspace = page.getByTestId('tasks-page');
  await expect(workspace).toBeVisible();
  await expect(page.getByTestId('tasks-figma-workspace')).toBeVisible();
  await expect(page.getByTestId('tasks-daily-suggestion')).toContainText('Daily suggestion');
  const suggestionBackground = await page.getByTestId('tasks-daily-suggestion').evaluate((element) => getComputedStyle(element).backgroundImage);
  expect(suggestionBackground).toContain('linear-gradient');
  expect(suggestionBackground).toContain('rgb(0, 64, 64)');
  await expect(page.getByTestId('tasks-suggestion-create')).toBeVisible();
  await expect(page.getByTestId('task-greeting')).toContainText(/what task is next\?/i);
  await expect(page.getByTestId('task-workspace-composer')).toBeVisible();
  await expectComposerInFront(page);
  await expect(page.getByTestId('task-board')).toBeVisible();
  for (const status of statuses) await expect(page.getByTestId(`task-column-${status}`)).toBeAttached();
  await expectPreviewColumnCounts(page);
  await expect(page.getByTestId('task-board-summary')).toHaveCount(0);
  const suggestionBox = await page.getByTestId('tasks-daily-suggestion').boundingBox();
  const boardBox = await page.getByTestId('task-board').boundingBox();
  expect(suggestionBox).not.toBeNull();
  expect(boardBox).not.toBeNull();
  expect(boardBox!.y - (suggestionBox!.y + suggestionBox!.height)).toBeLessThan(220);
  const filterBox = await page.getByTestId('task-filter-button').boundingBox();
  const search = page.getByTestId('task-search-link');
  const chips = page.getByTestId('task-filter-tags').locator('button');
  const greetingBox = await page.getByTestId('task-greeting').boundingBox();
  expect(filterBox).not.toBeNull();
  expect(greetingBox).not.toBeNull();
  await expect(search).toHaveCSS('font-size', '16px');
  await expect(search.locator('.task-search-link-icon')).toBeVisible();
  await expect(chips).toHaveCount(2);
  await expect(chips.first()).toHaveCSS('font-size', '12px');
  await expect(chips.first()).toHaveCSS('min-height', '20px');
  expect(filterBox!.width).toBe(40);
  expect(filterBox!.height).toBe(40);
  await expect(page.getByTestId('task-filter-button')).toHaveCSS('border-radius', '9999px');
  const [searchBox, chipBox] = await Promise.all([
    search.boundingBox(),
    chips.first().boundingBox(),
  ]);
  expect(searchBox && chipBox, 'task toolbar controls should be measurable').toBeTruthy();
  expect(chipBox!.height).toBe(20);
  expect(chipBox!.height).toBeLessThan(filterBox!.height);
  expect(filterBox!.y).toBeLessThan(greetingBox!.y);
  await testInfo.attach('tasks-workspace-figma-desktop', { body: await workspace.screenshot(), contentType: 'image/png' });

  await search.click();
  const searchField = page.getByTestId('task-search-input');
  await expect(searchField).toBeVisible();
  await expect(searchField).toHaveCSS('font-size', '14px');
  expect((await searchField.locator('..').boundingBox())!.height).toBeLessThanOrEqual(34);
});

// contract-test: supporting surface=gui.web assertions=tasks.surface.semantic-parity
test('keeps the Figma task toolbar readable in dark mode', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1512, height: 921 });
  await page.goto(`/dev/preview/tasks/TasksPage?theme=dark&background=%23131313&width=1320&chrome=0`);
  await waitForComponentPreview(page);

  const filter = page.getByTestId('task-filter-button');
  const chips = page.getByTestId('task-filter-tags').locator('button');
  const suggestionHeading = page.getByTestId('tasks-suggestion-heading');
  const suggestionDescription = page.getByTestId('tasks-suggestion-description');
  const suggestionCard = page.getByTestId('tasks-suggestion-card');
  const suggestionCreate = page.getByTestId('tasks-suggestion-create');
  await expect(suggestionHeading).toHaveText('Daily suggestion');
  await expect(suggestionDescription).toContainText('Security is essential');
  await expect(suggestionCard).toContainText('Double check security');
  await expect(suggestionCreate).toContainText('Click to create task');
  for (const element of [suggestionHeading, suggestionDescription, suggestionCard, suggestionCreate]) {
    await expect(element).toBeVisible();
    const style = await element.evaluate((node) => {
      const computed = getComputedStyle(node);
      return { color: computed.color, opacity: computed.opacity, visibility: computed.visibility };
    });
    expect(style.color).not.toBe('rgba(0, 0, 0, 0)');
    expect(style.opacity).toBe('1');
    expect(style.visibility).toBe('visible');
  }
  await expect(page.getByTestId('task-board-summary')).toHaveCount(0);
  await expectPreviewColumnCounts(page);
  const backlogCount = page.getByTestId('task-column-count-backlog');
  await expect(backlogCount).toHaveCSS('font-size', '12px');
  await expect(filter).toBeVisible();
  await expect(chips).toHaveCount(2);
  const contrast = await Promise.all([
    backlogCount.evaluate((element) => getComputedStyle(element).color),
    filter.evaluate((element) => getComputedStyle(element).backgroundColor),
    filter.locator('span').evaluate((element) => getComputedStyle(element).backgroundImage),
  ]);
  expect(contrast[0]).not.toBe('rgb(0, 0, 0)');
  expect(contrast[1]).not.toBe('rgba(0, 0, 0, 0)');
  expect(contrast[2]).toContain('linear-gradient');
  await testInfo.attach('tasks-workspace-toolbar-dark', { body: await page.getByTestId('tasks-page').screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=tasks.surface.semantic-parity,tasks.project-links.encrypted
test('shares the compact Figma toolbar with project tasks', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1512, height: 921 });
  await page.goto(`${workspacePreview(1320)}&variant=project`);
  await waitForComponentPreview(page);

  const toolbar = page.getByTestId('project-task-toolbar');
  const filter = page.getByTestId('project-task-filter-button');
  const search = page.getByTestId('project-task-search-input');
  await expect(toolbar).toBeVisible();
  await expect(page.getByTestId('project-task-board-summary')).toHaveCount(0);
  await expectPreviewColumnCounts(page);
  await expect(search).toHaveCSS('font-size', '16px');
  await expect(page.getByTestId('project-task-filter-tags').locator('button').first()).toHaveCSS('font-size', '12px');
  expect((await filter.boundingBox())?.width).toBe(40);
  expect((await filter.boundingBox())?.height).toBe(40);
  await testInfo.attach('project-tasks-shared-board-controls', { body: await page.getByTestId('project-tasks-page').screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=tasks.surface.semantic-parity,tasks.lifecycle.visible
test('keeps the complete Tasks workspace and composer contained on phone', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 393, height: 652 });
  await page.goto(workspacePreview(393));
  await waitForComponentPreview(page);
  await expectLexendReady(page);

  const workspace = page.getByTestId('tasks-page');
  await expect(workspace).toBeVisible();
  await expect(page.getByTestId('task-workspace-composer')).toBeVisible();
  await expectComposerInFront(page);
  const metrics = await workspace.evaluate((element) => ({ clientWidth: element.clientWidth, scrollWidth: element.scrollWidth }));
  expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.clientWidth + 1);
  for (const status of statuses) await expect(page.getByTestId(`task-column-${status}`)).toBeAttached();
  await testInfo.attach('tasks-workspace-figma-mobile', { body: await workspace.screenshot(), contentType: 'image/png' });
});
