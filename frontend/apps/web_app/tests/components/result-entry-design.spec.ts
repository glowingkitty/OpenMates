import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentMotion, waitForComponentPreview } from '../helpers/component-preview';
// playwright-account: not_required reason=isolated_component_preview

const preview = (path: string, width: number, variant = '', theme = 'light') =>
	`/dev/preview/embeds/${path}?chrome=0&theme=${theme}&background=%23dbeafe&width=${width}${variant ? `&variant=${variant}` : ''}${variant === 'chat' ? '&context=chat' : ''}`;

for (const width of [390, 1280]) {
	// contract-test: direct surface=gui.web assertions=home-search.images.complete-gallery,home-search.listings.rich-provider-evidence,home-search.location.precision
	test(`home result design, icon explanations and gallery at ${width}px`, async ({
		page
	}, testInfo) => {
		await page.setViewportSize({ width, height: 900 });
		await page.goto(preview('home/HomeListingEmbedFullscreen', width));
		await waitForComponentPreview(page);
		await waitForComponentMotion(page.getByTestId('embed-fullscreen-overlay'));
		const content = page.getByTestId('result-embed-content');
		await expect(content).toHaveAttribute('data-app-id', 'home');
		await expect(page.getByTestId('result-facts')).toContainText(/1[,. ]250/);
		await expect(page.getByTestId('result-facts')).toContainText('65 m²');
		await expect(page.getByTestId('home-amenity-balcony')).toHaveAttribute('data-state', 'yes');
		await expect(page.getByTestId('home-amenity-furnished')).toHaveAttribute('data-state', 'no');
		await expect(page.getByTestId('home-amenity-pets_allowed')).toHaveAttribute(
			'data-state',
			'unknown'
		);
		const gallery = page.getByTestId('home-gallery');
		const map = page.getByTestId('result-map');
        const zoom = map.locator('.leaflet-control-zoom-in');
        await expect(zoom).toBeVisible();
        expect((await zoom.boundingBox())!.width).toBeLessThanOrEqual(44);
        expect((await zoom.boundingBox())!.height).toBeLessThanOrEqual(44);
		await expect(page.getByTestId('home-gallery-image')).toHaveCSS('object-fit', 'contain');
		await expect(page.getByTestId('home-location-area')).toBeVisible();
		for (const control of await gallery.locator('button').all()) {
			expect((await control.boundingBox())!.width).toBeLessThanOrEqual(44);
		}
		const composer = page.getByTestId('apps-request-composer');
		expect((await composer.boundingBox())!.height).toBeGreaterThanOrEqual(60);
        const regularComposerBackground = await composer.evaluate(element => {
            const probe = document.createElement('span');
            probe.style.background = 'var(--color-grey-blue)';
            element.appendChild(probe);
            const color = getComputedStyle(probe).backgroundColor;
            probe.remove();
            return color;
        });
        await expect(composer).toHaveCSS('background-color', regularComposerBackground);
		const galleryBox = (await gallery.boundingBox())!;
		const mapBox = (await map.boundingBox())!;
		if (width > 600) {
			expect(Math.abs(galleryBox.y - mapBox.y)).toBeLessThan(2);
			expect(mapBox.x).toBeGreaterThanOrEqual(galleryBox.x + galleryBox.width - 2);
		} else expect(mapBox.y).toBeGreaterThanOrEqual(galleryBox.y + galleryBox.height - 2);
        const thumbnail = page.getByRole('button', { name: 'Photo 2', exact: true });
        const shape = await thumbnail.evaluate(button => {
            const stage = button.closest('[data-testid="home-gallery"]')!.querySelector('.gallery-stage')!.getBoundingClientRect();
            const bounds = button.getBoundingClientRect();
            return { width: bounds.width, height: bounds.height, top: bounds.top, bottom: bounds.bottom, stageBottom: stage.bottom, overlay: getComputedStyle(button, '::after').backgroundColor, opacity: getComputedStyle(button, '::after').opacity };
        });
        expect(shape.width).toBe(shape.height);
        expect(shape.top).toBeLessThan(shape.stageBottom);
        expect(shape.bottom).toBeGreaterThan(shape.stageBottom);
        expect(shape.overlay).toBe('rgba(255, 255, 255, 0.6)');
        expect(shape.opacity).toBe('1');
        await thumbnail.hover();
        await expect.poll(() => thumbnail.evaluate(button => getComputedStyle(button, '::after').opacity)).toBe('0');
        for (const name of ['Previous photo', 'Next photo']) {
            const arrow = page.getByRole('button', { name, exact: true });
            await expect(arrow).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
            await expect(arrow).toHaveCSS('border-radius', '0px');
        }
		await gallery.scrollIntoViewIfNeeded();
		await page.getByRole('button', { name: 'Next photo', exact: true }).click();
		await expect(page.getByTestId('home-gallery-image')).toHaveAttribute('src', '/store-examples/home-2.webp');
        await expect(page.getByRole('button', { name: 'Photo 2', exact: true })).toHaveAttribute('aria-pressed', 'true');
		await page.getByRole('button', { name: 'Photo 2', exact: true }).focus();
		await page.keyboard.press('End');
		await expect(page.getByTestId('home-gallery-image')).toHaveAttribute('src', '/store-examples/home-3.webp');
        await expect(page.getByTestId('home-gallery-counter')).toHaveCount(0);
		await page.getByTestId('home-amenity-pets_allowed').focus();
		await expect(page.getByRole('tooltip')).toContainText('Pets allowed: Unknown');
		const tooltip = (await page.getByRole('tooltip').boundingBox())!;
		expect(tooltip.x).toBeGreaterThanOrEqual(0);
		expect(tooltip.x + tooltip.width).toBeLessThanOrEqual(width);
		await page.keyboard.press('Escape');
		await expect(page.getByRole('tooltip')).toHaveCount(0);
		await expect(page.getByTestId('embed-fullscreen-overlay')).toBeVisible();
		await expect(page.getByTestId('home-location-info')).toHaveCount(0);
        await expect(page.getByTestId('home-location-label')).toContainText('Approximate location');
		await page.getByTestId('result-facts').scrollIntoViewIfNeeded();
		await expect(page.getByTestId('external-provider-cta')).toBeVisible();
		await expect(page.getByTestId('apps-request-textarea')).toBeVisible();
		await expect(content).not.toHaveCSS('overflow-x', 'scroll');
		await testInfo.attach(`home-design-${width}`, {
			body: await page.screenshot(),
			contentType: 'image/png'
		});
	});

	// contract-test: direct surface=gui.web assertions=health-search-appointments.results.booking-provenance,health-search-appointments.surface-parity
	test(`appointment shared result design and unknown insurance at ${width}px`, async ({
		page
	}, testInfo) => {
		await page.setViewportSize({ width, height: 900 });
		await page.goto(preview('health/HealthAppointmentEmbedFullscreen', width));
		await waitForComponentPreview(page);
		await waitForComponentMotion(page.getByTestId('embed-fullscreen-overlay'));
		await expect(page.getByTestId('result-facts')).toContainText('4.8');
		await expect(page.getByTestId('result-facts')).toContainText('120 EUR');
		await expect(page.getByTestId('result-facts')).toContainText('Private');
		await expect(page.getByTestId('result-map')).toBeVisible();
		await expect(page.getByTestId('external-provider-cta')).toHaveText('Open on Doctolib');
		await expect(page.getByTestId('apps-request-textarea')).toBeVisible();
		await page.getByTestId('health-appointment-info').click();
		await expect(page.getByRole('tooltip')).toContainText('Dr. Sophie Müller');
		await page.keyboard.press('Escape');
		await expect(page.getByTestId('embed-fullscreen-overlay')).toBeVisible();
		await page.getByTestId('result-facts').scrollIntoViewIfNeeded();
		await testInfo.attach(`appointment-design-${width}`, {
			body: await page.screenshot(),
			contentType: 'image/png'
		});
		await page.goto(
			preview('health/HealthAppointmentEmbedFullscreen', width, 'unknownInsurance', 'dark')
		);
		await waitForComponentPreview(page);
		await expect(page.getByTestId('result-facts')).not.toContainText('Private');
		const insurance = page
			.getByTestId('result-facts')
			.getByRole('button', { name: /verify on Doctolib/ });
		await expect(insurance).toHaveAttribute('data-state', 'unknown');
		await insurance.focus();
		await expect(page.getByRole('tooltip')).toContainText('verify on Doctolib');
	});

	// contract-test: supporting surface=gui.web assertions=home-search.images.complete-gallery,health-search-appointments.surface-parity
	test(`result previews show bottom identity and explicit chat expansion at ${width}px`, async ({
		page
	}, testInfo) => {
		await page.setViewportSize({ width, height: 900 });
		for (const path of ['home/HomeListingEmbedPreview', 'health/HealthAppointmentEmbedPreview']) {
			const expansions: string[] = [];
			const listener = (message: { text(): string }) => {
				if (message.text() === '[Preview] result expanded') expansions.push(message.text());
			};
			page.on('console', listener);
			await page.goto(`${preview(path, width, 'chat')}&context=chat`);
			await waitForComponentPreview(page);
			const card = page.getByTestId('embed-preview');
			await expect(card).toHaveAttribute('role', 'group');
			await expect(card.locator('.result-corner')).toBeVisible();
			await expect(card.getByTestId('result-preview-expand')).toBeVisible();
            if (path.startsWith('health/')) {
                const map = card.getByTestId('result-map-preview');
                await expect(map).toHaveAttribute('inert', '');
                await expect(map).toHaveAttribute('aria-hidden', 'true');
                const calendar = card.getByTestId('embed-calendar-date');
                const time = card.getByTestId('embed-calendar-time');
                await expect(calendar).toBeVisible();
                await expect(time).toContainText('10:30');
                await expect(time).toHaveCSS('font-size', '14px');
                const rating = card.locator('.appointment-meta > span').filter({ hasText: '4.8' });
                await expect(rating).toHaveAttribute('title', /reviews/);
                await expect(rating.locator('svg')).toHaveCSS('fill', 'rgb(255, 213, 0)');
                await expect(rating.locator('svg')).toHaveCSS('color', 'rgb(255, 213, 0)');
                const badgeGeometry = await card.evaluate(root => {
                    const calendar = root.querySelector('[data-testid="embed-calendar-date"]')!.getBoundingClientRect();
                    const time = root.querySelector('[data-testid="embed-calendar-time"]')!.getBoundingClientRect();
                    const corner = root.querySelector('.result-corner')!.getBoundingClientRect();
                    const card = root.getBoundingClientRect();
                    return { calendarTop: calendar.top - corner.top, timeTop: time.top - corner.top,
                        visible: [calendar, time].every(rect => rect.left >= card.left && rect.right <= card.right && rect.top >= card.top && rect.bottom <= card.bottom) };
                });
                expect(badgeGeometry.visible).toBe(true);
                if (width === 390) {
                    expect(badgeGeometry.calendarTop).toBeGreaterThanOrEqual(0);
                    expect(badgeGeometry.calendarTop).toBeLessThanOrEqual(2.5);
                    expect(badgeGeometry.timeTop).toBeLessThanOrEqual(8.5);
                }

            }
			const title = card.locator('.listing-title, .doctor-name, [data-testid="result-card-title"], [data-testid="health-appointment-title"]');
			await expect(title).toBeVisible();
			await expect(title).toHaveCSS('user-select', 'text');
			const tools = card.getByTestId('preview-tools');
			const colors = await tools.evaluate(element => Array.from(element.querySelectorAll('button, a')).map(control => {
				const icon = control.querySelector('svg, .clickable-icon')!;
				const style = getComputedStyle(icon);
				return icon.tagName.toLowerCase() === 'svg'
					? getComputedStyle(icon.querySelector('path, rect, circle') || icon).stroke
					: style.backgroundColor;
			}));
			expect(colors).toHaveLength(2);
			expect(colors).toEqual([colors[0], colors[0]]);
			for (const mask of await tools.locator('.clickable-icon').all()) await expect(mask).toHaveCSS('background-image', 'none');
			for (const control of await tools.locator('button, a').all()) {
				await control.hover();
				await expect(control).toHaveCSS('scale', '1.02');
			}
			await page.mouse.move(0, 0);
			for (const control of await tools.locator('button, a').all()) await expect(control).toHaveCSS('scale', '1');
			await title.click();
			expect(expansions).toHaveLength(0);
			await card.getByTestId('result-preview-expand').click();
			await expect.poll(() => expansions.length).toBe(1);
			await page.mouse.move(0, 0);
			for (const control of await card.locator('.result-tools button, .result-tools a').all()) {
				await expect(control).toHaveCSS('scale', '1');
				expect((await control.boundingBox())!.width).toBeLessThanOrEqual(36);
			}
			const box = (await card.boundingBox())!;
			expect(box.x).toBeGreaterThanOrEqual(0);
			expect(box.x + box.width).toBeLessThanOrEqual(width);
			await testInfo.attach(`${path.split('/')[0]}-preview-${width}`, {
				body: await page.screenshot(),
				contentType: 'image/png'
			});
			page.off('console', listener);
		}
	});
}

