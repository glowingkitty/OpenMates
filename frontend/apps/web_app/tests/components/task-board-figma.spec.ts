import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
import { installTasksWorkspacePreviewWorkflow } from '../helpers/tasks-workspace-preview';
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
  await installTasksWorkspacePreviewWorkflow(page);
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
  await expect(draftPlan.getByTestId('task-board-plan-open')).toHaveAttribute('href', '/#plan-id=preview-plan-draft');
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
  await expect.poll(readPickedUpAngle).toBeGreaterThanOrEqual(2);
  expect(await readPickedUpAngle()).toBeLessThanOrEqual(4);
  const dragImageAngle = await page.evaluate(() => {
    const transform = (window as unknown as { taskCardPreviewDragImageTransform: string }).taskCardPreviewDragImageTransform;
    const matrix = new DOMMatrix(transform);
    return Math.round(Math.atan2(matrix.b, matrix.a) * 180 / Math.PI);
  });
  expect(dragImageAngle).toBeGreaterThanOrEqual(2);
  expect(dragImageAngle).toBeLessThanOrEqual(4);
  await testInfo.attach('task-card-picked-up', { body: await todoCard.screenshot(), contentType: 'image/png' });
  await page.getByTestId('task-column-in_progress').evaluate((element) => {
    const dataTransfer = (window as unknown as { taskCardPreviewDataTransfer: DataTransfer }).taskCardPreviewDataTransfer;
    element.dispatchEvent(new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer }));
  });
  await expect(page.getByTestId('task-column-drop-target-in_progress')).toHaveText('Drop to mark In progress');
  await expect(page.getByTestId('task-column-in_progress').locator('.task-column-list > :first-child')).toHaveAttribute('data-testid', 'task-column-drop-target-in_progress');
  await testInfo.attach('task-column-drop-target-visible', { body: await board.screenshot(), contentType: 'image/png' });
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

