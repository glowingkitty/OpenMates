// playwright-account: not_required reason=public_logged_out_example_admission
/* eslint-disable @typescript-eslint/no-require-imports */
import { test, expect } from './helpers/cookie-audit';
import { configureFixtureImageProxy } from './landing-app-example-admission';
import { vegetarianRecipesFromFridgeVegetablesChat } from '../../../packages/ui/src/demo_chats/data/example_chats/vegetarian-recipes-from-fridge-vegetables';
const { openFullscreen, closeFullscreen } = require('./helpers/embed-test-helpers');

for (const [viewport, size] of [['phone', { width: 390, height: 844 }], ['laptop', { width: 1440, height: 1000 }]] as const) {
// contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity,chats.rendering.inline-entity-interaction
test(`public vegetarian questionnaire reuses real recipe previews and fullscreen on ${viewport}`,  async ({ page }) => {
  test.setTimeout(120_000);
  const ownerEmbedRequests: string[] = [];
  page.on('request', (request) => {
    if (request.method() === 'GET' && /\/v1\/embeds\/chats\/[^/]+\/embeds\/[^/?]+/.test(new URL(request.url()).pathname)) {
      ownerEmbedRequests.push(request.url());
    }
  });
  await configureFixtureImageProxy(page, vegetarianRecipesFromFridgeVegetablesChat);
  await page.setViewportSize(size);
  await page.goto('/example/vegetarian-recipes-from-fridge-vegetables', { waitUntil: 'domcontentloaded' });
  await expect(page).toHaveURL(/#chat-id=example-vegetarian-recipes-from-fridge$/, { timeout: 30_000 });
  const question = page.getByTestId('interactive-question-card').filter({ hasText: 'Which cooking style would you prefer to make today?' });
  await question.scrollIntoViewIfNeeded();
  await expect(question).toBeVisible();
  const send = question.getByTestId('interactive-question-send');
  await expect(send).toBeDisabled();
  for (const [optionId, label, title] of [
    ['salad', 'Fresh & crunchy chopped salad', 'Thai Chopped Spinach Salad with Chickpeas'],
    ['fritters', 'Crispy pan-fried fritters or patties', 'Chickpea Fritters with Veggies'],
  ]) {
    const option = question.getByTestId(`interactive-question-option-${optionId}`);
    await expect(option.locator('.recipe-title')).toHaveText(title);
    await expect(option.getByText('Preview unavailable', { exact: true })).toHaveCount(0);
    const image = option.getByTestId('nutrition-recipe-preview-image');
    await image.scrollIntoViewIfNeeded();
    await expect(image).toBeVisible();
    await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.complete && element.naturalWidth > 0), {
      message: 'The saved public recipe photo loads real image bytes',
    }).toBe(true);
    await option.getByText(label, { exact: true }).click();
    await expect(send).toBeEnabled();
    const fullscreen = await openFullscreen(page, option.getByTestId('embed-preview'));
    await expect(fullscreen.locator('.recipe-fullscreen .title')).toHaveText(title);
    await closeFullscreen(page, fullscreen);
    await expect(question).toBeVisible();
    await expect(send).toBeEnabled();
  }
  expect(ownerEmbedRequests, 'Known public recipe refs resolve from their example source without owner-only embed fetches').toEqual([]);
});
}
