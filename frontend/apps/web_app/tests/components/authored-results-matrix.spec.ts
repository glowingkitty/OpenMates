import { readFile } from 'node:fs/promises';
import { expect, test } from '../helpers/cookie-audit';
import type { Locator } from '@playwright/test';
import {
  authoredChildren, authoredDocument, authoredDefinitions, authoredChild,
  openAuthoredComponent, isolateAuthoredImages, assertReadableAuthoredBounds, authoredCapture,
} from '../helpers/authored-result-fixtures';

// playwright-account: not_required reason=isolated_component_preview
// Static saved-content fixtures establish browser presentation and interaction;
// encrypted persistence, authorization and sync are separate integration checks.
test.setTimeout(180_000);

// Independent presentation expectations: one useful supplied fact per kind,
// beyond a title/badge. These intentionally do not call frontend formatters.
const usefulFacts: Record<string, string> = {
  'events.event': 'Community organizers', 'home.listing': '62',
  'health.appointment': 'Dermatology', 'travel.connection': 'Brussels',
  'travel.stay': 'Wi-Fi', 'maps.place': 'cafe', 'fitness.location': 'Yoga',
  'fitness.class': 'Example studio', 'shopping.product': '1.5 L',
  'jobs.job_result': 'Example', 'nutrition.recipe': 'Red lentils',
  'code.repo': 'MIT', 'web.website': 'Reference supplied by the user.',
  'news.website': 'Dated announcement.', 'electronics.component': 'EX123',
  'business.company_financial_result': '2025', 'weather.weather_day': 'Brussels',
  'hosting.hosting_domain': 'example.org',
  'social_media.social_post': 'Draft proposal: join our community workshop.',
  'design.icon_result': 'Apache-2.0', 'images.image_result': 'Photographer supplied by user',
  'videos.video': 'Example', 'models3d.model_result': 'CC BY 4.0',
  'tv.movie': 'A supplied film synopsis.', 'tv.series': 'A supplied series synopsis.',
};

async function assertProvenanceHasOwnSpace(card: Locator) {
  const provenance = card.getByTestId('authored-result-provenance');
  await expect(provenance).toBeVisible();
  await expect.poll(() => card.evaluate(element => {
    const badge = element.querySelector<HTMLElement>('[data-testid="authored-result-provenance"]');
    const body = element.querySelector<HTMLElement>(':scope > .result-preview-content, :scope > .content-result-layout, :scope > .desktop-layout, :scope > .mobile-layout');
    if (!badge || !body) return false;
    const outer = element.getBoundingClientRect();
    const origin = badge.getBoundingClientRect();
    const content = body.getBoundingClientRect();
    return origin.height > 0 && content.top >= outer.top - 1
      && content.bottom <= origin.top + 1 && origin.bottom <= outer.bottom + 1
      && getComputedStyle(badge).pointerEvents === 'none';
  })).toBe(true);
}

