import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
import type { Locator, Page, TestInfo } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';

// playwright-account: not_required reason=isolated_component_preview
const ROOT = '/dev/preview/embeds/hosting/';
const BACKGROUND = '%23dbeafe';

type Component =
	| 'HostingSearchEmbedPreview'
	| 'HostingSearchEmbedFullscreen'
	| 'HostingDomainEmbedPreview'
	| 'HostingDomainEmbedFullscreen';

async function openPreview(page: Page, component: Component, options: {
	variant?: string;
	theme?: 'light' | 'dark';
	width?: number;
} = {}) {
	const { variant, theme = 'light', width = 390 } = options;
	await page.setViewportSize({ width, height: width < 600 ? 844 : 900 });
	const query = `theme=${theme}&background=${BACKGROUND}&width=${width}&chrome=0${variant ? `&variant=${variant}` : ''}`;
	await page.goto(`${ROOT}${component}?${query}`);
	await waitForComponentPreview(page);
	await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
}

async function expectWithinViewport(page: Page, root: Locator) {
	await expect(root).toBeVisible();
	const bounds = await root.boundingBox();
	expect(bounds).not.toBeNull();
	expect(bounds!.x).toBeGreaterThanOrEqual(-1);
	expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(page.viewportSize()!.width + 1);
	expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(page.viewportSize()!.width + 1);
}

async function checkpoint(testInfo: TestInfo, name: string, root: Locator) {
  await testInfo.attach(name, { body: await root.screenshot({ animations: 'disabled' }), contentType: 'image/png' });
}

async function chooseView(page: Page, view: string, keyboard = false) {
	const search = page.getByTestId('hosting-search-fullscreen');
	const more = search.locator('.more-trigger');
	await more.click();
	await expect(more).toHaveAttribute('aria-expanded', 'true');
	const option = search.getByTestId(`hosting-view-${view}`);
	if (keyboard) {
		await option.focus();
		await expect(option).toBeFocused();
		await page.keyboard.press('Enter');
	} else await option.click();
	await expect(more).toHaveAttribute('aria-expanded', 'false');
	await more.click();
	await expect(option).toHaveAttribute('aria-pressed', 'true');
	await more.click();
	await expect(option).not.toBeVisible();
}

async function expectHeaderThenChildren(search: Locator) {
	await expect(search.locator('.search-results > :first-child')).toHaveAttribute('data-testid', 'hosting-domain-grid');
	await expect(search.locator('.search-results > *')).toHaveCount(1);
	await expect(search.locator('.search-results .summary, .search-results .filters, .search-results .notice')).toHaveCount(0);
	await expect(search.getByTestId('hosting-view-all')).not.toBeVisible();
}

async function expectCanonicalSvgPaths(icon: Locator, asset: 'server' | 'search', property: 'backgroundImage' | 'maskImage', pseudo = false) {
	const canonical = await readFile(resolve(__dirname, `../../../../packages/ui/static/icons/${asset}.svg`), 'utf8');
	const paths = await icon.evaluate(async (element, { canonical, property, pseudo }) => {
		const parsePaths = (xml: string) => Array.from(
			new DOMParser().parseFromString(xml, 'image/svg+xml').querySelectorAll('path'),
			(path) => path.getAttribute('d')
		);
		const image = pseudo ? getComputedStyle(element, '::after')[property] : getComputedStyle(element)[property];
		if (!image.startsWith('url(')) return { expected: parsePaths(canonical), actual: [] };
		let source = image.slice(4, -1).trim();
		if ((source.startsWith('"') && source.endsWith('"')) || (source.startsWith("'") && source.endsWith("'")))
			source = source.slice(1, -1);
		const response = await fetch(source);
		const actual = parsePaths(await response.text());
		const decoded = new Image();
		decoded.src = source;
		await decoded.decode();
		await new Promise<void>((done) => requestAnimationFrame(() => requestAnimationFrame(() => done())));
		return { expected: parsePaths(canonical), actual };
	}, { canonical, property, pseudo });
	expect(paths.expected.length).toBeGreaterThan(0);
	expect(paths.actual).toEqual(paths.expected);
}

