/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Public and settings coverage for the Design icon-search example chat.
 *
 * Product contract: docs/specs/design-search-icons/spec.yml
 * Source chat must be a real natural-language CLI chat that triggered
 * design.search_icons, not a hand-authored fixture.
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { closeFullscreen, openFullscreen, verifySearchGrid } = require('./helpers/embed-test-helpers');
const { getE2EDebugUrl } = require('./signup-flow-helpers');

const EXAMPLE_SLUG = 'dashboard-sidebar-svg-icons';
const EXAMPLE_CHAT_ID = 'example-dashboard-sidebar-svg-icons';
const DESIGN_ICON_ROUTE = '/v1/apps/design/icons/iconify/';

function trackIconRequests(page: any) {
	const forbidden: string[] = [];
	const openMatesSvg: string[] = [];

	page.on('request', (request: any) => {
		const url = request.url();
		if (url.includes('api.iconify.design') || /preview[^/]*\/.*iconify|iconify.*preview/i.test(url)) {
			forbidden.push(url);
		}
		if (url.includes(DESIGN_ICON_ROUTE)) {
			openMatesSvg.push(url);
		}
	});

	return { forbidden, openMatesSvg };
}

async function openDesignIconExample(page: any) {
	const response = await page.goto(getE2EDebugUrl(`/example/${EXAMPLE_SLUG}`), {
		waitUntil: 'domcontentloaded'
	});
	expect(response?.status()).toBe(200);
	await expect(page).toHaveURL(new RegExp(`#chat-id=${EXAMPLE_CHAT_ID}`), { timeout: 15_000 });
	await expect(page.getByTestId('user-message-content').filter({ hasText: 'Find open-source SVG home and settings icons' })).toBeVisible({ timeout: 30_000 });
	await expect(page.getByTestId('message-assistant').filter({ hasText: 'Tabler Icons' })).toBeVisible({ timeout: 30_000 });
}

test.describe('Design icon search example', () => {
	test('renders the settings-linked example and icon embeds through OpenMates SVG routes', async ({ page }) => {
		test.setTimeout(120_000);
		await page.setViewportSize({ width: 1600, height: 900 });

		const requests = trackIconRequests(page);

		await page.goto(getE2EDebugUrl('/#settings/apps/design/skill/search_icons'), {
			waitUntil: 'domcontentloaded'
		});
		await page.waitForLoadState('networkidle');

		const settingsMenu = page.locator('[data-testid="settings-menu"].visible');
		await expect(settingsMenu).toBeVisible({ timeout: 15_000 });
		await expect(settingsMenu).toHaveAttribute('data-active-view', 'apps/design/skill/search_icons', {
			timeout: 15_000
		});

		const exampleCard = settingsMenu.locator('[data-testid="app-store-example-chat-card"][data-app-id="design"][data-skill-id="search_icons"]').first();
		await expect(exampleCard).toBeVisible({ timeout: 15_000 });
		await expect(exampleCard.getByTestId('resume-large-title')).toContainText('Dashboard Sidebar SVG Icons');

		await openDesignIconExample(page);

		const designEmbeds = page.locator('[data-testid="embed-preview"][data-app-id="design"][data-skill-id="search_icons"][data-status="finished"]');
		await expect(designEmbeds.first()).toBeVisible({ timeout: 30_000 });
		await expect(async () => {
			const count = await designEmbeds.count();
			expect(count).toBeGreaterThanOrEqual(10);
		}).toPass({ timeout: 30_000 });

		const homeParent = designEmbeds.filter({ hasText: 'home' }).filter({ hasText: '20 icons' }).first();
		const settingsParent = designEmbeds.filter({ hasText: 'settings' }).filter({ hasText: '20 icons' }).first();
		await expect(homeParent).toBeVisible({ timeout: 15_000 });
		await expect(settingsParent).toBeVisible({ timeout: 15_000 });

		await expect(designEmbeds.locator(`img[src*="${DESIGN_ICON_ROUTE}"]`).first()).toBeVisible({ timeout: 30_000 });
		expect(requests.openMatesSvg.length, 'Icon previews should fetch SVGs through OpenMates API').toBeGreaterThan(0);

		const fullscreen = await openFullscreen(page, settingsParent);
		const resultCards = await verifySearchGrid(fullscreen, 5, 30_000);
		await expect(resultCards.first().locator(`img[src*="${DESIGN_ICON_ROUTE}"]`)).toBeVisible({ timeout: 30_000 });

		await resultCards.first().click();
		const resultFullscreen = page.getByTestId('design-icon-result-fullscreen');
		await expect(resultFullscreen).toBeVisible({ timeout: 15_000 });
		await expect(resultFullscreen).toContainText(/Apache 2\.0|MIT|Open Font License/);
		await expect(resultFullscreen.locator('code')).toContainText(DESIGN_ICON_ROUTE);

		const svgRequestsBeforeRecolor = requests.openMatesSvg.length;
		await page.getByTestId('design-icon-color-input').fill('#2563eb');
		await page.waitForTimeout(300);
		expect(requests.openMatesSvg.length, 'Changing color must not call the backend again').toBe(svgRequestsBeforeRecolor);
		await expect(resultFullscreen.getByRole('button', { name: 'Copy SVG' })).toBeEnabled();
		await expect(resultFullscreen.getByRole('button', { name: 'Download SVG' })).toBeEnabled();
		await expect(resultFullscreen.getByRole('button', { name: 'Download PNG' })).toBeEnabled();

		expect(requests.forbidden, 'Web rendering must not call Iconify or preview-server icon routes').toEqual([]);
		await closeFullscreen(page, page.getByTestId('embed-fullscreen-overlay'));
	});
});
