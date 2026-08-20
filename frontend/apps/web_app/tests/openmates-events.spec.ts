/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * frontend/apps/web_app/tests/openmates-events.spec.ts
 *
 * Deployed smoke coverage for generated OpenMates event pages and event embed
 * deep links. These checks are unauthenticated and avoid live backend state by
 * mocking app shell status endpoints while preserving the real deployed event
 * bundle and public SEO route.
 */

import { expect, test } from './helpers/cookie-audit';

const { getE2EDebugUrl } = require('./signup-flow-helpers');

const EVENT_SLUG = 'openmates-community-hour-2026-08-25';
const EVENT_TITLE = 'OpenMates Monthly Community Hour';

const SERVER_STATUS = {
	is_self_hosted: false,
	payment_enabled: true,
	server_edition: 'development',
	domain: 'openmates.org',
	ai_models_configured: true,
	free_testing_credits: null,
	anonymous_free_usage: null
};

test.beforeEach(async ({ page }) => {
	await page.route('**/v1/settings/server-status', async (route) => {
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify(SERVER_STATUS)
		});
	});
	await page.route('**/v1/analytics/beacon', async (route) => {
		await route.fulfill({ status: 204, body: '' });
	});
});

// contract-test: direct surface=gui.web assertions=newsletter.surface.semantic-parity,newsletter.campaign.event-link-fallback
test('OpenMates event SEO page serves static event HTML without 500', async ({ page }) => {
	const response = await page.request.get(getE2EDebugUrl(`/events/${EVENT_SLUG}`));
	const html = await response.text();

	expect(response.status()).toBe(200);
	expect(html).toContain(EVENT_TITLE);
	expect(html).toContain('OpenMates Events');
	expect(html).toContain(`/events/${EVENT_SLUG}`);
	expect(html).toContain('https://schema.org/EventScheduled');
	expect(html).not.toContain('Internal Error');
});

// contract-test: direct surface=gui.web assertions=newsletter.surface.semantic-parity,newsletter.campaign.accessible-event-layout
test('OpenMates event embed deep link renders details and registration CTA', async ({ page }) => {
	await page.goto(getE2EDebugUrl(`/#embed-id=${EVENT_SLUG}`), { waitUntil: 'domcontentloaded' });

	await expect(page.getByText(EVENT_TITLE).first()).toBeVisible({ timeout: 20000 });
	await expect(page.getByRole('link', { name: /register on luma/i })).toBeVisible({ timeout: 10000 });
	await expect(page.locator('body')).toContainText('Tuesday, August 25, 2026', { timeout: 10000 });
	await expect(page.locator('body')).toContainText('Online event', { timeout: 10000 });
	await expect(page.locator('body')).toContainText('OpenMates Events', { timeout: 10000 });
	await expect(page.locator('body')).toContainText('Tired of big-tech AI chatbots and agents', { timeout: 10000 });
});