async function expectHostingGlyph(root: Locator) {
	const badge = root.locator('[data-app-icon="hosting"]').first();
	const glyph = root.locator('.icon_rounded.hosting').first();
	await expect(badge).toBeVisible();
	await expect(glyph).toBeVisible();
	expect(await badge.evaluate((element) => getComputedStyle(element).backgroundImage)).toContain('gradient(');
	const cardBox = await root.boundingBox();
	const badgeBox = await badge.boundingBox();
	expect(cardBox).not.toBeNull();
	expect(badgeBox).not.toBeNull();
	expect(badgeBox!.x).toBeGreaterThanOrEqual(cardBox!.x - 1);
	expect(badgeBox!.y).toBeGreaterThanOrEqual(cardBox!.y - 1);
	expect(badgeBox!.x + badgeBox!.width).toBeLessThanOrEqual(cardBox!.x + cardBox!.width + 1);
	expect(badgeBox!.y + badgeBox!.height).toBeLessThanOrEqual(cardBox!.y + cardBox!.height + 1);
	const metrics = await glyph.evaluate((element) => {
		const box = element.getBoundingClientRect();
		const icon = getComputedStyle(element, '::after');
		return {
			badgeWidth: box.width,
			badgeHeight: box.height,
			glyphWidth: parseFloat(icon.width),
			glyphHeight: parseFloat(icon.height),
		};
	});
	expect(metrics.badgeWidth).toBeGreaterThan(0);
	expect(metrics.badgeHeight).toBeGreaterThan(0);
	expect(metrics.glyphWidth).toBeGreaterThan(0);
	expect(metrics.glyphHeight).toBeGreaterThan(0);
	await expectCanonicalSvgPaths(glyph, 'server', 'backgroundImage', true);
}

async function expectSearchHeaderGlyph(root: Locator) {
	const icon = root.locator('.header-skill-icon[data-skill-icon="search"]').first();
	await expect(icon).toBeVisible();
	const metrics = await icon.evaluate((element) => {
		const box = element.getBoundingClientRect();
		return { width: box.width, height: box.height };
	});
	expect(metrics.width).toBeGreaterThan(0);
	expect(metrics.height).toBeGreaterThan(0);
	await expectCanonicalSvgPaths(icon, 'search', 'maskImage');
}

// contract-test: direct surface=gui.web assertions=hosting-domains.embeds.parent-child,hosting-domains.quotes.truthful,hosting-domains.results.partial-and-safe,hosting-domains.surface-parity
test('search preview summarizes checked results and exposes honest terminal states', async ({ page }, testInfo) => {
	test.setTimeout(90_000);
	await openPreview(page, 'HostingSearchEmbedPreview');
	const card = page.locator('.unified-embed-preview').first();
	await expect(page.getByTestId('hosting-search-preview')).toBeVisible();
	await expectWithinViewport(page, card);
	await expect(card).toContainText('cedarcomet');
	await expect(card).toContainText('Gandi');
	await expect(card).toContainText('6 checked');
	await expect(card).toContainText('3 available');
	await expect(card).toContainText(/available/i);
	await expect(card).toContainText(/first year/i);
	await expect(card).toContainText(/13[.,]09/);
	await expect(card.getByTestId('embed-status-value')).toHaveCount(0);
	await expectHostingGlyph(card);
	await checkpoint(testInfo, 'hosting-search-preview-default-phone-light', card);

	for (const variant of ['processing', 'cancelled', 'empty', 'error', 'partial'] as const) {
		await openPreview(page, 'HostingSearchEmbedPreview', { variant });
		await expectWithinViewport(page, card);
		await expect(card).toContainText('cedarcomet');
		if (variant === 'processing') {
			await expect(card.getByTestId('embed-status-value').first()).toBeVisible();
			await expect(card.getByTestId('embed-status-value').first()).toHaveClass(/processing-shimmer/);
		} else await expect(card.getByTestId('embed-status-value')).toHaveCount(0);
		if (variant === 'partial') {
			await expect(page.getByTestId('hosting-search-partial')).toBeVisible();
		} else {
			await expect(card).not.toContainText(/from\s+€|from\s+EUR/i);
		}
	}

	await openPreview(page, 'HostingSearchEmbedPreview', { theme: 'dark', width: 1280 });
	await expectWithinViewport(page, card);
	await expectHostingGlyph(card);
	await checkpoint(testInfo, 'hosting-search-preview-default-laptop-dark', card);
});

