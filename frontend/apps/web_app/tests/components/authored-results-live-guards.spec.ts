import { expect, test } from '../helpers/cookie-audit';
import {
  authoredChild, openAuthoredComponent, isolateAuthoredImages, authoredCapture,
} from '../helpers/authored-result-fixtures';

// playwright-account: not_required reason=isolated_component_preview
// These exercise real component/store/imperative renderer paths with static
// saved-content inputs. They do not claim backend or encrypted persistence proof.

// contract-test: supporting surface=gui.web assertions=authored-results.lifecycle.encrypted-and-stable,tv-titles.lifecycle.groups-and-actions,tv-titles.series.supplied-seasons
test('same mounted TV fullscreen follows next and previous child identity, content and source', async ({ page }, testInfo) => {
  await isolateAuthoredImages(page);
  await openAuthoredComponent(page, 'AuthoredResultsPreviewFixture', { variant: 'tvNavigation' });
  const movie = authoredChild('tv.movie');
  const series = authoredChild('tv.series');
  const movieCard = page.locator(`[data-testid="authored-results-preview"] [data-testid="embed-preview"][data-embed-id="${movie.embed_id}"]`);
  await movieCard.focus();
  await movieCard.press('Enter');
  const fullscreen = page.getByTestId('authored-fixture-fullscreen');
  await expect(fullscreen).toHaveAttribute('data-embed-id', movie.embed_id);
  await expect(fullscreen.getByTestId('embed-header-title')).toHaveText('Supplied: tv.movie');
  await expect(fullscreen.getByTestId('tv-open-source')).toHaveAttribute('href', 'https://example.org/movie');
  await expect(fullscreen.getByTestId('tv-score-source').getByRole('link')).toHaveAttribute('href', 'https://example.org/movie-score');
  const mounted = await fullscreen.getByTestId('tv-title-fullscreen').elementHandle();
  expect(mounted).not.toBeNull();
  await fullscreen.getByRole('button', { name: 'Next embed', exact: true }).click();
  await expect(fullscreen).toHaveAttribute('data-embed-id', series.embed_id);
  await expect(fullscreen.getByTestId('embed-header-title')).toHaveText('Supplied: tv.series');
  await expect(fullscreen.getByTestId('tv-synopsis')).toHaveText('A supplied series synopsis.');
  await expect(fullscreen.getByTestId('tv-open-source')).toHaveAttribute('href', 'https://example.org/series');
  await expect(fullscreen.getByTestId('tv-score-source')).toHaveCount(0);
  await expect(fullscreen.getByTestId('tv-season')).toHaveCount(2);
  await expect(fullscreen.locator('[data-testid="tv-season"][data-season-number="0"]')).toContainText('Specials');
  expect(await mounted!.evaluate(node => node === document.querySelector('[data-testid="tv-title-fullscreen"]'))).toBe(true);
  await authoredCapture(page, testInfo, 'same-mounted-series-after-movie');
  await fullscreen.getByRole('button', { name: 'Previous embed', exact: true }).click();
  await expect(fullscreen).toHaveAttribute('data-embed-id', movie.embed_id);
  await expect(fullscreen.getByTestId('embed-header-title')).toHaveText('Supplied: tv.movie');
  await expect(fullscreen.getByTestId('tv-open-source')).toHaveAttribute('href', 'https://example.org/movie');
  await expect(fullscreen.getByTestId('tv-score')).toContainText('8.2 / 10');
  await expect(fullscreen.getByTestId('tv-seasons')).toHaveCount(0);
  expect(await mounted!.evaluate(node => node.isConnected)).toBe(true);
  await expect(page.getByTestId('authored-fixture-error')).toHaveCount(0);
});

// contract-test: supporting surface=gui.web assertions=authored-results.lifecycle.encrypted-and-stable,authored-results.content.typed-and-useful
test('partial carrier keeps its valid child and readable warning inline and its fullscreen request opens the first member', async ({ page }, testInfo) => {
  const eventId = authoredChild('events.event').embed_id;
  await openAuthoredComponent(page, 'AuthoredResultsPreviewFixture', { width: 390, theme: 'dark', variant: 'partial' });
  const inline = page.getByTestId('authored-results-preview');
  await expect(inline.getByTestId('authored-results-partial')).toBeVisible();
  await expect(inline.getByTestId('embed-preview')).toHaveCount(1);
  await expect(inline.locator(`[data-testid="embed-preview"][data-embed-id="${eventId}"]`)).toContainText('Supplied: events.event');
  await expect(inline).not.toContainText(/source_json|schema_version|"items"/);
  await authoredCapture(page, testInfo, 'partial-valid-child-inline');
  // An old carrier link or history entry has no group layer: it opens the first member's fullscreen.
  await openAuthoredComponent(page, 'AuthoredResultsPreviewFixture', { width: 390, theme: 'dark', variant: 'partialFullscreen' });
  const fullscreen = page.getByTestId('authored-fixture-fullscreen');
  await expect(fullscreen).toHaveAttribute('data-embed-id', eventId);
  await expect(fullscreen.getByTestId('embed-header-title')).toHaveText('Supplied: events.event');
  await expect(fullscreen).not.toContainText(/source_json|schema_version|"items"/);
  await expect(page.getByTestId('authored-fixture-error')).toHaveCount(0);
  await authoredCapture(page, testInfo, 'partial-carrier-opens-first-member');
});

