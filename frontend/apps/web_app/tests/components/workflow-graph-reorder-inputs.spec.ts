// playwright-account: not_required reason=isolated_component_preview
/* eslint-disable @typescript-eslint/no-require-imports -- Existing Playwright helper exports. */
export {};
import type { Page } from '@playwright/test';
const { expect, test } = require('../helpers/cookie-audit');

const preview = '/dev/preview/workflows/WorkflowGraphRenderer?variant=typedControls&theme=light&background=%23dbeafe&width=900&chrome=0';

// contract-test: direct surface=gui.web assertions=workflows-ui.mvp.authoring
test('workflow card movement and typed skill inputs render in bare preview', async ({ page }: { page: Page }) => {
  await page.goto(preview, { waitUntil: 'domcontentloaded' });
  await expect(page.getByTestId('component-preview-canvas')).toHaveAttribute('data-preview-ready', 'true', { timeout: 30000 });
  await expect(page.getByTestId('preview-toolbar')).toHaveCount(0);

  const fitness = page.locator('[data-node-id="fitness"]');
  await expect(fitness.getByTestId('workflow-node-summary')).toHaveAttribute('draggable', 'true');
  await fitness.getByTestId('workflow-node-summary').click();
  await expect(fitness.getByTestId('workflow-node-move-up')).toHaveCount(0);
  const moveDown = fitness.getByTestId('workflow-node-move-down');
  await expect(moveDown).toBeVisible();
  await moveDown.focus();
  await expect(moveDown).toBeFocused();
  await expect(fitness.getByTestId('workflow-schema-field-city').locator('.type-badge')).toHaveText('Location');
  await fitness.getByTestId('workflow-schema-field-city').getByTestId('workflow-node-location-picker').click();
  await expect(fitness.getByTestId('workflow-location-map')).toBeVisible();
  await fitness.getByTestId('workflow-schema-field-city').getByTestId('workflow-node-location-picker').click();
  await expect(fitness.getByTestId('workflow-location-map')).toHaveCount(0);
  await expect(fitness.getByTestId('workflow-schema-field-date-range')).toBeVisible();
  await expect(fitness.locator('input[id$="start_date"], input[id$="end_date"]')).toHaveCount(0);
  await fitness.getByTestId('workflow-date-range-specific').click();
  const classCalendar = fitness.getByTestId('workflow-date-range-control');
  await expect(classCalendar).toBeVisible();
  await expect(fitness.getByTestId('workflow-date-range-specific')).toHaveCSS('color', 'rgb(255, 255, 255)');
  await classCalendar.getByRole('button', { name: 'Next month' }).click();
  await expect(classCalendar.getByRole('button', { name: 'Next month' })).toBeEnabled();
  await classCalendar.getByRole('button', { name: 'Next month' }).click();
  const availableDays = await classCalendar.locator('.day:not([disabled])').evaluateAll(buttons => buttons.map(button => Number((button as HTMLElement).dataset.day)));
  expect(availableDays.length).toBeGreaterThan(24);
  await classCalendar.locator(`[data-day="${availableDays[2]}"]`).click();
  await classCalendar.locator(`[data-day="${availableDays[24]}"]`).click();
  const boundaries = await classCalendar.locator('.day.range-boundary').evaluateAll(buttons => buttons.map(button => Number((button as HTMLElement).dataset.day)));
  expect(boundaries.at(-1)! - boundaries[0]).toBe(13);
  await fitness.locator('.editor-header .close-button').click();

  const stays = page.locator('[data-node-id="stays"]');
  await stays.getByTestId('workflow-node-summary').click();
  await expect(stays.getByTestId('workflow-node-move-up')).toBeVisible();
  await expect(stays.getByTestId('workflow-node-move-down')).toHaveCount(0);
  await expect(stays.getByTestId('workflow-schema-field-date-range')).toBeVisible();
  await expect(stays.locator('input[id$="check_in_date"], input[id$="check_out_date"]')).toHaveCount(0);
  await stays.getByTestId('workflow-date-range-specific').click();
  await expect(stays.getByTestId('workflow-date-range-control')).toBeVisible();

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(stays.getByTestId('workflow-node-move-up')).toBeVisible();
  await expect(stays.getByTestId('workflow-schema-field-date-range')).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});