// contract-test: direct surface=gui.web assertions=hosting-domains.embeds.parent-child,hosting-domains.availability.selection,hosting-domains.results.partial-and-safe,hosting-domains.surface-parity
test('search fullscreen filters checked children locally and opens their details', async ({ page }, testInfo) => {
	test.setTimeout(90_000);
	await openPreview(page, 'HostingSearchEmbedFullscreen');
	const grid = page.getByTestId('hosting-domain-grid');
	const search = page.getByTestId('hosting-search-fullscreen');
	await expectWithinViewport(page, grid);
	await expect(grid).toContainText('cedarcomet');
	await expectHeaderThenChildren(search);
	await expect(grid.getByTestId('hosting-domain-preview')).toHaveCount(2);
	await expect(grid).toContainText('cedarcomet.com');
	await expect(grid).toContainText('cedarcomet.net');
	await expectSearchHeaderGlyph(page.getByTestId('hosting-search-fullscreen'));
	await checkpoint(testInfo, 'hosting-search-selected-phone-light', search);

	const outboundRequests: string[] = [];
	page.on('request', (request) => {
		if (/\/(?:v1\/apps\/hosting|gandi)\//i.test(request.url()))
			outboundRequests.push(request.url());
	});
	await chooseView(page, 'available');
	await expect(grid.getByTestId('hosting-domain-preview')).toHaveCount(2);
	await expect(grid).toContainText(/available/i);
	await expect(grid).not.toContainText(/unavailable|could not check/i);
	await chooseView(page, 'in-use');
	await expect(grid.getByTestId('hosting-domain-preview')).toHaveCount(2);
	await expect(grid).toContainText('cedarcomet.org');
	await expect(grid).toContainText('cedarcomet.co');
	await expect(grid).not.toContainText(/could not check/i);
	const childCard = grid.locator('.unified-embed-preview').first();
	await childCard.focus();
	await expect(childCard).toBeFocused();
	await page.keyboard.press('Enter');
	const detail = page.getByTestId('hosting-domain-fullscreen');
	await expect(detail).toBeVisible();
	await expect(detail).toContainText('cedarcomet.org');
	await detail.getByRole('button', { name: 'Next embed' }).click();
	await expect(detail).toContainText('cedarcomet.co');
	await expect(detail.getByTestId('hosting-domain-back')).toHaveCount(0);
	await expect(detail.getByRole('button', { name: /back to results/i })).toHaveCount(0);
	await detail.getByTestId('embed-minimize').click();
	await expect(detail).toHaveCount(0);
	await expect(grid.getByTestId('hosting-domain-preview')).toHaveCount(2);
	await expect(grid).toContainText('cedarcomet.org');
	await chooseView(page, 'all', true);
	await expect(grid.getByTestId('hosting-domain-preview')).toHaveCount(2);
	await expect(grid).toContainText('cedarcomet.com');
	await expect(grid).not.toContainText(/could not check/i);
	await chooseView(page, 'unknown');
	await expect(grid.getByTestId('hosting-domain-preview')).toHaveCount(1);
	const unknownStatus = grid.getByTestId('hosting-domain-preview').locator('.topline > span:first-child');
	await expect(unknownStatus).toHaveText(/could not check/i);
	await expect(unknownStatus).not.toHaveText(/unavailable/i);
	await expect(grid.getByTestId('hosting-domain-registration')).toContainText(/price unavailable/i);
	await expect(outboundRequests).toEqual([]);
	await checkpoint(testInfo, 'hosting-search-unknown-phone-light', grid);

	await openPreview(page, 'HostingSearchEmbedFullscreen', { variant: 'partial' });
	await expectHeaderThenChildren(search);
	await expect(search.getByTestId('hosting-search-partial')).toHaveCount(0);
	await chooseView(page, 'unknown');
	await expect(page.getByTestId('hosting-domain-grid')).toContainText(/could not check/i);
	await openPreview(page, 'HostingSearchEmbedFullscreen', { variant: 'availableOnly' });
	await expect(page.getByTestId('hosting-domain-grid')).not.toContainText(/unavailable|in use/i);
	await openPreview(page, 'HostingSearchEmbedFullscreen', { variant: 'empty' });
	await expect(page.getByTestId('hosting-search-empty')).toBeVisible();
	await openPreview(page, 'HostingSearchEmbedFullscreen', { variant: 'error' });
	await expectHeaderThenChildren(search);
	await expect(page.getByTestId('hosting-domain-grid')).toContainText(/could not check/i);
	for (const variant of ['processing', 'cancelled'] as const) {
		await openPreview(page, 'HostingSearchEmbedFullscreen', { variant });
		await expect(page.getByTestId('hosting-domain-grid')).toHaveCount(0);
		await expect(page.getByTestId('hosting-search-fullscreen')).toContainText(variant === 'processing' ? /searching|processing/i : /cancelled/i);
	}
	await openPreview(page, 'HostingSearchEmbedFullscreen', { theme: 'dark', width: 1280 });
	await expectWithinViewport(page, page.getByTestId('hosting-domain-grid'));
	await expectHeaderThenChildren(search);
	await checkpoint(testInfo, 'hosting-search-selected-laptop-dark', search);
});

// contract-test: direct surface=gui.web assertions=hosting-domains.embeds.parent-child,hosting-domains.quotes.truthful,hosting-domains.results.partial-and-safe,hosting-domains.surface-parity
test('domain preview distinguishes registration, renewal, terms and check status', async ({ page }, testInfo) => {
	test.setTimeout(90_000);
	await openPreview(page, 'HostingDomainEmbedPreview');
	const card = page.locator('.unified-embed-preview').first();
	await expect(page.getByTestId('hosting-domain-preview')).toBeVisible();
	await expectWithinViewport(page, card);
	await expect(card).toContainText('cedarcomet');
	await expect(card.getByTestId('embed-status-value')).toHaveCount(0);
	await expect(card).toContainText(/renewal/i);
	await expect(card).toContainText(/first.year offer/i);
	await expect(page.getByTestId('hosting-domain-registration')).toContainText(/14[.,]27\s*\/\s*year/i);
	await expect(page.getByTestId('hosting-domain-renewal')).toContainText(/47[.,]60\s*\/\s*year/i);
	await expectHostingGlyph(card);
	await checkpoint(testInfo, 'hosting-domain-preview-default-phone-light', card);

	for (const [variant, expected] of [
		['unavailable', /unavailable|in use/i],
		['unknown', /could not check/i],
		['premium', /premium/i],
		['minTwoYears', /minimum 2 years/i],
		['missingPrice', /price unavailable/i],
		['longIdn', /\.test/i],
	] as const) {
		await openPreview(page, 'HostingDomainEmbedPreview', { variant });
		await expectWithinViewport(page, card);
		await expect(card).toContainText(expected);
		if (variant === 'unknown') {
			const status = card.locator('.topline > span:first-child');
			await expect(status).toHaveText(/could not check/i);
			await expect(status).not.toHaveText(/unavailable/i);
			await expect(card.getByTestId('hosting-domain-registration')).toContainText(/price unavailable/i);
		}
		if (variant === 'minTwoYears') await expect(card).not.toContainText(/first.year offer/i);
		if (variant === 'longIdn') {
			const suffix = card.locator('.domain-suffix');
			await expect(suffix).toContainText(/\.test$/);
			const suffixBox = await suffix.boundingBox();
			const cardBox = await card.boundingBox();
			expect(suffixBox).not.toBeNull();
			expect(cardBox).not.toBeNull();
			expect(suffixBox!.x + suffixBox!.width).toBeLessThanOrEqual(cardBox!.x + cardBox!.width + 1);
			await checkpoint(testInfo, 'hosting-domain-preview-long-idn-phone-light', card);
		}
	}
	await openPreview(page, 'HostingDomainEmbedPreview', { theme: 'dark', width: 1280 });
	await expectWithinViewport(page, card);
	await expectHostingGlyph(card);
	await checkpoint(testInfo, 'hosting-domain-preview-default-laptop-dark', card);
});

// contract-test: direct surface=gui.web assertions=hosting-domains.embeds.parent-child,hosting-domains.surface-parity
test('fullscreen keeps standard domain card dimensions while the pane shrinks and grows', async ({ page }, testInfo) => {
	test.setTimeout(90_000);
	await openPreview(page, 'HostingSearchEmbedFullscreen', { width: 1280, theme: 'dark' });
	const grid = page.getByTestId('hosting-domain-grid');
	const cards = grid.getByTestId('embed-preview');
	await expect(cards).toHaveCount(2);
	for (const width of [1280, 1000, 760, 620, 500, 390, 320, 390, 1000]) {
		await page.setViewportSize({ width, height: 900 });
		await page.mouse.move(0, 0);
		await expect.poll(async () => cards.evaluateAll((elements) => elements.map((element) => {
			const bounds = element.getBoundingClientRect();
			return [Math.round(bounds.width), Math.round(bounds.height)];
		}))).toEqual([[300, 200], [300, 200]]);
		for (let index = 0; index < 2; index++) await expectWithinViewport(page, cards.nth(index));
		if (width === 390 || width === 620) await checkpoint(testInfo, `hosting-domain-fixed-width-pane-${width}`, page.getByTestId('hosting-search-fullscreen'));
	}
});

// contract-test: direct surface=gui.web assertions=hosting-domains.embeds.parent-child,hosting-domains.quotes.truthful,hosting-domains.surface-parity
test('domain fullscreen keeps quote terms, source and copyable names readable', async ({ page }, testInfo) => {
	test.setTimeout(90_000);
	await openPreview(page, 'HostingDomainEmbedFullscreen');
	const detail = page.getByTestId('hosting-domain-fullscreen');
	await expectWithinViewport(page, detail);
	await expect(detail.getByTestId('hosting-domain-back')).toHaveCount(0);
	await expect(detail.getByRole('button', { name: /back to results/i })).toHaveCount(0);
	await expectSearchHeaderGlyph(detail);
	await expect(page.getByTestId('hosting-domain-registration')).toBeVisible();
	await expect(page.getByTestId('hosting-domain-renewal')).toBeVisible();
	await expect(page.getByTestId('hosting-domain-registration')).toContainText(/13[.,]09/);
	await expect(page.getByTestId('hosting-domain-renewal')).toContainText(/38[.,]06/);
	await expect(detail).not.toContainText(/first.year offer/i);
	await expect(detail.getByRole('table')).toHaveCount(2);
	await expect(detail).toContainText(/VAT|tax/i);
	await expect(detail).not.toContainText(/\b1 years\b/i);
	await expect(detail).toContainText(/availability.*change|prices.*change/i);
	await expect(detail.getByRole('link', { name: /open on Gandi/i })).toHaveAttribute('href', /^https:\/\/shop\.gandi\.net\//);
	await checkpoint(testInfo, 'hosting-domain-detail-default-phone-light', detail);

	await openPreview(page, 'HostingDomainEmbedFullscreen', { variant: 'minTwoYears' });
	await expect(page.getByTestId('hosting-domain-registration')).toContainText(/minimum 2 years/i);
	await expect(detail).not.toContainText(/first.year offer/i);
	await openPreview(page, 'HostingDomainEmbedFullscreen', { variant: 'premium' });
	await expect(detail).toContainText(/premium/i);
	await expect(detail).toContainText(/identity verification/i);
	await openPreview(page, 'HostingDomainEmbedFullscreen', { variant: 'missingPrice' });
	await expect(page.getByTestId('hosting-domain-registration')).toContainText(/price unavailable/i);
	await expect(page.getByTestId('hosting-domain-renewal')).toContainText(/price unavailable/i);
	await openPreview(page, 'HostingDomainEmbedFullscreen', { variant: 'unknown' });
	const unknownSubtitle = detail.getByTestId('embed-header-subtitle');
	await expect(unknownSubtitle).toContainText(/could not check/i);
	await expect(unknownSubtitle).not.toContainText(/unavailable/i);
	await expect(page.getByTestId('hosting-domain-registration')).toContainText(/price unavailable/i);
	await openPreview(page, 'HostingDomainEmbedFullscreen', { variant: 'longIdn' });
	await expect(page.getByTestId('hosting-domain-ascii')).toContainText(/xn--/);
	await expect(page.getByTestId('hosting-domain-ascii')).toHaveCSS('user-select', 'text');
	await expectWithinViewport(page, detail);
	await checkpoint(testInfo, 'hosting-domain-detail-long-idn-phone-light', detail);
	await openPreview(page, 'HostingDomainEmbedFullscreen', { theme: 'dark', width: 1280 });
	await expectWithinViewport(page, detail);
	await checkpoint(testInfo, 'hosting-domain-detail-default-laptop-dark', detail);
});
