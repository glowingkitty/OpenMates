/** Source-free execution is unavailable; historical rendering remains supported. */
import { test } from './helpers/cookie-audit';
import { expectUnavailableSkill, expectHistoricalCard } from './helpers/provider-boundary';

// contract-test: supporting surface=rest_api assertions=app-skills.providers.unavailable-no-network
test('travel.search_connections rejects unavailable execution', async ({ request }) => {
  await expectUnavailableSkill(request, 'travel', 'search_connections');
});

// contract-test: direct surface=gui.web assertions=app-skills.history.renderable
test('travel.search_connections historical card remains readable', async ({ page }) => {
  await expectHistoricalCard(page, 'travel/TravelConnectionEmbedPreview');
});
