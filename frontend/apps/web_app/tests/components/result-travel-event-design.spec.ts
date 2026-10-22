import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentMotion, waitForComponentPreview } from '../helpers/component-preview';
// playwright-account: not_required reason=isolated_component_preview

const preview = (path: string, width: number, variant = '') =>
  `/dev/preview/embeds/${path}?chrome=0&width=${width}${variant ? `&variant=${variant}` : ''}${variant === 'chat' ? '&context=chat' : ''}`;

for (const width of [390, 1280]) {
  // contract-test: supporting surface=gui.web assertions=travel-search.surface-parity
  test(`connection preserves itinerary and route map in shared detail at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(preview('travel/TravelConnectionEmbedFullscreen', width));
    await waitForComponentPreview(page);
    await waitForComponentMotion(page.getByTestId('embed-fullscreen-overlay'));
    await expect(page.getByTestId('result-facts')).toContainText('189');
    await expect(page.getByTestId('result-map')).toBeVisible();
    await expect.poll(() => page.getByTestId('header-airline-logos').locator('img').evaluateAll(images => images.every(image => (image as HTMLImageElement).complete && (image as HTMLImageElement).naturalWidth > 0))).toBe(true);
    await expect(page.getByTestId('flight-details-card')).toContainText('Airbus A320neo');
    await expect(page.getByTestId('flight-details-card')).toContainText('Munich');
    await expect(page.getByTestId('apps-request-textarea')).toBeVisible();
    await testInfo.attach(`connection-${width}`, { body: await page.screenshot(), contentType: 'image/png' });
  });

  // contract-test: supporting surface=gui.web assertions=travel-search.surface-parity,events-search.surface-parity
  test(`stay and event media follow compact facts at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    for (const path of ['travel/TravelStayEmbedFullscreen', 'events/EventEmbedFullscreen']) {
      await page.goto(preview(path, width));
      await waitForComponentPreview(page);
      await waitForComponentMotion(page.getByTestId('embed-fullscreen-overlay'));
      await expect(page.getByTestId('result-facts')).toBeVisible();
      const media = page.locator('.result-media-panel');
      const map = page.getByTestId('result-map');
      await expect(media.locator('img')).toBeVisible();
      await expect(map).toBeVisible();
      const imageBox = (await media.boundingBox())!;
      const mapBox = (await map.boundingBox())!;
      if (width > 600) expect(Math.abs(imageBox.y - mapBox.y)).toBeLessThan(3);
      else expect(mapBox.y).toBeGreaterThanOrEqual(imageBox.y + imageBox.height - 2);
      if (path.startsWith('travel')) {
        const gallery = page.getByTestId('stay-gallery');
        const galleryImage = gallery.locator('img');
        await expect(galleryImage).toHaveCSS('object-fit', 'contain');
        await expect.poll(() => galleryImage.evaluate(image => (image as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
        const galleryBox = (await gallery.boundingBox())!;
        const photoBox = (await galleryImage.boundingBox())!;
        expect(Math.abs(galleryBox.height - mapBox.height)).toBeLessThan(2);
        expect(Math.abs(photoBox.height - mapBox.height)).toBeLessThan(2);
        const letterbox = await gallery.evaluate(element => getComputedStyle(element).backgroundColor); expect(letterbox).not.toBe('rgba(0, 0, 0, 0)');
        expect(Math.max(...letterbox.match(/\d+/g)!.slice(0, 3).map(Number))).toBeLessThanOrEqual(64);
        for (const control of await page.getByTestId('stay-gallery').locator('button').all()) {
          const bounds = (await control.boundingBox())!;
          expect(bounds.width).toBeLessThanOrEqual(44);
          expect(bounds.height).toBeLessThanOrEqual(44);
          await expect(control).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
          const chevron = control.locator('.embed-chevron');
          await expect(chevron).toHaveCount(1);
          await expect(chevron).toHaveCSS('border-top-style', 'solid');
          await expect(chevron).toHaveCSS('border-right-style', 'solid');
          expect((await control.textContent())?.trim()).toBe('');
        }
        const nextPhoto = page.getByRole('button', { name: 'Next image', exact: true });
        const previousPhoto = page.getByRole('button', { name: 'Previous image', exact: true });
        await expect(previousPhoto.locator('.embed-chevron')).toHaveClass(/previous/);
        await nextPhoto.click();
        await expect(page.getByTestId('stay-gallery-counter')).toHaveText('2 / 3');
        await nextPhoto.press('Enter');
        await expect(page.getByTestId('stay-gallery-counter')).toHaveText('3 / 3');
        await previousPhoto.press('Space');
        await expect(page.getByTestId('stay-gallery-counter')).toHaveText('2 / 3');
      } else {
        const titleBounds = (await page.getByTestId('embed-header-title').boundingBox())!;
        for (const arrow of await page.locator('.nav-arrow').all()) {
          const arrowBounds = (await arrow.boundingBox())!;
          expect(arrowBounds.x + arrowBounds.width <= titleBounds.x || arrowBounds.x >= titleBounds.x + titleBounds.width).toBe(true);
        }
        const zoomControls = map.getByTestId('embed-map-zoom-controls');
        await expect(zoomControls).toBeVisible();
        const zoomMasks = await zoomControls.evaluate(controls => {
          return ['plus', 'minus'].map((name, index) => {
            const control = controls.querySelectorAll('a')[index];
            const probe = document.createElement('span');
            probe.style.maskImage = `var(--icon-url-${name})`;
            control.appendChild(probe);
            const result = { actual: getComputedStyle(control, '::after').maskImage, expected: getComputedStyle(probe).maskImage };
            probe.remove();
            return result;
          });
        });
        for (const mask of zoomMasks) {
          expect(mask.expected).not.toBe('none');
          expect(mask.actual).toBe(mask.expected);
        }
        await expect(page.getByTestId('event-facts').locator('button, [role="button"]')).toHaveCount(0);
        await expect(page.locator('.event-meta-row, .event-type-badge, .event-free-badge, .event-fee-badge, .event-rsvp, .event-source-badge')).toHaveCount(0);
        await expect(page.locator('.result-detail-content')).not.toContainText('Date & Time');
        await expect(page.getByTestId('event-time-range')).toHaveCount(1);
        await expect(page.getByTestId('event-time-range')).toHaveText(/7:00 PM\s*–\s*10:00 PM/);
        await expect(page.getByTestId('event-date-label')).toContainText('2026');
        const organizer = page.getByTestId('event-organizer-card');
        const venue = page.getByTestId('event-venue-card');
        await expect(organizer).toContainText('AI Berlin Community');
        await expect(venue).toContainText('Factory Berlin');
        const identityColor = await organizer.evaluate(element => {
          const probe = document.createElement('span');
          probe.style.color = 'var(--color-primary-start)';
          element.appendChild(probe);
          const color = getComputedStyle(probe).color;
          probe.remove();
          return color;
        });
        await expect(organizer.locator('strong')).toHaveCSS('color', identityColor);
        await expect(venue.locator('strong')).toHaveCSS('color', identityColor);
        const eventColor = await venue.evaluate(element => {
          const probe = document.createElement('span');
          probe.style.color = 'var(--color-app-events-start)';
          element.appendChild(probe);
          const color = getComputedStyle(probe).color;
          probe.remove();
          return color;
        });
        await expect(venue.locator('.event-icon')).toHaveCSS('color', eventColor);
        expect(Math.abs((await organizer.boundingBox())!.width - (await venue.boundingBox())!.width)).toBeLessThan(1);
        await expect(page.getByTestId('event-description').locator('strong')).toContainText('Schedule');
        await expect(page.getByTestId('event-description').locator('ul li')).toHaveCount(4);
        await expect(page.getByTestId('event-description').getByRole('link', { name: 'Read the event guide' })).toHaveAttribute('rel', 'noopener noreferrer');
      }
      await expect(page.getByTestId('apps-request-textarea')).toBeVisible();
      await testInfo.attach(`${path.split('/')[0]}-${width}`, { body: await page.screenshot(), contentType: 'image/png' });
    }
  });

  // contract-test: supporting surface=gui.web assertions=travel-search.surface-parity,events-search.surface-parity
  test(`travel and event chat cards preserve selection and explicit expansion at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    for (const path of ['travel/TravelConnectionEmbedPreview', 'travel/TravelStayEmbedPreview', 'events/EventEmbedPreview']) {
      const expansions: string[] = [];
      const listener = (message: { text(): string }) => { if (message.text() === '[Preview] travel/event result expanded') expansions.push(message.text()); };
      page.on('console', listener);
      await page.goto(preview(path, width, 'chat'));
      await waitForComponentPreview(page);
      const card = page.getByTestId('embed-preview');
      await expect(card).toHaveAttribute('role', 'group');
      await expect(card.locator('.result-corner')).toBeVisible();
      if (path.includes('Connection')) {
        await expect(page.getByTestId('connection-preview-details')).toBeVisible();
        await expect(page.getByTestId('connection-price')).toContainText('189');
        await expect(page.getByTestId('connection-route')).toContainText('Munich');
        await expect(page.getByTestId('connection-time')).toContainText('MUC');
        if (width > 600) await expect(card.locator('.connection-map')).toBeVisible();
        else await expect(card.locator('.connection-map')).toBeHidden();
      } else await expect(page.getByTestId('result-card-title')).toBeVisible();
      if (path.startsWith('events/')) {
        await expect(page.getByTestId('result-card-title')).toHaveCSS('-webkit-line-clamp', '2');
        await expect(page.getByTestId('result-card-content').locator('img')).toHaveCSS('object-fit', 'contain');
        await expect(page.getByTestId('embed-calendar-date').locator('strong')).toHaveText('15');
        await expect(page.getByTestId('embed-calendar-date').locator('span')).toHaveText('Sun');
        await expect(page.getByTestId('event-preview-attribution')).toHaveText('7:00 PM, by AI Berlin Community');
        await expect(page.getByTestId('event-preview-rsvps')).toContainText('142 RSVPs');
        await expect(page.getByTestId('result-card-content')).not.toContainText('Join us for an evening');
        await expect(page.getByTestId('result-card-content')).not.toContainText('In Person');
        await expect(page.getByTestId('result-card-content')).not.toContainText('Free');
        await expect(page.getByTestId('result-card-content').locator('.card-source')).toHaveCount(0);
      }
      const identity = path.includes('Connection') ? page.getByTestId('connection-route') : page.getByTestId('result-card-title');
      await identity.click();
      expect(expansions).toHaveLength(0);
      await page.getByTestId('result-preview-expand').click();
      await expect.poll(() => expansions.length).toBe(1);
      page.off('console', listener);
      await testInfo.attach(`${path.split('/').pop()}-${width}`, { body: await page.screenshot(), contentType: 'image/png' });
    }
  });
}

// contract-test: supporting surface=gui.web assertions=events-search.surface-parity
test('online event and coordinate-free map remain readable without invented locations', async ({ page }) => {
  await page.goto(preview('events/EventEmbedFullscreen', 390, 'online'));
  await waitForComponentPreview(page);
  await expect(page.getByTestId('result-map')).toHaveCount(0);
  await expect(page.getByTestId('result-embed-content')).toContainText('Online event');
  await page.goto(preview('events/EventEmbedFullscreen', 390, 'unknownFee'));
  await waitForComponentPreview(page);
  await expect(page.getByTestId('result-facts')).not.toContainText('Free');
  await expect(page.locator('.result-media-panel')).toHaveCount(0);
  await page.goto(preview('maps/MapLocationEmbedFullscreen', 390, 'noCoords'));
  await waitForComponentPreview(page);
  await expect(page.getByTestId('result-map')).toHaveCount(0);
  await expect(page.getByTestId('map-location-fullscreen')).toContainText('Schellingstraße');
});

// contract-test: supporting surface=gui.web assertions=travel-search.realtime.source-faithful,travel-search.optimization.additive-provenance,travel-search.surface-parity
test('connection previews retain both journey legs and rail realtime provenance', async ({ page }) => {
  await page.goto(preview('travel/TravelConnectionEmbedPreview', 900, 'roundTripItinerary'));
  await waitForComponentPreview(page);
  await expect(page.locator('.itinerary-leg')).toHaveCount(2);
  await expect(page.locator('.itinerary-leg').first()).toContainText('MUC');
  await expect(page.locator('.itinerary-leg').last()).toContainText('LHR');
  await page.goto(preview('travel/TravelConnectionEmbedPreview', 390, 'trainRealtime'));
  await waitForComponentPreview(page);
  await expect(page.getByTestId('connection-realtime-status')).toHaveText('+12 min arrival');
  await expect(page.getByTestId('connection-optimization-badge')).toHaveText('Optimized by OpenMates');
  await expect(page.getByTestId('airline-logos').locator('img')).toHaveAttribute('alt', 'Deutsche Bahn');
});

for (const width of [390, 1280]) {
  // contract-test: supporting surface=gui.web assertions=maps-search.discovery.bounded-provider-routing
  test(`both location detail adapters use the shared map layout at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    for (const path of ['MapsLocationEmbedFullscreen', 'MapLocationEmbedFullscreen']) {
      await page.goto(preview(`maps/${path}`, width));
      await waitForComponentPreview(page);
      await waitForComponentMotion(page.getByTestId('embed-fullscreen-overlay'));
      await expect(page.getByTestId('result-embed-content')).toHaveAttribute('data-app-id', 'maps');
      await expect(page.getByTestId('result-map')).toBeVisible();
      await expect(page.getByTestId('map-location-fullscreen')).toContainText(path === 'MapsLocationEmbedFullscreen' ? 'Berlin Hauptbahnhof' : 'Man vs. Machine');
      await expect(page.getByRole('button', { name: 'Open on Google Maps', exact: true })).toBeVisible();
      await expect(page.getByTestId('apps-request-textarea')).toBeVisible();
      await testInfo.attach(`${path}-${width}`, { body: await page.screenshot(), contentType: 'image/png' });
    }
  });
}

for (const width of [390, 1280]) {
  // contract-test: supporting surface=gui.web assertions=travel-search.surface-parity
  test(`persisted flight details retain track and timing in the shared layout at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    const providerRequests: string[] = [];
    page.on('request', request => { if (/\/travel\/(flight-details|get_flight)/.test(request.url())) providerRequests.push(request.url()); });
    await page.goto(preview('travel/TravelFlightDetailsEmbedFullscreen', width));
    await waitForComponentPreview(page);
    await waitForComponentMotion(page.getByTestId('embed-fullscreen-overlay'));
    await expect(page.getByTestId('embed-header-title')).toHaveText('OM123');
    await expect(page.getByTestId('result-facts')).toContainText('1h 30m');
    await expect(page.getByTestId('result-facts')).toContainText('940 km');
    await expect(page.getByTestId('result-facts')).toContainText('4 points');
    await expect(page.getByTestId('result-map').locator('.leaflet-overlay-pane path')).toHaveCount(1);
    await expect(page.getByTestId('flight-track-details')).toContainText('26R');
    await expect(page.getByTestId('flight-track-details')).toContainText('27L');
    await expect(page.getByTestId('flight-track-details')).toContainText('synthetic-preview');
    await expect(page.getByTestId('external-provider-cta')).toHaveText('Open on Flightradar24');
    await expect(page.getByTestId('apps-request-textarea')).toBeVisible();
    expect(providerRequests).toHaveLength(0);
    await testInfo.attach(`flight-track-${width}`, { body: await page.screenshot(), contentType: 'image/png' });
    await page.goto(preview('travel/TravelFlightDetailsEmbedFullscreen', width, 'diverted'));
    await waitForComponentPreview(page);
    await expect(page.getByTestId('flight-track-details')).toContainText('Flight diverted to LGW');
    await page.goto(preview('travel/TravelFlightDetailsEmbedFullscreen', width, 'noTrack'));
    await waitForComponentPreview(page);
    await expect(page.getByTestId('result-map')).toHaveCount(0);
    await expect(page.getByTestId('flight-track-unavailable')).toBeVisible();
  });

  // contract-test: supporting surface=gui.web assertions=travel-search.surface-parity,maps-search.gui.place-rendering,maps-search.compatibility.regular-search
  test(`flight and map previews share cards while retaining selection and approximate labels at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    for (const path of ['travel/TravelFlightDetailsEmbedPreview', 'maps/MapLocationEmbedPreview', 'maps/MapsLocationEmbedPreview']) {
      await page.goto(preview(path, width, 'chat'));
      await waitForComponentPreview(page);
      await expect(page.getByTestId('embed-preview')).toHaveAttribute('role', 'group');
      await expect(page.getByTestId('result-card-title')).toBeVisible();
      await expect(page.getByTestId('result-preview-expand')).toBeVisible();
      if (path.includes('/maps/') || path.startsWith('maps/')) await expect(page.getByTestId('result-card-media').locator('img')).toBeVisible();
      else {
        await expect(page.getByTestId('result-card-content')).toContainText('MUC → LHR');
        await expect(page.getByTestId('result-card-content')).toContainText('4 pts');
      }
      await testInfo.attach(`${path.split('/').pop()}-${width}`, { body: await page.screenshot(), contentType: 'image/png' });
    }
    await page.goto(preview('maps/MapLocationEmbedPreview', width, 'selected'));
    await waitForComponentPreview(page);
    await expect(page.getByTestId('maps-place-card')).toHaveAttribute('data-selected', 'true');
    await expect(page.getByTestId('maps-place-card')).toHaveClass(/selected/);
    await page.goto(preview('maps/MapsLocationEmbedPreview', width, 'nearbyArea'));
    await waitForComponentPreview(page);
    await expect(page.getByTestId('maps-location-approximate')).toContainText('Approximate area');
    await expect(page.getByTestId('result-card-media')).toHaveCount(0);
    await page.goto(preview('maps/MapsLocationEmbedPreview', width, 'brokenImage'));
    await waitForComponentPreview(page);
    await expect(page.getByTestId('result-card-media')).toHaveCount(0);
    await expect(page.getByTestId('result-card-content')).toContainText('Europaplatz 1');
  });
}