for (const width of [390, 1100]) for (const theme of ['light', 'dark'] as const) {
  // contract-test: supporting surface=gui.web assertions=authored-results.eligibility.all-suitable-results,authored-results.content.typed-and-useful,authored-results.facts.provenance-and-drafts,authored-results.groups.same-response-and-reuse,authored-results.surfaces.shared-semantics,tv-titles.lifecycle.groups-and-actions
  test(`all 25 authored kinds keep provenance and open their own fullscreen at ${width}px ${theme}`, async ({ page }, testInfo) => {
    expect(authoredChildren).toHaveLength(25);
    expect(new Set(authoredDocument.items.map(item => item.kind))).toEqual(new Set(Object.keys(authoredDefinitions)));
    await isolateAuthoredImages(page);
    await page.route('**/v1/apps/design/icons/iconify/**', route => route.fulfill({
      contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><path d="M3 4h18v17H3z"/></svg>',
    }));
    await openAuthoredComponent(page, 'AuthoredResultsPreviewFixture', { width, theme, variant: 'matrix25',
      props: { isMobile: width === 390 } });
    const carrier = page.getByTestId('authored-results-preview');
    await expect(carrier).toBeVisible();
    await expect(carrier.getByTestId('embed-preview')).toHaveCount(25);
    await expect(page.getByTestId('authored-fixture-error')).toHaveCount(0);
    const failures: Error[] = [];
    for (const [index, item] of authoredDocument.items.entries()) {
      try {
        await test.step(`${item.kind}: actual stored child preview to fullscreen`, async () => {
          const child = authoredChildren[index];
          const card = carrier.locator(`[data-testid="embed-preview"][data-embed-id="${child.embed_id}"]`);
          await card.scrollIntoViewIfNeeded();
          await expect(card).toBeVisible();
          if (item.kind === 'images.image_result') {
            await expect(card.getByRole('img', { name: item.title, exact: true })).toBeVisible();
          } else if (item.kind === 'travel.connection') {
            // The existing itinerary preview presents route facts; the stored
            // authored title remains asserted in its fullscreen header below.
            await expect(card).toContainText(usefulFacts[item.kind]);
          } else await expect(card).toContainText(item.title);
          await expect(card.getByTestId('authored-result-context')).toHaveAttribute('data-origin', item.origin);
          await expect(card.getByTestId('authored-result-origin')).toHaveText(item.origin === 'draft' ? 'Draft' : 'User-provided');
          await assertProvenanceHasOwnSpace(card);
          await expect(card).not.toContainText(/openmates_embeds|"schema_version"|"content_commitment"|app_skill_use/);
          await assertReadableAuthoredBounds(page, card);
          await expect(card).toHaveAttribute('role', 'button');
          await expect(card.getByTestId('preview-tools')).toHaveCount(0);
          await expect(card.getByTestId('result-preview-expand')).toHaveCount(0);
          await expect(card.getByTestId('result-preview-more')).toHaveCount(0);
          if (width === 390) await card.click();
          else {
            await card.focus();
            await expect(card).toBeFocused();
            await card.press('Enter');
          }
          const fullscreen = page.getByTestId('authored-fixture-fullscreen');
          await expect(fullscreen).toHaveAttribute('data-embed-id', child.embed_id);
          await expect(fullscreen.getByTestId('embed-header-title')).toHaveText(item.title);
          if (item.kind === 'travel.stay') {
            // Amenities use the shared icon fact control. Its readable explanation
            // lives in a body-level tooltip opened by the user's interaction.
            const wifi = fullscreen.getByRole('button', { name: 'Wi-Fi', exact: true });
            await expect(wifi).toBeVisible();
            await expect(wifi).toHaveAttribute('data-state', 'yes');
            await wifi.click();
            await expect(wifi).toHaveAttribute('aria-expanded', 'true');
            const explanation = page.getByRole('tooltip').filter({ hasText: 'Wi-Fi' });
            await expect(explanation).toBeVisible();
            await expect(explanation).toContainText(usefulFacts[item.kind]);
            await expect(explanation).toHaveAttribute('id', (await wifi.getAttribute('aria-describedby'))!);
            await wifi.press('Escape');
            await expect(explanation).toHaveCount(0);
          } else await expect(fullscreen).toContainText(usefulFacts[item.kind]);
          const provenance = fullscreen.getByTestId('authored-result-context');
          await expect(provenance).toHaveAttribute('data-origin', item.origin);
          if (item.origin === 'draft') {
            await expect(provenance.getByTestId('authored-result-origin')).toHaveText('Draft');
            await expect(provenance.getByRole('link')).toHaveCount(0);
            await expect(fullscreen).not.toContainText(/Published successfully|Posting complete|Generation complete/);
          } else {
            await expect(provenance.getByRole('link', { name: 'Supplied test reference' })).toHaveAttribute('href', 'https://example.org/reference');
          }
          if (item.kind === 'shopping.product') {
            await expect(fullscreen).toContainText('1.5 L');
            await expect(fullscreen).not.toContainText(/0 reviews|0 ratings|In stock|Free delivery/);
          }
          if (item.kind === 'health.appointment') {
            await expect(fullscreen).toContainText('Dermatology');
            await expect(fullscreen).toContainText('Dr Example');
            await expect(fullscreen).not.toContainText(/Insurance accepted|Available now|Confirmed appointment/);
          }
          if (item.kind === 'nutrition.recipe') {
            const recipe = fullscreen.getByTestId('nutrition-recipe-details');
            await expect(recipe.getByRole('listitem').filter({ hasText: 'Red lentils' })).toContainText(/150\s+g/);
            await expect(recipe.locator('ol > li')).toHaveText(['Rinse lentils.', 'Simmer until tender.']);
          }
          if (item.kind === 'jobs.job_result') {
            const salary = fullscreen.getByTestId('jobs-salary');
            await expect(salary).toContainText(/60,000/);
            await expect(salary).toContainText(/80,000/);
            await expect(salary).toContainText('€');
            await expect(salary).toContainText('annual');
          }
          if (item.kind === 'hosting.hosting_domain') {
            await expect(fullscreen.getByRole('button', { name: 'In use', exact: true })).toBeVisible();
            const registration = fullscreen.getByTestId('hosting-domain-registration');
            await expect(registration).toContainText(/€12[.,]00/);
            await expect(registration).toContainText('1 year');
            await expect(registration).not.toContainText(/per year|\/ year|First year offer/);
          }
          if (item.kind === 'home.listing') {
            await fullscreen.getByTestId('home-price-info').click();
            await expect(page.getByTestId('home-price-summary')).toBeVisible();
            await expect(page.getByTestId('home-rent-component')).toHaveCount(2);
            await expect(page.getByTestId('home-price-summary')).toContainText('1,200 EUR / month');
            await expect(page.getByTestId('home-price-summary')).toContainText('200 EUR / month');
            await fullscreen.getByTestId('home-price-info').press('Escape');
            const balcony = fullscreen.getByTestId('home-amenity-balcony');
            await expect(balcony).toHaveAttribute('data-state', 'yes');
            await expect(balcony).toHaveAccessibleName(/Balcony/);
          }
          if (item.kind === 'videos.video') {
            const source = fullscreen.getByTestId('video-source');
            await expect(source).toHaveAttribute('href', 'https://example.org/video');
            await expect(source).toHaveAccessibleName('View source', { exact: true });
            await expect(source).not.toContainText('YouTube');
          }
          await authoredCapture(page, testInfo, `${item.kind.replaceAll('.', '-')}-fullscreen-${width}-${theme}`);
          await fullscreen.getByTestId('embed-minimize').click();
          await expect(fullscreen).toHaveCount(0);
        });
      } catch (error) {
        failures.push(new Error(`${item.kind}: presentation or interaction failed`, { cause: error }));
        const evidenceName = `${item.kind.replaceAll('.', '-')}-failure-${width}-${theme}`;
        await testInfo.attach(`${evidenceName}-error`, {
          body: String(error instanceof Error ? error.stack || error.message : error).slice(0, 8000),
          contentType: 'text/plain',
        });
        try {
          // One viewport-sized image per failed kind, within the same recording.
          await testInfo.attach(evidenceName, { body: await page.screenshot({
            type: 'jpeg', quality: 70, animations: 'disabled',
          }), contentType: 'image/jpeg' });
        } catch (captureError) {
          failures.push(new Error(`${item.kind}: failure screenshot could not be captured`, { cause: captureError }));
        }
        if (index < authoredDocument.items.length - 1) {
          try {
            // A failed assertion can leave a fullscreen or a portal open. Reset
            // the real bare fixture before inspecting the next independent kind.
            await openAuthoredComponent(page, 'AuthoredResultsPreviewFixture', { width, theme, variant: 'matrix25',
              props: { isMobile: width === 390 } });
            await expect(carrier).toBeVisible();
            await expect(carrier.getByTestId('embed-preview')).toHaveCount(25);
            await expect(page.getByTestId('authored-fixture-error')).toHaveCount(0);
          } catch (resetError) {
            throw new AggregateError([...failures, resetError],
              `Authored matrix could not reset after ${item.kind}; subsequent kinds were not checked`);
          }
        }
      }
    }
    try {
      await expect(carrier.getByTestId('embed-preview')).toHaveCount(25);
      await expect(page.getByTestId('authored-fixture-error')).toHaveCount(0);
    } catch (error) {
      failures.push(new Error('Authored matrix final carrier invariants failed', { cause: error }));
    }
    if (failures.length) throw new AggregateError(failures,
      `Authored matrix failed at ${width}px ${theme}: ${failures.map(error => error.message).join('; ')}`);
  });

  // contract-test: supporting surface=gui.web assertions=authored-results.lifecycle.encrypted-and-stable,authored-results.groups.same-response-and-reuse,authored-results.actions.truthful-and-explicit
  test(`single authored event uses its own child identity and exports date-only and unknown-end calendars at ${width}px ${theme}`, async ({ page }, testInfo) => {
    for (const [variant, expectedStart, expectedEnd] of [
      ['dateOnly', 'DTSTART;VALUE=DATE:20270130', 'DTEND;VALUE=DATE:20270131'],
      ['timedNoEnd', 'DTSTART:20270130T080000Z', undefined],
    ] as const) {
      await openAuthoredComponent(page, 'AuthoredResultsPreviewFixture', { width, theme, variant });
      const carrier = page.getByTestId('authored-results-preview');
      await expect(carrier.getByTestId('embed-preview')).toHaveCount(1);
      const eventId = authoredChild('events.event').embed_id;
      const card = carrier.locator(`[data-testid="embed-preview"][data-embed-id="${eventId}"]`);
      await assertProvenanceHasOwnSpace(card);
      await expect(card).toHaveAttribute('role', 'group');
      await expect(card.getByTestId('result-preview-more')).toBeVisible();
      const expand = card.getByTestId('result-preview-expand');
      await expect(expand).toHaveAttribute('type', 'button');
      await expand.focus();
      await expand.press('Enter');
      const fullscreen = page.getByTestId('authored-fixture-fullscreen');
      await expect(fullscreen).toHaveAttribute('data-embed-id', eventId);
      const sourceCta = fullscreen.getByTestId('external-provider-cta');
      await expect(sourceCta).toHaveClass(/embed-header-cta/);
      await expect(sourceCta).toHaveAttribute('href', 'https://example.org/conference');
      // Production mounts fullscreen outside ReadOnlyMessage; its markdown-link
      // gradient must never replace the shared CTA's filled button and text.
      expect(await sourceCta.evaluate(element => !!element.closest('.read-only-message'))).toBe(false);
      await expect(sourceCta).toHaveCSS('color', 'rgb(255, 255, 255)');
      await expect(sourceCta).not.toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
      await expect(sourceCta).not.toHaveCSS('background-clip', 'text');
      await expect(fullscreen.getByTestId('embed-calendar-button')).toBeVisible();
      const [download] = await Promise.all([
        page.waitForEvent('download'), fullscreen.getByTestId('embed-calendar-button').click(),
      ]);
      const file = await download.path();
      expect(file).not.toBeNull();
      const calendar = await readFile(file!, 'utf8');
      expect(download.suggestedFilename()).toMatch(/\.ics$/);
      expect(calendar).toContain(expectedStart);
      if (expectedEnd) expect(calendar).toContain(expectedEnd);
      else expect(calendar).not.toMatch(/^DTEND[;:]/m);
      expect(calendar).toContain('BEGIN:VEVENT');
      expect(calendar).not.toContain('Invalid Date');
      await authoredCapture(page, testInfo, `event-${variant}-${width}-${theme}`);
    }
  });

  // contract-test: supporting surface=gui.web assertions=authored-results.media.safe-and-attributed,authored-results.facts.provenance-and-drafts
  test(`failed source image preserves the readable authored event and provenance at ${width}px ${theme}`, async ({ page }, testInfo) => {
    await isolateAuthoredImages(page, true);
    const failedImage = page.waitForResponse(response => response.url().includes('/api/v1/image?') && response.status() === 404);
    await openAuthoredComponent(page, 'AuthoredResultsPreviewFixture', { width, theme, variant: 'singleevent' });
    await failedImage;
    const card = page.getByTestId('authored-results-preview').getByTestId('embed-preview');
    await expect(card).toContainText('Supplied: events.event');
    await expect(card.getByTestId('authored-result-context')).toHaveAttribute('data-origin', 'user_provided');
    await assertReadableAuthoredBounds(page, card);
    await card.getByTestId('result-preview-expand').focus();
    await card.getByTestId('result-preview-expand').press('Enter');
    const fullscreen = page.getByTestId('authored-fixture-fullscreen');
    await expect(fullscreen).toHaveAttribute('data-embed-id', authoredChild('events.event').embed_id);
    await expect(fullscreen.getByTestId('embed-header-title')).toHaveText('Supplied: events.event');
    await expect(fullscreen.getByTestId('authored-result-context').getByRole('link', { name: 'Supplied test reference' })).toHaveAttribute('href', 'https://example.org/reference');
    await authoredCapture(page, testInfo, `event-failed-source-image-${width}-${theme}`);
  });

  // contract-test: supporting surface=gui.web assertions=authored-results.lifecycle.encrypted-and-stable,authored-results.actions.truthful-and-explicit
  test(`incomplete, failed and cancelled authored carriers expose no finished cards or raw payload at ${width}px ${theme}`, async ({ page }) => {
    for (const variant of ['processing', 'error', 'cancelled']) {
      await openAuthoredComponent(page, 'AuthoredResultsPreviewFixture', { width, theme, variant });
      const carrier = page.getByTestId('authored-results-preview');
      await expect(carrier).toBeVisible();
      await expect(carrier).toHaveAttribute('data-status', variant);
      await expect(carrier.locator('[data-testid="embed-preview"][data-status="finished"]')).toHaveCount(0);
      await expect(carrier.getByRole('status')).toBeVisible();
      await expect(carrier.getByTestId('embed-calendar-button')).toHaveCount(0);
      await expect(carrier.getByTestId('external-provider-cta')).toHaveCount(0);
      await expect(carrier).not.toContainText(/schema_version|source_json|"items"|app_skill_use/);
      await assertReadableAuthoredBounds(page, carrier);
    }
  });
}
