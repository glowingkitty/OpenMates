/** Source-free execution is unavailable; historical rendering remains supported. */
import { test } from './helpers/cookie-audit';
import { expectUnavailableSkill, expectHistoricalCard } from './helpers/provider-boundary';

// contract-test: supporting surface=rest_api assertions=app-skills.providers.unavailable-no-network
test('shopping.search_products rejects unavailable execution', async ({ request }) => {
  await expectUnavailableSkill(request, 'shopping', 'search_products');
});

// contract-test: direct surface=gui.web assertions=app-skills.history.renderable
test('shopping.search_products historical card remains readable', async ({ page }) => {
  await expectHistoricalCard(page, 'shopping/ShoppingResultEmbedFullscreen');
});