// contract-test: supporting surface=gui.web assertions=authored-results.lifecycle.encrypted-and-stable,authored-results.groups.same-response-and-reuse
test('processing carrier hydrates through the real store and embedUpdated path without replacing its props', async ({ page }, testInfo) => {
  await openAuthoredComponent(page, 'AuthoredResultsPreviewFixture', { variant: 'streaming' });
  const carrier = page.getByTestId('authored-results-preview');
  await expect(carrier).toHaveAttribute('data-status', 'processing');
  await expect(carrier.locator('[data-testid="embed-preview"][data-status="finished"]')).toHaveCount(0);
  const mounted = await carrier.elementHandle();
  await page.evaluate(() => document.dispatchEvent(new Event('preview:finish-authored-results')));
  await expect(carrier).toHaveAttribute('data-status', 'finished');
  const event = carrier.locator(`[data-testid="embed-preview"][data-embed-id="${authoredChild('events.event').embed_id}"]`);
  await expect(event).toHaveAttribute('data-status', 'finished');
  await expect(event).toContainText('Supplied: events.event');
  await expect(event.getByTestId('authored-result-origin')).toHaveCount(0);
  expect(await mounted!.evaluate(node => node === document.querySelector('[data-testid="authored-results-preview"]'))).toBe(true);
  await event.getByTestId('result-preview-expand').focus();
  await event.getByTestId('result-preview-expand').press('Enter');
  await expect(page.getByTestId('authored-fixture-fullscreen')).toHaveAttribute('data-embed-id', authoredChild('events.event').embed_id);
  await expect(page.getByTestId('authored-fixture-error')).toHaveCount(0);
  await authoredCapture(page, testInfo, 'hydrated-carrier-real-child-fullscreen');
});

// contract-test: supporting surface=gui.web assertions=authored-results.lifecycle.encrypted-and-stable,authored-results.surfaces.shared-semantics
test('real GroupRenderer supplies source-chat context without an ambient DOM source marker', async ({ page }, testInfo) => {
  await openAuthoredComponent(page, 'AuthoredResultsPreviewFixture', { variant: 'groupSource' });
  const host = page.getByTestId('authored-group-renderer-host');
  await expect(host.getByTestId('authored-results-preview')).toBeVisible();
  expect(await host.evaluate(node => node.closest('[data-embed-chat-id]') === null)).toBe(true);
  const event = host.locator(`[data-testid="embed-preview"][data-embed-id="${authoredChild('events.event').embed_id}"]`);
  await expect(event).toContainText('Supplied: events.event');
  await event.getByTestId('result-preview-expand').focus();
  await event.getByTestId('result-preview-expand').press('Enter');
  const fullscreen = page.getByTestId('authored-fixture-fullscreen');
  await expect(fullscreen).toHaveAttribute('data-embed-id', authoredChild('events.event').embed_id);
  // Observes the actual production embedfullscreen event, not fixture props.
  await expect(fullscreen).toHaveAttribute('data-source-chat-id', '777d0000-0000-4000-8000-000000002000');
  await expect(fullscreen.getByTestId('embed-header-title')).toHaveText('Supplied: events.event');
  await expect(page.getByTestId('authored-fixture-error')).toHaveCount(0);
  await authoredCapture(page, testInfo, 'group-renderer-explicit-source-context');
});