// contract-test: direct surface=gui.web assertions=home-search.location.precision,home-search.images.complete-gallery,health-search-appointments.surface-parity
test('missing photos and coordinates render truthful compact fallbacks', async ({ page }) => {
	await page.goto(preview('home/HomeListingEmbedFullscreen', 390, 'noPhotos'));
	await waitForComponentPreview(page);
	await expect(page.getByTestId('home-gallery')).toContainText('No listing photos available.');
	await expect(page.getByTestId('result-map')).toHaveCount(0);
	await page.goto(preview('health/HealthAppointmentEmbedFullscreen', 390, 'noMap'));
	await waitForComponentPreview(page);
	await expect(page.getByTestId('result-map')).toHaveCount(0);
	await expect(page.getByTestId('external-provider-cta')).toBeVisible();
});

for (const width of [390, 1280]) {
  // contract-test: direct surface=gui.web assertions=home-search.location.precision,home-search.images.complete-gallery
  test(`home missing-photo preview uses factual map geometry at ${width}px`, async ({ page }, testInfo) => {
    test.setTimeout(90_000);
    await page.setViewportSize({ width, height: 900 });
    for (const variant of ['noImage', 'brokenImage']) {
      await page.goto(`${preview('home/HomeListingEmbedPreview', width, variant)}${width > 600 ? '&context=chat' : ''}`);
      await waitForComponentPreview(page);
      const card = page.getByTestId('embed-preview');
      const map = card.getByTestId('result-map-preview');
      await expect(map).toBeVisible();
      await expect(map).toHaveAttribute('inert', '');
      await expect(card.getByTestId('home-preview-location-area')).toHaveAttribute('data-radius-m', '1200');
      await expect(card.locator('.leaflet-marker-icon')).toHaveCount(0);
      await expect(card.getByTestId('result-card-title')).toContainText('Kreuzberg');
      await testInfo.attach(`home-map-fallback-${variant}-${width}`, { body: await page.getByTestId('component-preview-canvas').screenshot(), contentType: 'image/png' });
    }
    const cityQueries: string[] = [];
    await page.route('**/v1/geocode/search?**', route => {
      cityQueries.push(new URL(route.request().url()).searchParams.get('q')!);
      return route.fulfill({json: [{name: 'Berlin', addresstype: 'city', address: {city: 'Berlin'}, boundingbox: ['52.34', '52.68', '13.09', '13.76']}]});
    });
    await page.goto(`${preview('home/HomeListingEmbedPreview', width, 'noLocation')}${width > 600 ? '&context=chat' : ''}`);
    await waitForComponentPreview(page);
    const cityArea = page.getByTestId('home-preview-location-area');
    await expect(cityArea).toBeVisible();
    await expect(cityArea).toHaveAttribute('data-area-basis', 'city');
    expect(Number(await cityArea.getAttribute('data-radius-m'))).toBeGreaterThan(20000);
    expect(Number(await cityArea.getAttribute('data-radius-m'))).toBeLessThan(40000);
    await expect(page.getByTestId('home-preview-approximate')).toHaveText('Approximate location');
    await expect(page.locator('.leaflet-marker-icon')).toHaveCount(0);
    expect(cityQueries).toEqual(['Berlin']);
    await expect(page.getByTestId('home-listing-result-card')).toContainText('Kreuzberg');
    await testInfo.attach(`home-city-fallback-${width}`, {body: await page.getByTestId('component-preview-canvas').screenshot(), contentType: 'image/png'});
  });
}

