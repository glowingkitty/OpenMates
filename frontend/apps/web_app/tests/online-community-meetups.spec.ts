/* eslint-disable @typescript-eslint/no-require-imports */
/** Verify online-only community listings and the October 2026 community hour. */
import { expect, test } from './helpers/cookie-audit';

const { getE2EDebugUrl } = require('./signup-flow-helpers');
const EVENT_SLUG = 'openmates-community-hour-2026-10-27';
const EVENT_TITLE = 'OpenMates Monthly Community Hour';

test.use({ locale: 'en-US', timezoneId: 'Europe/Berlin' });

test.beforeEach(async ({ page }) => {
	// Keep the scheduled events visible independently of the day CI runs.
	await page.clock.setFixedTime(new Date('2026-09-26T10:00:00+02:00'));
	await page.route('**/v1/settings/server-status', async (route) => {
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({
				is_self_hosted: false, payment_enabled: true,
				server_edition: 'development', domain: 'openmates.org',
				ai_models_configured: true, free_testing_credits: null, anonymous_free_usage: null,
			}),
		});
	});
	await page.route('**/v1/analytics/beacon', (route) => route.fulfill({ status: 204, body: '' }));
});

// contract-test: direct surface=gui.web assertions=newsletter.surface.semantic-parity,newsletter.campaign.event-link-fallback
test('public event pages publish the October online community hour and omit the cancelled meetup', async ({ page }) => {
	const index = await page.request.get(getE2EDebugUrl('/events'));
	expect(index.status()).toBe(200);
	const indexHtml = await index.text();
	expect(indexHtml).toContain(`/events/${EVENT_SLUG}`);
	expect(indexHtml).not.toContain('/events/openmates-berlin-meetup-2026-09-26');

	await page.goto(getE2EDebugUrl(`/events/${EVENT_SLUG}`));
	await expect(page.getByRole('heading', { name: EVENT_TITLE, exact: true })).toBeVisible();
	await expect(page.locator('time').first()).toHaveText('Tuesday, October 27, 2026');
	await expect(page.locator('time').nth(1)).toHaveText('7:00 PM to 8:00 PM');
	const jsonLd = JSON.parse(await page.locator('script[type="application/ld+json"]').textContent() || '{}');
	expect(jsonLd.startDate).toBe('2026-10-27T19:00:00+01:00');
	expect(jsonLd.endDate).toBe('2026-10-27T20:00:00+01:00');
	expect(jsonLd.eventAttendanceMode).toBe('https://schema.org/OnlineEventAttendanceMode');
	await expect(page.getByRole('link', { name: 'Register on Luma', exact: true })).toHaveAttribute('href', /^https:\/\/luma\.com\//);
	const image = await page.request.get(`/event-assets/openmates/${EVENT_SLUG}.jpg`);
	expect(image.status()).toBe(200);
	expect(image.headers()['content-type']).toContain('image/jpeg');
});

// contract-test: direct surface=gui.web assertions=newsletter.surface.semantic-parity,newsletter.campaign.accessible-event-layout
test('sidebar lists only online events and opens the October community hour', async ({ page }) => {
	await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
	const history = page.getByTestId('activity-history-wrapper');
	if (!(await history.isVisible().catch(() => false))) {
		await page.getByTestId('sidebar-toggle').click();
	}
	await expect(history).toBeVisible({ timeout: 10000 });
	const events = page.getByTestId('events-group');
	await expect(events).toBeVisible();
	await events.getByTestId('show-more-events').click();
	await expect(events.getByTestId('event-list-item')).toHaveCount(6);
	await events.getByTestId('show-more-events').click();
	const entries = events.getByTestId('event-list-item');
	await expect(entries).toHaveCount(7);
	for (const entry of await entries.all()) {
		await expect(entry).toContainText('Online');
	}
	await expect(events).not.toContainText('Monthly Meetup Berlin');
	const october = entries.filter({ hasText: EVENT_TITLE }).filter({ hasText: 'Oct' });
	await expect(october).toContainText('27');
	await october.click();
	await expect(page.locator('body')).toContainText('Tuesday, October 27, 2026');
	await expect(page.locator('body')).toContainText('7:00 PM to 8:00 PM');
	await expect(page.getByTestId('external-provider-cta').first()).toHaveText('Register on Luma');
});