for (const width of [390, 1280]) {
  // contract-test: supporting surface=gui.web assertions=travel-search.surface-parity
  test(`connection carrier fallback and essential facts fit inside the card at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(preview('travel/TravelConnectionEmbedPreview', width, 'brokenCarrier'));
    await waitForComponentPreview(page);
    const card = page.getByTestId('embed-preview');
    const logo = page.getByTestId('airline-logos').locator('img');
    await expect(logo).toHaveAttribute('alt', 'Rail provider');
    await expect(logo).not.toHaveAttribute('src', '/missing-carrier-fixture.png');
    await expect.poll(() => logo.evaluate(image => (image as HTMLImageElement).complete && (image as HTMLImageElement).naturalWidth > 0)).toBe(true);
    const bounds = (await card.boundingBox())!;
    for (const fact of await card.locator('.journey-date, .journey-times, [data-testid="connection-price"], [data-testid="connection-meta"], .seats-warning').all()) {
      const factBounds = (await fact.boundingBox())!;
      expect(factBounds.y).toBeGreaterThanOrEqual(bounds.y);
      expect(factBounds.y + factBounds.height).toBeLessThanOrEqual(bounds.y + bounds.height - 5);
    }
    await expect(page.getByTestId('connection-meta')).not.toContainText('Mar 15');
    await expect(page.getByTestId('connection-time')).toContainText('→');
    await testInfo.attach(`connection-carrier-fallback-${width}`, { body: await page.screenshot(), contentType: 'image/png' });
  });
}

// contract-test: supporting surface=gui.web assertions=events-search.surface-parity
test('event description preserves provider HTML structure safely and dates use the event timezone', async ({ page }, testInfo) => {
  const forbiddenRequests: string[] = [];
  page.on('request', request => { if (request.url().includes('event-description-must-not-load')) forbiddenRequests.push(request.url()); });
  await page.goto(preview('events/EventEmbedFullscreen', 1280, 'formattedHtml'));
  await waitForComponentPreview(page);
  const description = page.getByTestId('event-description');
  await expect(description.locator('p').first()).toHaveText('Join our Book Lovers Social meetup!');
  await expect(description.locator('strong')).toHaveText('Book Lovers Social meetup!');
  await expect(description.locator('em')).toHaveText('Matt Damon');
  await expect(description.locator('ol li')).toHaveCount(2);
  const guide = description.getByRole('link', { name: 'reading guide' });
  await expect(guide).toHaveAttribute('href', 'https://example.com/reading');
  await expect(guide).toHaveAttribute('target', '_blank');
  await expect(guide).toHaveAttribute('rel', 'noopener noreferrer');
  await expect(description.locator('script, img, iframe, [onerror], a[href^="javascript:"]')).toHaveCount(0);
  expect(forbiddenRequests).toHaveLength(0);
  await description.scrollIntoViewIfNeeded();
  await testInfo.attach('event-formatted-description', { body: await page.screenshot(), contentType: 'image/png' });
  await page.goto(preview('events/EventEmbedFullscreen', 390, 'overnightTimezone'));
  await waitForComponentPreview(page);
  await expect(page.getByTestId('event-time-range')).toHaveText(/Mar 15 11:30 PM\s*–\s*Mar 16 1:00 AM/);
  await page.goto(preview('events/EventEmbedPreview', 390, 'timezoneBoundary'));
  await waitForComponentPreview(page);
  await expect(page.getByTestId('embed-calendar-date').locator('strong')).toHaveText('16');
  await expect(page.getByTestId('embed-calendar-date').locator('span')).toHaveText('Mon');
  await expect(page.getByTestId('event-preview-attribution')).toContainText('12:30 AM, by Berlin Lingua Hub');
  await expect(page.getByTestId('event-preview-attribution')).toHaveCSS('text-overflow', 'ellipsis');
});