// contract-test: supporting surface=gui.web assertions=tasks.surface.semantic-parity,tasks.lifecycle.visible
test('reveals 30 then 20 items per status while keeping the full count and page scrolling', async ({ page }) => {
  await page.setViewportSize({ width: 1512, height: 921 });
  await page.goto(`${preview(1320)}&variant=manyBacklog`);
  await waitForComponentPreview(page);

  const board = page.getByTestId('task-board');
  const backlog = page.getByTestId('task-column-backlog');
  const cards = backlog.locator('[data-testid="task-card"], [data-testid="task-board-plan-card"]');
  const more = page.getByTestId('task-column-show-more-backlog');
  await expect(page.getByTestId('task-column-count-backlog')).toHaveText('(56)');
  await expect(cards).toHaveCount(30);
  await expect(more).toBeVisible();
  await more.click();
  await expect(cards).toHaveCount(50);
  await more.click();
  await expect(cards).toHaveCount(56);
  await expect(more).toHaveCount(0);
  await expect(page.getByTestId('task-column-count-backlog')).toHaveText('(56)');
  const boardScroll = await board.evaluate((element) => ({ height: element.clientHeight, contentHeight: element.scrollHeight }));
  expect(boardScroll.contentHeight).toBeLessThanOrEqual(boardScroll.height + 1);
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
  const inspirationArea = page.getByTestId('tasks-daily-inspiration-area');
  await expect(inspirationArea).toBeVisible();
  await expect(inspirationArea.getByTestId('daily-inspiration-banner')).toBeVisible();
  await expect(inspirationArea.getByTestId('daily-inspiration-label')).toHaveText('Daily inspiration');
  await expect(inspirationArea.getByTestId('daily-inspiration-phrase')).toContainText('next action');
  await expect(inspirationArea.getByTestId('daily-inspiration-cta-text')).toHaveText('Click to create task');
  await expect(page.getByTestId('task-greeting')).toContainText(/what task is next\?/i);
  await expect(page.getByTestId('task-workspace-composer')).toBeVisible();
  await expectComposerInFront(page);
  await expect(page.getByTestId('task-board')).toBeVisible();
  for (const status of statuses) await expect(page.getByTestId(`task-column-${status}`)).toBeAttached();
  await expectPreviewColumnCounts(page);
  await expect(page.getByTestId('task-board-summary')).toHaveCount(0);
  const suggestionBox = await inspirationArea.boundingBox();
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

// contract-test: supporting surface=gui.web assertions=tasks.surface.semantic-parity,tasks.lifecycle.visible
test('scrolls the shared inspiration away when the task board is populated', async ({ page }) => {
  await page.setViewportSize({ width: 1512, height: 921 });
  await page.goto(`${workspacePreview(1320)}&variant=manyBacklog`);
  await waitForComponentPreview(page);

  const scrollLayer = page.getByTestId('tasks-workspace-scroll-layer');
  const inspiration = page.getByTestId('tasks-daily-inspiration-area');
  await expect(inspiration.getByTestId('daily-inspiration-banner')).toBeVisible();
  const scrollSize = await scrollLayer.evaluate((element) => ({ visible: element.clientHeight, content: element.scrollHeight }));
  expect(scrollSize.content, `Tasks scroll layer: ${JSON.stringify(scrollSize)}`).toBeGreaterThan(scrollSize.visible);
  const before = await Promise.all([inspiration.boundingBox(), page.getByTestId('task-board').boundingBox()]);
  await scrollLayer.evaluate((element) => { element.scrollTop = element.scrollHeight; });
  await expect.poll(() => scrollLayer.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
  const after = await Promise.all([inspiration.boundingBox(), page.getByTestId('task-board').boundingBox()]);
  expect(after[0]!.y).toBeLessThan(before[0]!.y);
  expect(after[1]!.y).toBeLessThan(before[1]!.y);
});

// contract-test: supporting surface=gui.web assertions=tasks.surface.semantic-parity
test('keeps the Figma task toolbar readable in dark mode', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1512, height: 921 });
  await page.goto(`/dev/preview/tasks/TasksPage?theme=dark&background=%23131313&width=1320&chrome=0`);
  await waitForComponentPreview(page);

  const filter = page.getByTestId('task-filter-button');
  const chips = page.getByTestId('task-filter-tags').locator('button');
  const suggestionHeading = page.getByTestId('tasks-daily-inspiration-area').getByTestId('daily-inspiration-label');
  const suggestionDescription = page.getByTestId('tasks-daily-inspiration-area').getByTestId('daily-inspiration-phrase');
  const suggestionCard = page.getByTestId('tasks-daily-inspiration-area').getByTestId('daily-inspiration-info-card');
  const suggestionCreate = page.getByTestId('tasks-daily-inspiration-area').getByTestId('daily-inspiration-cta-text');
  await expect(suggestionHeading).toHaveText('Daily inspiration');
  await expect(suggestionDescription).toContainText('next action');
  await expect(suggestionCard).toContainText('Task planning tip');
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

// contract-test: supporting surface=gui.web assertions=tasks.detail.embed-responsive,tasks.surface.semantic-parity
test('opens task and workflow run details beside the full workspace when there is room', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1512, height: 921 });
  await page.goto(workspacePreview(1320));
  await waitForComponentPreview(page);

  const board = page.getByTestId('task-board');
  await page.getByTestId('task-card').filter({ hasText: 'Design 3D model' }).getByTestId('task-card-open').click();
  const taskPanel = page.getByTestId('task-detail-panel');
  await expect(taskPanel).toBeVisible();
  await expect(page.getByTestId('task-detail-fullscreen')).toHaveCSS('transform', /^(none|matrix\(1, 0, 0, 1, 0, 0\))$/);
  await expect(board).toBeVisible();
  const workspace = page.getByTestId('tasks-figma-workspace');
  const [workspaceBox, taskBox] = await Promise.all([workspace.boundingBox(), taskPanel.boundingBox()]);
  expect(workspaceBox && taskBox).toBeTruthy();
  expect(Math.abs(workspaceBox!.y - taskBox!.y)).toBeLessThanOrEqual(2);
  expect(workspaceBox!.x + workspaceBox!.width).toBeLessThan(taskBox!.x);
  await expect(taskPanel.getByRole('alert')).toHaveCount(0);
  await testInfo.attach('tasks-split-task-detail', { body: await page.getByTestId('tasks-workspace-layout').screenshot(), contentType: 'image/png' });
  await page.getByTestId('task-detail-minimize').click();

  await board.evaluate((element) => { element.scrollLeft = element.scrollWidth; });
  await page.getByTestId('workflow-run-projection').click();
  const runPanel = page.getByTestId('workflow-run-projection-detail');
  await expect(runPanel).toHaveAttribute('data-presentation', 'split');
  const [runBox, workspaceRunBox] = await Promise.all([runPanel.boundingBox(), workspace.boundingBox()]);
  expect(runBox && workspaceRunBox).toBeTruthy();
  expect(Math.abs(runBox!.y - workspaceRunBox!.y)).toBeLessThanOrEqual(2);
  await expect(page.getByTestId('workflow-run-fullscreen')).toHaveCSS('transform', /^(none|matrix\(1, 0, 0, 1, 0, 0\))$/);
  await expect(board).toBeVisible();
  expect(runBox!.height).toBeGreaterThan(500);
  const runTitleBox = await page.getByTestId('embed-header-title').boundingBox();
  expect(runTitleBox!.y).toBeLessThan(runBox!.y + 260);
  const runId = page.getByTestId('workflow-run-detail-id');
  await expect(runId).toHaveText('weather-report-run');
  await expect(page.getByTestId('workflow-run-detail-live-status')).toHaveAttribute('data-status', 'completed');
  await expect(page.getByTestId('workflow-run-task-graph').getByTestId('workflow-node-card')).toHaveCount(2);
  await expect(runPanel.getByRole('alert')).toHaveCount(0);
  await testInfo.attach('tasks-split-workflow-run-detail', { body: await page.getByTestId('tasks-workspace-layout').screenshot(), contentType: 'image/png' });
  const runIdColors = await runId.evaluate((element) => {
    const style = getComputedStyle(element);
    return { foreground: style.color, background: style.backgroundColor };
  });
  expect(runIdColors.foreground).not.toBe(runIdColors.background);
});

