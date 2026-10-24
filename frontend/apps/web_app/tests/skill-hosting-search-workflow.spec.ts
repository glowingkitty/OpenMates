/** Source-free execution is unavailable; historical rendering remains supported. */
import { test } from './helpers/cookie-audit';
import { expectUnavailableSkill, expectHistoricalCard } from './helpers/provider-boundary';

// contract-test: supporting surface=rest_api assertions=app-skills.providers.unavailable-no-network
test('hosting.search_domains rejects unavailable execution', async ({ request }) => {
  await expectUnavailableSkill(request, 'hosting', 'search_domains');
});

// contract-test: direct surface=gui.web assertions=app-skills.history.renderable
test('hosting.search_domains historical card remains readable', async ({ page }) => {
  await expectHistoricalCard(page, 'hosting/HostingDomainEmbedFullscreen');
});
