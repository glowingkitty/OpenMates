import type { Locator, Page } from '@playwright/test';
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
// Project tiles show description, icon and category gradient (TASK-1807); the
// appearance settings offer the category gradients and the icon list.

async function openTiles(page: Page, width: number, height: number) {
  await page.setViewportSize({ width, height });
  const query = new URLSearchParams({ theme: 'light', width: String(width), chrome: '0', variant: 'presentationTiles' });
  await page.goto(`/dev/preview/projects/ProjectsPage?${query}`, { waitUntil: 'domcontentloaded' });
  return waitForComponentPreview(page);
}

function tile(scope: Page | Locator, title: string): Locator {
  return scope.getByTestId('project-landing-card').filter({ hasText: title }).first();
}

async function attach(page: Page, name: string): Promise<void> {
  await test.info().attach(name, { body: await page.screenshot({ fullPage: false }), contentType: 'image/png' });
}

// contract-test: direct surface=gui.web assertions=projects.presentation.tile
test('desktop tiles show description, icon and the category gradient', async ({ page }) => {
  await openTiles(page, 1440, 1000);
  const row = page.getByTestId('project-mixed-row');
  const recipes = tile(row, 'Recipe Keeper');
  await expect(recipes).toBeVisible();
  await expect(recipes).toContainText('Save, plan and cook your family recipes in one place.');
  await expect(recipes).toHaveAttribute('data-category', 'cooking_food');
  await expect(recipes).toHaveAttribute('data-icon', 'chef-hat');
  expect(await recipes.getAttribute('style')).not.toContain('--color-app-projects');
  await expect(tile(row, 'Household budget')).toHaveAttribute('data-category', 'finance');
  const legacy = tile(row, 'OpenMates');
  await expect(legacy).toHaveAttribute('data-icon', 'folder');
  expect(await legacy.getAttribute('style')).toContain('--color-app-projects');
  expect(await recipes.getAttribute('style')).not.toEqual(await tile(row, 'Household budget').getAttribute('style'));
  await attach(page, 'desktop-project-tiles');

  await page.getByTestId('projects-show-all').click();
  const grid = page.getByTestId('all-projects-grid');
  await expect(tile(grid, 'Kitchen renovation')).toContainText('Plans, quotes and building steps for the new kitchen.');
  await expect(tile(grid, 'Kitchen renovation')).toHaveAttribute('data-category', 'maker_prototyping');
  await attach(page, 'desktop-all-projects-grid');
});

// contract-test: direct surface=gui.web assertions=projects.presentation.tile
test('phone tiles keep the description readable without horizontal overflow', async ({ page }) => {
  await openTiles(page, 390, 844);
  const recipes = tile(page.getByTestId('project-mixed-row'), 'Recipe Keeper');
  await expect(recipes).toBeVisible();
  await expect(recipes.locator('.resume-large-summary')).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  await attach(page, 'phone-project-tiles');
});

// contract-test: direct surface=gui.web assertions=projects.presentation.manual-lock
test('appearance settings offer the category gradients and the icon list', async ({ page }) => {
  await page.setViewportSize({ width: 720, height: 900 });
  await page.goto('/dev/preview/settings/ProjectAppearanceSettings?theme=light&width=720&chrome=0', { waitUntil: 'domcontentloaded' });
  await waitForComponentPreview(page);
  const category = page.getByTestId('project-appearance-category');
  await expect(category).toBeVisible();
  await expect(category).toContainText('Cooking and food');
  await expect(page.getByTestId('project-appearance-icon')).toHaveValue('chef-hat');
  await category.click();
  // Scoped to the category listbox: the icon list is a native select whose options also have role=option.
  const categoryList = page.getByRole('listbox', { name: 'Project category' });
  await expect(categoryList.getByRole('option')).toHaveCount(16);
  await expect(categoryList.getByRole('option', { name: 'Software development' })).toBeVisible();
  await attach(page, 'appearance-category-options');
});
