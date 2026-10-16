// playwright-account: not_required reason=isolated_component_preview
import { test, expect } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
import { configureFixtureImageProxy } from '../landing-app-example-admission';
import { vegetarianRecipesFromFridgeVegetablesChat } from '../../../../packages/ui/src/demo_chats/data/example_chats/vegetarian-recipes-from-fridge-vegetables';

const payload = {
  id: 'recipe_preference', type: 'choice', multiple: false,
  question: 'Which cooking style would you prefer to make today?',
  options: [
    { id: 'salad', text: 'Fresh & crunchy chopped salad', embed_ids: ['thai-chopped-spinach-Gfw'] },
    { id: 'fritters', text: 'Crispy pan-fried fritters or patties', embed_ids: ['chickpea-fritters-with-qY9'] },
  ],
};

// contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction,chats.surface.semantic-parity
test('recipe option previews retain their public example source through questionnaire roots', async ({ page }) => {
  await configureFixtureImageProxy(page, vegetarianRecipesFromFridgeVegetablesChat);
  // Exercise both a bare component root and the imperative TipTap question mount.
  for (const path of ['interactive_questions/InteractiveQuestionContainer', 'ReadOnlyMessage']) {
    const params = new URLSearchParams({ theme: 'light', background: '#dbeafe', width: '900', chrome: '0' });
    if (path === 'ReadOnlyMessage') {
      params.set('props', JSON.stringify({ role: 'assistant', chatId: 'example-vegetarian-recipes-from-fridge', content: '```interactive_question\n' + JSON.stringify(payload) + '\n```' }));
    } else params.set('variant', 'recipe_options');
    await page.goto(`/dev/preview/${path}?${params}`);
    await waitForComponentPreview(page);
    const card = page.getByTestId('interactive-question-card');
    await expect(card.getByText(payload.question, { exact: true })).toBeVisible();
    const salad = card.getByTestId('interactive-question-option-salad');
    const fritters = card.getByTestId('interactive-question-option-fritters');
    await expect(salad.locator('.recipe-title')).toHaveText('Thai Chopped Spinach Salad with Chickpeas');
    await expect(fritters.locator('.recipe-title')).toHaveText('Chickpea Fritters with Veggies');
    await expect(card.getByText('Preview unavailable', { exact: true })).toHaveCount(0);
    for (const option of [salad, fritters]) {
      const image = option.getByTestId('nutrition-recipe-preview-image');
      await image.scrollIntoViewIfNeeded();
      await expect(image).toBeVisible();
      await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.complete && element.naturalWidth > 0), {
        message: 'The saved public recipe photo loads real image bytes',
      }).toBe(true);
    }
    await expect(card.getByTestId('interactive-question-send')).toBeDisabled();
    await salad.getByText('Fresh & crunchy chopped salad', { exact: true }).click();
    await expect(card.getByTestId('interactive-question-send')).toBeEnabled();
    const geometry = await card.evaluate((element) => ({ width: element.clientWidth, scrollWidth: element.scrollWidth }));
    expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.width + 1);
  }
});
