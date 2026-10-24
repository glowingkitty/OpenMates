/** Source-free execution is unavailable; historical rendering remains supported. */
import { test } from './helpers/cookie-audit';
import { expectUnavailableSkill, expectHistoricalCard } from './helpers/provider-boundary';

// contract-test: supporting surface=rest_api assertions=app-skills.providers.unavailable-no-network
test('health.search_appointments rejects unavailable execution', async ({ request }) => {
  await expectUnavailableSkill(request, 'health', 'search_appointments');
});

// contract-test: direct surface=gui.web assertions=app-skills.history.renderable
test('health.search_appointments historical card remains readable', async ({ page }) => {
  await expectHistoricalCard(page, 'health/HealthAppointmentEmbedPreview');
});
