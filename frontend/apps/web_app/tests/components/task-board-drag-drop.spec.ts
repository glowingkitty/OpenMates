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

// contract-test: supporting surface=gui.web assertions=tasks.lifecycle.visible,tasks.surface.semantic-parity
test('moves a task with a native pointer drag from its clickable card surface', async ({ page }) => {
  const card = page.getByTestId('task-card').filter({ hasText: 'Design 3D model' });
  const target = page.getByTestId('task-column-in_progress');
  await card.getByTestId('task-card-open').dragTo(target, { targetPosition: { x: 80, y: 20 } });
  await expect(page.locator('html')).toHaveAttribute('data-task-board-action', 'move:preview-todo:in_progress');
  await expect(card).toHaveAttribute('data-drag-state', 'settled');
  await expect(page.getByTestId('task-column-drop-target-in_progress')).toHaveCount(0);
});

// contract-test: supporting surface=gui.web assertions=tasks.lifecycle.visible
test('keeps an internal task move when the drop has no transferred identifier', async ({ page }) => {
  const card = page.getByTestId('task-card').filter({ hasText: 'Design 3D model' });
  await card.evaluate((element) => {
    element.dispatchEvent(new DragEvent('dragstart', { bubbles: true, cancelable: true, dataTransfer: new DataTransfer() }));
  });
  await expect(card).toHaveAttribute('data-drag-state', 'picked-up');
  await page.getByTestId('task-column-in_progress').evaluate((element) => {
    element.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: new DataTransfer() }));
  });
  await expect(page.locator('html')).toHaveAttribute('data-task-board-action', 'move:preview-todo:in_progress');
  await card.evaluate((element) => element.dispatchEvent(new DragEvent('dragend', { bubbles: true })));
  await expect(card).toHaveAttribute('data-drag-state', 'settled');
  await expect(page.locator('body > [aria-hidden="true"].task-card')).toHaveCount(0);
});
