import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
// contract-test: supporting surface=gui.web assertions=tasks.lifecycle.visible,tasks.surface.semantic-parity
test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 1512, height: 921 });
  await page.addInitScript(() => {
    window.addEventListener('task-board-preview-action', (event) => {
      document.documentElement.dataset.taskBoardAction = String((event as CustomEvent<string>).detail);
    });
  });
  await page.goto('/dev/preview/tasks/TaskBoard?theme=light&background=%23f3f3f3&width=1320&chrome=0');
  await waitForComponentPreview(page);
});

for (const theme of ['light', 'dark']) {
  // contract-test: supporting surface=gui.web assertions=tasks.surface.semantic-parity,tasks.lifecycle.visible
  test(`smoothly scales draggable cards to 1.1 on mouse hover in ${theme} mode`, async ({ page }, testInfo) => {
    if (theme === 'dark') {
      await page.goto('/dev/preview/tasks/TaskBoard?theme=dark&background=%23131313&width=1320&chrome=0');
      await waitForComponentPreview(page);
    }
    const board = page.getByTestId('task-board');
    const card = page.getByTestId('task-card').filter({ hasText: 'Design 3D model' });
    const open = card.getByTestId('task-card-open');
    await expect(card).toHaveCSS('transform', 'none');
    const initialBox = await card.boundingBox();
    const boardBox = await board.boundingBox();
    expect(initialBox && boardBox).toBeTruthy();
    const initialShadow = await card.evaluate((element) => getComputedStyle(element).boxShadow);
    await expect(open).toHaveCSS('cursor', 'grab');
    const motion = await card.evaluate((element) => {
      const style = getComputedStyle(element);
      return { properties: style.transitionProperty, durations: style.transitionDuration };
    });
    expect(motion.properties).toContain('transform');
    expect(motion.durations.split(',').every((duration) => parseFloat(duration) > 0)).toBe(true);

    await open.hover();
    await expect.poll(() => card.evaluate((element) => {
      const matrix = new DOMMatrix(getComputedStyle(element).transform);
      return { x: matrix.a, y: matrix.d, rotation: matrix.b };
    })).toEqual({ x: 1.1, y: 1.1, rotation: 0 });
    const hoveredBox = await card.boundingBox();
    expect(hoveredBox).not.toBeNull();
    expect(hoveredBox!.width / initialBox!.width).toBeCloseTo(1.1, 2);
    expect(hoveredBox!.height / initialBox!.height).toBeCloseTo(1.1, 2);
    expect(await board.boundingBox()).toEqual(boardBox);
    expect(await card.evaluate((element) => getComputedStyle(element).boxShadow)).not.toBe(initialShadow);
    const expandedEdgeIsClickable = await page.evaluate(({ x, y }) => {
      return document.elementFromPoint(x, y)?.closest('[data-task-id]')?.getAttribute('data-task-id');
    }, { x: hoveredBox!.x + 2, y: hoveredBox!.y + hoveredBox!.height / 2 });
    expect(expandedEdgeIsClickable).toBe('preview-todo');
    await testInfo.attach(`task-card-hover-${theme}`, { body: await board.screenshot(), contentType: 'image/png' });

    await page.mouse.move(0, 0);
    await expect(card).toHaveCSS('transform', 'none');
    const settledBox = await card.boundingBox();
    expect(settledBox!.width).toBeCloseTo(initialBox!.width, 2);
    expect(settledBox!.height).toBeCloseTo(initialBox!.height, 2);
    await expect(card).toHaveCSS('box-shadow', initialShadow);
  });
}

// contract-test: supporting surface=gui.web assertions=tasks.surface.semantic-parity
test('keeps the hover highlight immediate when reduced motion is requested', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const card = page.getByTestId('task-card').filter({ hasText: 'Design 3D model' });
  await card.getByTestId('task-card-open').hover();
  await expect(card).toHaveCSS('transform', 'matrix(1.1, 0, 0, 1.1, 0, 0)');
  await expect(card).toHaveCSS('transition-duration', '0s');
});

// contract-test: supporting surface=gui.web assertions=tasks.surface.semantic-parity
test('keeps read-only workflow projections from advertising drag support', async ({ page }) => {
  const card = page.getByTestId('task-card').filter({ hasText: 'Daily Weather Report' });
  await expect(card).toHaveAttribute('draggable', 'false');
  const open = card.getByTestId('workflow-run-projection');
  await open.hover();
  await expect(open).toHaveCSS('cursor', 'pointer');
  await expect(card).toHaveCSS('transform', 'none');
});

// contract-test: supporting surface=gui.web assertions=tasks.lifecycle.visible,tasks.surface.semantic-parity
test('moves a task with a native pointer drag from its clickable card surface', async ({ page }) => {
  const card = page.getByTestId('task-card').filter({ hasText: 'Design 3D model' });
  const target = page.getByTestId('task-column-in_progress');
  await card.getByTestId('task-card-open').hover();
  await expect(card).toHaveCSS('transform', 'matrix(1.1, 0, 0, 1.1, 0, 0)');
  await card.getByTestId('task-card-open').dragTo(target, { targetPosition: { x: 80, y: 20 } });
  await expect(page.locator('html')).toHaveAttribute('data-task-board-action', 'move:preview-todo:in_progress');
  await expect(card).toHaveAttribute('data-drag-state', 'settled');
  await expect(page.getByTestId('task-column-drop-target-in_progress')).toHaveCount(0);
});

// contract-test: supporting surface=gui.web assertions=tasks.lifecycle.visible
test('keeps an internal task move when the drop has no transferred identifier', async ({ page }) => {
  const card = page.getByTestId('task-card').filter({ hasText: 'Design 3D model' });
  await card.getByTestId('task-card-open').hover();
  await card.evaluate((element) => {
    element.dispatchEvent(new DragEvent('dragstart', { bubbles: true, cancelable: true, dataTransfer: new DataTransfer() }));
  });
  await expect(card).toHaveAttribute('data-drag-state', 'picked-up');
  await expect(card.getByTestId('task-card-open')).toHaveCSS('cursor', 'grabbing');
  await expect.poll(() => card.evaluate((element) => {
    const matrix = new DOMMatrix(getComputedStyle(element).transform);
    return Math.round(Math.atan2(matrix.b, matrix.a) * 180 / Math.PI);
  })).toBe(3);
  await page.getByTestId('task-column-in_progress').evaluate((element) => {
    element.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: new DataTransfer() }));
  });
  await expect(page.locator('html')).toHaveAttribute('data-task-board-action', 'move:preview-todo:in_progress');
  await card.evaluate((element) => element.dispatchEvent(new DragEvent('dragend', { bubbles: true })));
  await expect(card).toHaveAttribute('data-drag-state', 'settled');
  await expect(page.locator('body > [aria-hidden="true"].task-card')).toHaveCount(0);
});
