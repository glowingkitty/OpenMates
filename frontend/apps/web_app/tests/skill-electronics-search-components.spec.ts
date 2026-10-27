/** Source-free execution is unavailable; historical rendering remains supported. */
import { test } from './helpers/cookie-audit';
import { expectUnavailableSkill, expectHistoricalCard } from './helpers/provider-boundary';

// contract-test: supporting surface=rest_api assertions=app-skills.providers.unavailable-no-network
test('electronics.search_components rejects unavailable execution', async ({ request }) => {
  await expectUnavailableSkill(request, 'electronics', 'search_components');
});

// contract-test: direct surface=gui.web assertions=app-skills.history.renderable
test('electronics.search_components historical card remains readable', async ({ page }) => {
  await expectHistoricalCard(page, 'electronics/ElectronicsComponentEmbedPreview');
});