// contract-test: direct surface=gui.web assertions=home-search.listings.rich-provider-evidence,home-search.filters.explicit-and-unknown
 test('home advertised rent and availability details stay in compact fact explanations', async ({ page }) => {
  await page.goto(preview('home/HomeListingEmbedFullscreen', 390, 'rentDetails'));
  await waitForComponentPreview(page);
  await waitForComponentMotion(page.getByTestId('embed-fullscreen-overlay'));
  const facts = page.getByTestId('result-facts');
  await expect(facts).toContainText(/1[,. ]250/);
  await page.getByTestId('home-price-info').click();
  const prices = page.getByTestId('home-price-summary');
  for (const [label, value] of [['Cold rent', '1000 EUR'], ['Warm rent', '1250 EUR'], ['Utilities', '250 EUR'], ['Heating costs', '80 EUR'], ['Deposit', '3000']]) {
    await expect(prices.locator('div').filter({ has: page.locator('dt').filter({ hasText: new RegExp(`^${label}$`) }) })).toContainText(value);
  }
  await page.keyboard.press('Escape');
  await page.getByTestId('home-availability-info').click();
  await expect(page.getByRole('tooltip')).toContainText('2027-06-30');
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('result-embed-content')).not.toContainText('3000');
  for (const id of ['home-details-info', 'home-match-info', 'home-visual-info', 'home-neighborhood-info', 'home-location-info']) await expect(page.getByTestId(id)).toHaveCount(0);
});


for (const width of [390, 1280]) {
  // contract-test: direct surface=gui.web assertions=home-search.location.precision,home-search.images.complete-gallery
  test(`home without photos gives the whole media region to the map at ${width}px`, async ({page}, testInfo) => {
    await page.setViewportSize({width, height: 1000});
    await page.goto(preview('home/HomeListingEmbedFullscreen', width, 'noPhotosWithMap'));
    await waitForComponentPreview(page);
    await waitForComponentMotion(page.getByTestId('embed-fullscreen-overlay'));
    await expect(page.getByTestId('home-gallery')).toHaveCount(0);
    const region = page.getByTestId('result-media');
    const map = page.getByTestId('result-map');
    await expect(map).toBeVisible();
    expect((await map.boundingBox())!.width).toBeCloseTo((await region.boundingBox())!.width, 0);
    const zoom = map.locator('.leaflet-control-zoom-in');
    await expect(zoom).toBeVisible();
    await expect(zoom).toHaveCSS('background-color', 'rgb(255, 255, 255)');
    await testInfo.attach(`home-map-full-width-${width}`, {body: await page.screenshot(), contentType:'image/png'});
  });
}
