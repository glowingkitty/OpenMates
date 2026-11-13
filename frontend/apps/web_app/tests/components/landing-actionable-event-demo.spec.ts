/**
 * The guest intro "Actionable" event demo shows only what event search really
 * returns from public web pages: an upcoming event with title, date, city and
 * its own page. No RSVP counts, organizer names or placeholder provider text.
 * Runs in bare component preview, so it needs no account or inference.
 */
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
// proof-video: not_required reason=isolated_component_preview
const LEFTOVER_COPY = /event website|RSVP|Zusagen|Fluence|DEPIN|Heeresb/i;

for (const profile of [{ width: 390, language: 'de', cta: 'Eventseite öffnen' }, { width: 1280, language: 'en', cta: 'Open event page' }]) {
  // contract-test: direct surface=gui.web assertions=authored-results.demonstrations.proven-capability
  test(`event demo matches web-sourced results at ${profile.width}px ${profile.language}`, async ({ page }, testInfo) => {
    test.setTimeout(60_000);
    await page.setViewportSize({ width: profile.width, height: 800 });
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    await page.addInitScript(language => localStorage.setItem('preferredLanguage', language), profile.language);
    const query = new URLSearchParams({ chrome: '0', width: String(profile.width), theme: 'dark', background: '#161616' });
    await page.goto(`/dev/preview/landing/LandingActionableEventDemo?${query}`, { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page, 30_000);
    const demo = page.getByTestId('landing-actionable-event-demo');
    await expect(demo).toHaveAttribute('data-playing', 'true');

    await expect(demo).toHaveAttribute('data-active-stage', 'user-request');
    await expect(demo.getByTestId('landing-actionable-user-message')).toBeVisible();
    await testInfo.attach(`event-demo-request-${profile.width}`, { body: await page.screenshot(), contentType: 'image/png' });

    await expect(demo).toHaveAttribute('data-active-stage', 'event-preview', { timeout: 6_000 });
    const card = demo.getByTestId('landing-actionable-event-preview');
    await expect(card).toContainText('Open Source AI Night');
    await expect(card.getByTestId('event-preview-rsvps')).toHaveCount(0);
    await expect(card).not.toContainText(LEFTOVER_COPY);
    await expect(demo).toHaveAttribute('data-interaction-state', 'preview-clicked', { timeout: 4_000 });
    await testInfo.attach(`event-demo-card-${profile.width}`, { body: await page.screenshot(), contentType: 'image/png' });

    await expect(demo).toHaveAttribute('data-active-stage', 'provider-cta', { timeout: 6_000 });
    const cta = demo.getByTestId('landing-actionable-provider-button');
    await expect(cta).toHaveText(profile.cta);
    await expect(demo).toHaveAttribute('data-interaction-state', 'cta-clicked', { timeout: 4_000 });
    await testInfo.attach(`event-demo-cta-${profile.width}`, { body: await page.screenshot(), contentType: 'image/png' });
    await expect(demo).not.toContainText(LEFTOVER_COPY);
  });
}

test.describe('visitor in Berlin', () => {
  test.use({ timezoneId: 'Europe/Berlin' });
  // contract-test: direct surface=gui.web assertions=authored-results.demonstrations.proven-capability
  test('event demo always shows an upcoming date at 7 PM local time', async ({ page }) => {
    // Past events are filtered out of real searches, so the demo date must be ahead.
    await page.clock.setFixedTime(new Date('2026-11-13T10:00:00+01:00'));
    await page.goto('/dev/preview/landing/LandingActionableEventDemo?chrome=0&width=1280', { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page, 30_000);
    const demo = page.getByTestId('landing-actionable-event-demo');
    await expect(demo).toHaveAttribute('data-active-stage', 'event-preview', { timeout: 8_000 });
    // Friday 13 Nov 2026 -> the next Thursday is 19 Nov 2026.
    await expect(demo.getByTestId('landing-actionable-event-preview')).toContainText('19');
    await expect(demo.getByTestId('landing-actionable-event-preview')).not.toContainText('2024');
    await expect(demo.getByTestId('landing-actionable-event-preview')).toContainText('7:00');
    await expect(demo.getByTestId('landing-actionable-event-preview')).not.toContainText('UTC');
  });
});
