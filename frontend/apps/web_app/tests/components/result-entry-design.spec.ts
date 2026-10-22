import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentMotion, waitForComponentPreview } from '../helpers/component-preview';
// playwright-account: not_required reason=isolated_component_preview

const preview = (path: string, width: number, variant = '', theme = 'light') =>
	`/dev/preview/embeds/${path}?chrome=0&theme=${theme}&background=%23dbeafe&width=${width}${variant ? `&variant=${variant}` : ''}`;

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
		expect((await composer.boundingBox())!.height).toBeLessThanOrEqual(48);
		await expect(composer).toHaveCSS('background-color', 'rgb(255, 255, 255)');
		const galleryBox = (await gallery.boundingBox())!;
		const mapBox = (await map.boundingBox())!;
		if (width > 600) {
			expect(Math.abs(galleryBox.y - mapBox.y)).toBeLessThan(2);
			expect(mapBox.x).toBeGreaterThanOrEqual(galleryBox.x + galleryBox.width - 2);
		} else expect(mapBox.y).toBeGreaterThanOrEqual(galleryBox.y + galleryBox.height - 2);
		await gallery.scrollIntoViewIfNeeded();
		await page.getByRole('button', { name: 'Next photo', exact: true }).click();
		await expect(page.getByTestId('home-gallery-counter')).toHaveText('2 / 3');
		await page.getByRole('button', { name: 'Photo 2', exact: true }).focus();
		await page.keyboard.press('End');
		await expect(page.getByTestId('home-gallery-counter')).toHaveText('3 / 3');
		await page.getByTestId('home-amenity-pets_allowed').focus();
		await expect(page.getByRole('tooltip')).toContainText('Pets allowed: Unknown');
		const tooltip = (await page.getByRole('tooltip').boundingBox())!;
		expect(tooltip.x).toBeGreaterThanOrEqual(0);
		expect(tooltip.x + tooltip.width).toBeLessThanOrEqual(width);
		await page.keyboard.press('Escape');
		await expect(page.getByRole('tooltip')).toHaveCount(0);
		await expect(page.getByTestId('embed-fullscreen-overlay')).toBeVisible();
		await page.getByTestId('home-location-info').click();
		await expect(page.getByTestId('home-location-evidence')).toContainText('Approximate location');
		await page.keyboard.press('Escape');
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
			await page.goto(preview(path, width, 'chat'));
			await waitForComponentPreview(page);
			const card = page.getByTestId('embed-preview');
			await expect(card).toHaveAttribute('role', 'group');
			await expect(card.locator('.result-corner')).toBeVisible();
			await expect(card.getByTestId('result-preview-expand')).toBeVisible();
            if (path.startsWith('health/')) {
                const map = card.getByTestId('result-map-preview');
                await expect(map).toHaveAttribute('inert', '');
                await expect(map).toHaveAttribute('aria-hidden', 'true');
            }
			const title = card.locator('.listing-title, .doctor-name');
			await expect(title).toBeVisible();
			await expect(title).toHaveCSS('user-select', 'text');
			await title.click();
			expect(expansions).toHaveLength(0);
			await card.getByTestId('result-preview-expand').click();
			await expect.poll(() => expansions.length).toBe(1);
			for (const control of await card.locator('.result-tools button, .result-tools a').all()) {
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
