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
import { getOpenMatesEventBySlug } from '../../../packages/ui/src/data/openmatesEvents';

const { getE2EDebugUrl } = require('./signup-flow-helpers');

const EVENT_SLUG = 'openmates-teams-webinar-2026-10-14';
const EVENT = getOpenMatesEventBySlug(EVENT_SLUG);
if (!EVENT) throw new Error(`Missing generated OpenMates event ${EVENT_SLUG}`);
const EVENT_TITLE = EVENT.title;
const EVENT_EMBED_HASH = `#embed-id=${encodeURIComponent(EVENT.embed_id)}`;

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

// contract-test: direct surface=gui.web assertions=newsletter.surface.semantic-parity,newsletter.campaign.event-link-fallback,marketing-landing.public-content,marketing-landing.destinations
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

// contract-test: direct surface=gui.web assertions=newsletter.campaign.event-link-fallback,newsletter.campaign.accessible-event-layout,marketing-landing.public-content,marketing-landing.destinations
test('human event SEO navigation forwards to the matching app event detail', async ({ page }) => {
	await page.goto(getE2EDebugUrl(`/events/${EVENT_SLUG}`), { waitUntil: 'domcontentloaded' });

	await expect.poll(() => new URL(page.url()).hash, { timeout: 20000 }).toContain(EVENT_EMBED_HASH);
	expect(new URL(page.url()).pathname).toBe('/');
	await expect(page.getByText(EVENT_TITLE).first()).toBeVisible({ timeout: 20000 });
	await expect(page.getByText('Register on Luma').first()).toBeVisible({ timeout: 10000 });
	await expect(page.locator('body')).toContainText(EVENT.organizer.name);
	await expect(page.locator('body')).toContainText(EVENT.description.slice(0, 45));
});

test.describe('event SEO crawler view', () => {
	test.use({ userAgent: 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)' });

	// contract-test: direct surface=gui.web assertions=newsletter.campaign.event-link-fallback,newsletter.campaign.accessible-event-layout,marketing-landing.public-content,marketing-landing.destinations
	test('Googlebot keeps the crawlable event article and interactive CTA at the SEO URL', async ({ page }) => {
		const response = await page.goto(`/events/${EVENT_SLUG}`, { waitUntil: 'networkidle' });

		expect(response?.status()).toBe(200);
		await expect(page.getByRole('article').getByRole('heading', { name: EVENT_TITLE })).toBeVisible();
		await expect(page.getByRole('article')).toContainText(EVENT.summary);
		await expect(page.getByRole('link', { name: 'Open event in OpenMates' })).toHaveAttribute('href', new RegExp(`${EVENT_EMBED_HASH}$`));
		await expect(page.getByRole('link', { name: 'Register on Luma' })).toHaveAttribute('href', EVENT.url);
		const jsonLd = await page.locator('script[type="application/ld+json"]').first().textContent();
		expect(JSON.parse(jsonLd ?? '{}')).toMatchObject({
			'@type': 'Event',
			name: EVENT_TITLE,
			startDate: EVENT.date_start,
			eventStatus: 'https://schema.org/EventScheduled'
		});
		expect(new URL(page.url()).pathname).toBe(`/events/${EVENT_SLUG}`);
	});
});

// contract-test: direct surface=gui.web assertions=newsletter.surface.semantic-parity,newsletter.campaign.accessible-event-layout
test('OpenMates event embed deep link renders details and registration CTA', async ({ page }) => {
	await page.goto(getE2EDebugUrl(`/${EVENT_EMBED_HASH}`), { waitUntil: 'domcontentloaded' });

	await expect(page.getByText(EVENT_TITLE).first()).toBeVisible({ timeout: 20000 });
	await expect(page.getByText('Register on Luma').first()).toBeVisible({ timeout: 10000 });
	await expect(page.locator('body')).toContainText('October 14, 2026', { timeout: 10000 });
	await expect(page.locator('body')).toContainText('Online event', { timeout: 10000 });
	await expect(page.locator('body')).toContainText('OpenMates Events', { timeout: 10000 });
	await expect(page.locator('body')).toContainText(EVENT.description.slice(0, 45), { timeout: 10000 });
});

// contract-test: direct surface=gui.web assertions=newsletter.surface.semantic-parity
test('chat sidebar lists the three latest release news links below events', async ({ page }) => {
	await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });

	const history = page.getByTestId('activity-history-wrapper');
	if (!(await history.isVisible().catch(() => false))) {
		await page.getByTestId('sidebar-toggle').click();
	}
	await expect(history).toBeVisible({ timeout: 10000 });

	const newsGroup = page.getByTestId('latest-news-group');
	await expect(newsGroup).toBeVisible();
	const links = newsGroup.getByTestId('latest-news-item');
	await expect(links).toHaveCount(3);
	await expect(links.nth(0)).toHaveAttribute('href', '/news/introducing-openmates-v011');
	await expect(links.nth(1)).toHaveAttribute('href', '/news/introducing-openmates-v010');
	await expect(links.nth(2)).toHaveAttribute('href', '/news/introducing-openmates-v09');
	await expect(links.nth(0)).not.toHaveAttribute('target', '_blank');
});
