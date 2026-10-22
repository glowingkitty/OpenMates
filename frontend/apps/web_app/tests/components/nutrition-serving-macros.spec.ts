import type { Page } from '@playwright/test';
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentMotion, waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview

async function showMacrosForProof(page: Page, proteinText: string) {
  const macros = page.locator('.nutrition-grid');
  const overlay = page.locator('.unified-embed-fullscreen-overlay').filter({ has: macros });
  await waitForComponentMotion(overlay);
  const protein = macros.locator('.nutrition-value').filter({ hasText: proteinText });
  await protein.scrollIntoViewIfNeeded();
  await macros.scrollIntoViewIfNeeded();
  await expect(protein).toHaveText(proteinText);
  await expect(protein).toBeInViewport({ ratio: 1 });
  await expect(macros).toBeVisible();
  for (const item of await macros.locator('.nutrition-item').all()) {
    await expect(item.locator('.nutrition-value')).toBeInViewport({ ratio: 1 });
    await expect(item.locator('.nutrition-label')).toBeInViewport({ ratio: 1 });
  }
}

// contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
test('recipe search opens real Edamam macros on the same per-serving basis as calories', async ({ page }) => {
  await page.goto('/dev/preview/embeds/nutrition/NutritionSearchEmbedFullscreen?chrome=0&variant=edamamTotals');
  await waitForComponentPreview(page);
  const card = page.getByTestId('search-template-grid').getByTestId('embed-preview');
  await expect(card).toHaveCount(1);
  await card.click();
  await expect(page.getByTestId('result-facts')).toContainText('4 servings');
  const macros = page.locator('.nutrition-grid');
  await expect(macros).toBeVisible();
  await expect(macros.locator('.nutrition-item').filter({ hasText: 'kcal' }).locator('.nutrition-value'))
    .toHaveText('390.3');
  await expect(macros.locator('.nutrition-value')).toHaveText(['390.3', '20.4g', '7g', '65.8g']);
  // Opening the result must never present whole-recipe totals beside per-serving energy.
  await expect(macros).not.toContainText('81.44995');
  await showMacrosForProof(page, '20.4g');
});

// contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
test('legacy recipe values remain readable when opening the default search result', async ({ page }) => {
  await page.goto('/dev/preview/embeds/nutrition/NutritionSearchEmbedFullscreen?chrome=0');
  await waitForComponentPreview(page);
  const cards = page.getByTestId('search-template-grid').getByTestId('embed-preview');
  await expect(cards).toHaveCount(2);
  await cards.first().click();
  await expect(page.locator('.nutrition-grid .nutrition-value')).toHaveText(['520', '14g', '22g', '68g']);
  await showMacrosForProof(page, '14g');
});


// contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
test('direct inline recipe data opens complete provider fields and normalized macros', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/dev/preview/embeds/nutrition/NutritionRecipeEmbedFullscreen?chrome=0&variant=directData');
  await waitForComponentPreview(page);
  const viewport = page.getByTestId('component-preview-viewport');
  await expect(viewport).toContainText('Slow cooker chickpeas and spinach stew');
  await expect(viewport).toContainText('350 g of dry chickpeas, soaked in water for 12 hours');
  await expect(viewport).toContainText('200 g spinach or swiss chard');
  await expect(viewport).toContainText('Heat the oil in a small pan over high heat.');
  await page.getByTestId('nutrition-recipe-tags').getByRole('button').click();
  await expect(page.getByRole('tooltip')).toContainText('Vegetarian');
  await page.keyboard.press('Escape');
  await page.getByTestId('nutrition-recipe-categories').getByRole('button').click();
  await expect(page.getByRole('tooltip')).toContainText('american');
  await page.keyboard.press('Escape');
  await expect(page.locator('.nutrition-grid .nutrition-value')).toHaveText(['390.3', '20.4g', '7g', '65.8g']);
  await expect(viewport.getByText('Render Error', { exact: true })).toHaveCount(0);
  expect(errors).toEqual([]);
  await showMacrosForProof(page, '20.4g');
});
