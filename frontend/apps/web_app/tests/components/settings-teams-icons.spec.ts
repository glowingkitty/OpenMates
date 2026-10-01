import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import type { Locator } from '@playwright/test';

// playwright-account: not_required reason=isolated_component_preview

const canonicalIcon = (name: string) =>
	readFileSync(
		resolve(__dirname, '../../../../packages/ui/static/icons', `${name}.svg`),
		'utf8'
	).trim();

async function expectCanonicalMask(icon: Locator, name: string) {
	await expect
		.poll(() =>
			icon.evaluate(async (element, canonical) => {
				const mask = getComputedStyle(element).maskImage;
				const match = mask.match(/^url\(["']?(.*?)["']?\)$/);
				if (!match) return false;
				type Shape = { tag: string; attributes: [string, string][]; children: Shape[] };
				const shape = (node: Element): Shape => ({
					tag: node.tagName,
					attributes: Array.from(
						node.attributes,
						(attribute) => [attribute.name, attribute.value] as [string, string]
					).sort(([a], [b]) => a.localeCompare(b)),
					children: Array.from(node.children, shape)
				});
				const parse = (svg: string) => {
					const document = new DOMParser().parseFromString(svg, 'image/svg+xml');
					if (document.querySelector('parsererror')) throw new Error('Invalid canonical icon SVG');
					return shape(document.documentElement);
				};
				const actual = await (await fetch(match[1])).text();
				return JSON.stringify(parse(actual)) === JSON.stringify(parse(canonical));
			}, canonicalIcon(name))
		)
		.toBe(true);
}

test.describe('Teams settings canonical icons', () => {
	// contract-test: supporting surface=gui.web assertions=settings-ui.composition.canonical-and-accessible,settings-ui.parity.web-apple-shell
	test('empty Teams overview has masked information icons and usable create controls', async ({
		page
	}) => {
		await page.route('**/v1/teams', (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({ teams: [] })
			})
		);
		await page.setViewportSize({ width: 402, height: 874 });
		await page.goto(
			'/dev/preview/settings/SettingsTeams?theme=light&background=%23dbeafe&width=323&chrome=0'
		);
		await waitForComponentPreview(page);
		const teams = page.getByTestId('teams-settings-page');
		await expect(teams.getByText('Teams are account settings.', { exact: true })).toBeVisible();
		const icons = teams.locator('.settings-info-box.info .info-box-icon');
		await expect(icons).toHaveCount(2);
		for (const icon of await icons.all()) {
			await icon.scrollIntoViewIfNeeded();
			await expect(icon).toBeVisible();
			await expectCanonicalMask(icon, 'question');
			const bounds = await icon.boundingBox();
			expect(bounds?.width).toBe(20);
			expect(bounds?.height).toBe(20);
		}
		const input = page.getByTestId('team-name-input');
		const create = page.getByTestId('team-create-submit');
		await expect(create).toBeDisabled();
		await input.fill('Synthetic preview team');
		await expect(create).toBeEnabled();
		await expect(teams.getByText('No teams yet', { exact: true })).toBeVisible();
		const geometry = await teams.evaluate((element) => ({
			width: element.clientWidth,
			scrollWidth: element.scrollWidth
		}));
		expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.width + 1);
		await page.screenshot({
			path: test.info().outputPath('teams-overview-canonical-info-icons.png'),
			fullPage: true
		});
	});

	// contract-test: supporting surface=gui.web assertions=settings-ui.parity.web-apple-shell
	test('Teams banner resolves the route alias to its canonical mask in both header states', async ({
		page
	}) => {
		await page.setViewportSize({ width: 402, height: 874 });
		for (const variant of ['', '&variant=collapsed']) {
			await page.goto(
				`/dev/preview/settings/AppDetailsHeader?theme=light&background=%23dbeafe&width=323&chrome=0${variant}`
			);
			await waitForComponentPreview(page);
			await expect(page.getByText('Teams', { exact: true })).toBeVisible();
			const icon = page.locator('.banner-mask-icon');
			await expect(icon).toBeVisible();
			await expectCanonicalMask(icon, 'team');
			const bounds = await icon.boundingBox();
			expect(bounds?.width).toBe(variant ? 36 : 40);
			expect(bounds?.height).toBe(variant ? 36 : 40);
			const back = page.getByTestId('banner-back-button');
			await expect(back).toBeVisible();
			await expect(back).toBeEnabled();
			await back.click();
			await page.screenshot({
				path: test.info().outputPath(`teams-banner-${variant ? 'collapsed' : 'expanded'}.png`)
			});
		}
	});
});