// contract-test: supporting surface=gui.web assertions=tasks.detail.embed-responsive
test('uses full overlay details on a narrow Tasks workspace', async ({ page }) => {
  await page.setViewportSize({ width: 393, height: 652 });
  await page.goto(workspacePreview(393));
  await waitForComponentPreview(page);

  const board = page.getByTestId('task-board');
  await board.evaluate((element) => { element.scrollLeft = element.scrollWidth; });
  await page.getByTestId('workflow-run-projection').click();
  const runPanel = page.getByTestId('workflow-run-projection-detail');
  await expect(runPanel).toHaveAttribute('data-presentation', 'overlay');
  await expect(page.getByTestId('workflow-run-fullscreen')).toHaveCSS('transform', /^(none|matrix\(1, 0, 0, 1, 0, 0\))$/);
  const bounds = await runPanel.boundingBox();
  expect(bounds!.width).toBeGreaterThanOrEqual(390);
  expect(bounds!.height).toBeGreaterThanOrEqual(650);
  await page.getByTestId('task-detail-close').click();
  await expect(runPanel).toHaveCount(0);

  await board.evaluate((element) => { element.scrollLeft = 0; });
  await page.getByTestId('task-card').filter({ hasText: 'Design 3D model' }).getByTestId('task-card-open').click();
  await expect(page.getByTestId('task-detail-fullscreen')).toHaveCSS('transform', /^(none|matrix\(1, 0, 0, 1, 0, 0\))$/);
  await expect(page.getByTestId('task-detail-panel')).toHaveCount(0);
});
