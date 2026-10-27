/** Source-free execution is unavailable; historical rendering remains supported. */
import { test } from './helpers/cookie-audit';
import { expectUnavailableSkill, expectHistoricalCard } from './helpers/provider-boundary';

// contract-test: supporting surface=rest_api assertions=app-skills.providers.unavailable-no-network
test('fitness.search_locations rejects unavailable execution', async ({ request }) => {
  await expectUnavailableSkill(request, 'fitness', 'search_locations');
});

// contract-test: direct surface=gui.web assertions=app-skills.history.renderable
test('fitness.search_locations historical card remains readable', async ({ page }) => {
  await expectHistoricalCard(page, 'fitness/FitnessSearchEmbedPreview');
});
