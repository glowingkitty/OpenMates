/** Source-free execution is unavailable; historical rendering remains supported. */
import { test } from './helpers/cookie-audit';
import { expectUnavailableSkill, expectHistoricalCard } from './helpers/provider-boundary';

// contract-test: supporting surface=rest_api assertions=app-skills.providers.unavailable-no-network
test('models3d.search rejects unavailable execution', async ({ request }) => {
  await expectUnavailableSkill(request, 'models3d', 'search');
});

// contract-test: direct surface=gui.web assertions=app-skills.history.renderable
test('models3d.search historical card remains readable', async ({ page }) => {
  await expectHistoricalCard(page, 'models3d/Model3DSearchEmbedPreview');
});
