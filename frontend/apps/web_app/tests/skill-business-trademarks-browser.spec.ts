/** Source-free execution is unavailable; historical rendering remains supported. */
import { test } from './helpers/cookie-audit';
import { expectUnavailableSkill, expectHistoricalCard } from './helpers/provider-boundary';

// contract-test: supporting surface=rest_api assertions=app-skills.providers.unavailable-no-network
test('business.search_trademarks rejects unavailable execution', async ({ request }) => {
  await expectUnavailableSkill(request, 'business', 'search_trademarks');
});

// contract-test: direct surface=gui.web assertions=app-skills.history.renderable
test('business.search_trademarks historical card remains readable', async ({ page }) => {
  await expectHistoricalCard(page, 'business/BusinessTrademarkSearchEmbedPreview');
});