for (const [width, theme] of [[390, 'dark'], [1100, 'light']] as const) {
  for (const [kind, legacyUrl] of [
    ['events.event', 'https://example.org/conference.jpg'],
    ['tv.movie', 'https://example.org/movie-poster.jpg'],
    ['home.listing', 'https://example.org/legacy-home.jpg'],
    ['health.appointment', 'https://example.org/legacy-health.jpg'],
  ] as const) {
    // contract-test: supporting surface=gui.web assertions=authored-results.media.safe-and-attributed,authored-results.surfaces.shared-semantics
    test(`explicit authored image overrides legacy ${kind} media in preview and fullscreen at ${width}px ${theme}`, async ({ page }, testInfo) => {
      await isolateAuthoredImages(page);
      await openAuthoredComponent(page, 'AuthoredResultsPreviewFixture', { width, theme, variant: 'projectedImages' });
      const child = authoredChild(kind);
      const projectedUrl = `https://example.org/authored-${kind}.jpg`;
      const card = page.locator(`[data-testid="authored-results-preview"] [data-testid="embed-preview"][data-embed-id="${child.embed_id}"]`);
      const previewImage = kind === 'health.appointment' ? card.getByTestId('health-appointment-image')
        : card.getByRole('img', { name: String(child.content.title), exact: true });
      await expect(previewImage).toBeVisible();
      await expect.poll(async () => {
        const src = await previewImage.getAttribute('src');
        return src ? decodeURIComponent(src) : '';
      }).toContain(projectedUrl);
      await expect(previewImage).not.toHaveAttribute('src', new RegExp(encodeURIComponent(legacyUrl)));
      await expect.poll(() => previewImage.evaluate(node => (node as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
      if (width === 390) await card.click();
      else { await card.focus(); await card.press('Enter'); }
      const fullscreen = page.getByTestId('authored-fixture-fullscreen');
      await expect(fullscreen).toHaveAttribute('data-embed-id', child.embed_id);
      const image = kind === 'tv.movie' ? fullscreen.getByTestId('tv-fullscreen-poster')
        : kind === 'home.listing' ? fullscreen.getByTestId('home-gallery-image')
        : kind === 'health.appointment' ? fullscreen.getByTestId('health-appointment-fullscreen-image')
        : fullscreen.getByRole('img', { name: String(child.content.title), exact: true });
      await expect(image).toBeVisible();
      await expect.poll(async () => {
        const src = await image.getAttribute('src');
        return src ? decodeURIComponent(src) : '';
      }).toContain(projectedUrl);
      await expect.poll(() => image.evaluate(node => (node as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
      await expect(fullscreen.getByTestId('authored-result-origin')).toHaveText('User-provided');
      await authoredCapture(page, testInfo, `projected-${kind}-${width}-${theme}`);
      await fullscreen.getByTestId('embed-minimize').click();
      await expect(fullscreen).toHaveCount(0);
      const fixture = page.getByTestId('authored-results-fixture');
      await expect.poll(async () => {
        const serialized = await fixture.getAttribute('data-stored-images');
        if (!serialized) return null;
        const stored = JSON.parse(serialized) as Array<{ embed_id: string; image_url: string | null; poster_url: string | null; image_urls: string[] | null }>;
        const record = stored.find(value => value.embed_id === child.embed_id);
        return { url: kind === 'tv.movie' ? record?.poster_url : record?.image_url,
          ...(kind === 'home.listing' ? { gallery: record?.image_urls } : {}) };
      }).toEqual({ url: legacyUrl, ...(kind === 'home.listing' ? { gallery: [legacyUrl] } : {}) });
      await expect(page.getByTestId('authored-fixture-error')).toHaveCount(0);
    });
  }

  // contract-test: supporting surface=gui.web assertions=authored-results.content.typed-and-useful,authored-results.facts.provenance-and-drafts
  test(`numeric financial quarter and supplied zero weather facts remain readable at ${width}px ${theme}`, async ({ page }, testInfo) => {
    await openAuthoredComponent(page, 'AuthoredResultsPreviewFixture', { width, theme, variant: 'numericObservations' });
    const financialId = authoredChild('business.company_financial_result').embed_id;
    const financial = page.locator(`[data-testid="authored-results-preview"] [data-testid="embed-preview"][data-embed-id="${financialId}"]`);
    await financial.click();
    const fullscreen = page.getByTestId('authored-fixture-fullscreen');
    await expect(fullscreen).toHaveAttribute('data-embed-id', financialId);
    const financialDetails = fullscreen.getByTestId('business-financial-result-fullscreen');
    await expect(financialDetails).toContainText('Q2 2025');
    const cashFlow = financialDetails.locator('.metric-row').filter({ hasText: 'Cash flow' });
    await expect(cashFlow).toHaveCount(1);
    await expect(cashFlow.locator('strong')).toHaveText(/€0(?:[.,]00)?/);
    await expect(financialDetails).not.toContainText(/SEC filing|Investment advice/);
    await authoredCapture(page, testInfo, `financial-zero-quarter-${width}-${theme}`);
    await fullscreen.getByTestId('embed-minimize').click();
    const weatherId = authoredChild('weather.weather_day').embed_id;
    const weather = page.locator(`[data-testid="authored-results-preview"] [data-testid="embed-preview"][data-embed-id="${weatherId}"]`);
    await expect(weather).toContainText('0° / 0°');
    await weather.click();
    await expect(fullscreen).toHaveAttribute('data-embed-id', weatherId);
    const summary = fullscreen.getByTestId('weather-day-fullscreen-summary');
    await expect(summary).toContainText('0° / 0°');
    await expect(summary).toContainText('0%');
    const hourly = fullscreen.getByTestId('weather-hourly-row');
    await expect(hourly).toHaveCount(1);
    await expect(hourly).toContainText('09:00');
    await expect(hourly).toContainText('0°');
    await expect(hourly).toContainText('0%');
    await expect(hourly).toContainText('0 mm');
    await expect(hourly).toContainText('0 km/h');
    await expect(hourly).not.toContainText('—');
    await expect(fullscreen.getByTestId('weather-day-fullscreen')).toContainText('0 mm');
    await authoredCapture(page, testInfo, `weather-zero-observations-${width}-${theme}`);
  });
}
