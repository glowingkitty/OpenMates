import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentMotion, waitForComponentPreview } from '../helpers/component-preview';
import type { Locator, Page, TestInfo } from '@playwright/test';

async function expectEqualWorkspaceIdentity(avatar: Locator, icon: Locator): Promise<void> {
	await expect(avatar).toBeVisible();
	await expect(icon).toBeVisible();
	await expect(avatar).toBeInViewport();
	await expect(icon).toBeInViewport();
	await expect(avatar).toHaveCSS('opacity', '0.3');
	const [avatarBox, iconBox] = await Promise.all([avatar.boundingBox(), icon.boundingBox()]);
	expect(avatarBox).not.toBeNull();
	expect(iconBox).not.toBeNull();
	expect(Math.abs(avatarBox!.width - iconBox!.width)).toBeLessThanOrEqual(1);
	expect(Math.abs(avatarBox!.height - iconBox!.height)).toBeLessThanOrEqual(1);
	expect(avatarBox!.x + avatarBox!.width).toBeLessThan(iconBox!.x);
	expect(iconBox!.x - avatarBox!.x - avatarBox!.width).toBeGreaterThanOrEqual(8);
	expect(iconBox!.x - avatarBox!.x - avatarBox!.width).toBeLessThanOrEqual(12);
	expect(
		Math.abs(avatarBox!.y + avatarBox!.height / 2 - iconBox!.y - iconBox!.height / 2)
	).toBeLessThanOrEqual(1);
}

async function attachPreviewScreenshot(
	page: Page,
	testInfo: TestInfo,
	filename: string
): Promise<void> {
	const path = testInfo.outputPath(filename);
	await page.screenshot({ path });
	await testInfo.attach(filename, { path, contentType: 'image/png' });
}

// playwright-account: not_required reason=isolated_component_preview
test.describe('Team context picker preview', () => {
	// contract-test: supporting surface=gui.web assertions=teams.context.full-switch-local
	test('shows five recent choices, expands, and supports keyboard dismissal', async ({ page }) => {
		await page.goto(
			'/dev/preview/settings/TeamContextPicker?chrome=0&theme=light&background=%23dbeafe&width=320'
		);
		await waitForComponentPreview(page);
		const trigger = page.getByTestId('team-context-dropdown');
		await trigger.click();
		const menu = page.getByTestId('team-context-menu');
		await expect(menu).toBeVisible();
		await expect(menu).toHaveCSS('background-image', /linear-gradient/);
		await expect(menu).toHaveCSS('color', 'rgb(255, 255, 255)');
		await expect(menu).toHaveCSS('border-radius', '22px');
		await expect(menu).toHaveCSS('font-size', '16px');
		await expect(menu).toHaveCSS('font-weight', '700');
		await expect(menu.getByRole('menuitemradio')).toHaveCount(6); // Personal + five Teams
		await expect(page.getByTestId('team-context-new-team')).toBeVisible();
		await page.getByTestId('team-context-show-more').click();
		await expect(menu.getByRole('menuitemradio')).toHaveCount(8);
		await page.keyboard.press('Escape');
		await expect(menu).toHaveCount(0);
		await expect(trigger).toBeFocused();
		await trigger.click();
		await page.getByTestId('team-context-option-preview-team-2').click();
		await expect(menu).toHaveCount(0);
		await expect(trigger).toBeFocused();
	});
});

test.describe('Teams settings quick action preview', () => {
	// contract-test: supporting surface=gui.web assertions=teams.context.full-switch-local,settings-ui.composition.canonical-and-accessible
	test('matches the Figma overlay with left-aligned choices and a plain New team action', async ({
		page
	}) => {
		await page.setViewportSize({ width: 1280, height: 720 });
		await page.goto(
			'/dev/preview/settings/TeamQuickActionPreviewHarness?chrome=0&theme=light&background=%23dbeafe&width=336'
		);
		await waitForComponentPreview(page);
		await page.getByTestId('team-quick-context-dropdown').click();
		const menu = page.getByTestId('team-context-menu');
		await expect(menu).toBeVisible();
		await expect(menu).toHaveCSS('width', '185px');
		await waitForComponentMotion(menu);
		for (const row of await menu.getByRole('menuitemradio').all()) {
			await expect(row).toHaveCSS('justify-content', 'flex-start');
			const geometry = await row.evaluate((element) => {
				const menu = element.parentElement!.getBoundingClientRect();
				const icon = element.firstElementChild!.getBoundingClientRect();
				const label = element.lastElementChild!.getBoundingClientRect();
				return { iconX: icon.x - menu.x, labelX: label.x - menu.x };
			});
			expect(geometry.iconX).toBeCloseTo(13, 0);
			expect(geometry.labelX).toBeCloseTo(59, 0);
		}
		const create = page.getByTestId('team-context-new-team');
		await expect(create).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
		await expect(create).toHaveCSS('background-image', 'none');
		await expect(create).toHaveCSS('justify-content', 'flex-start');
		const createGeometry = await create.evaluate((element) => {
			const menu = element.parentElement!.getBoundingClientRect();
			const icon = element.firstElementChild!.getBoundingClientRect();
			const label = element.lastElementChild!.getBoundingClientRect();
			return {
				iconX: icon.x - menu.x,
				labelX: label.x - menu.x,
				height: element.getBoundingClientRect().height
			};
		});
		expect(createGeometry.iconX).toBeCloseTo(21, 0);
		expect(createGeometry.labelX).toBeCloseTo(59, 0);
		expect(createGeometry.height).toBe(22);
	});

	// contract-test: supporting surface=gui.web assertions=teams.context.full-switch-local,teams.workspace.surface-parity
	test('has separate Team toggle, picker, and create actions', async ({ page }) => {
		await page.goto(
			'/dev/preview/settings/TeamQuickActionPreviewHarness?chrome=0&theme=light&background=%23dbeafe&width=360'
		);
		await waitForComponentPreview(page);
		const row = page.getByTestId('settings-teams-item');
		await expect(row).toBeVisible();
		const picker = page.getByTestId('team-quick-context-dropdown');
		await expect(picker).toHaveCSS('background-image', /linear-gradient/);
		await expect(picker.getByTestId('team-quick-active-team-avatar')).toBeVisible();
		await expect(page.getByTestId('team-quick-action-result')).toHaveCSS('position', 'absolute');
		await picker.click();
		const menu = page.getByTestId('team-context-menu');
		await expect(menu).toHaveCSS('width', '185px');
		await expect(menu.getByRole('menuitemradio', { name: 'xHain' })).toBeVisible();
		await expect(menu.getByRole('menuitemradio', { name: 'OpenMates' })).toBeVisible();
		await expect(menu.getByRole('menuitemradio', { name: 'Personal' })).toBeVisible();
		await expect(menu.locator('.team-avatar').first()).toHaveCSS('width', '39px');
		await expect(page.getByTestId('team-context-new-team')).toHaveCSS(
			'color',
			/(?:rgba\(255, 255, 255, 0\.7\)|color\(srgb 1 1 1 \/ 0\.7\))/
		);
		await page.keyboard.press('Escape');
		await row.getByTestId('toggle-container').click();
		await expect(page.getByTestId('team-quick-action-result')).toHaveText('toggle');
		await expect(picker).toContainText('Personal');
		await row.getByTestId('toggle-container').click();
		await expect(picker).toContainText('xHain');
		await picker.click();
		await page.getByTestId('team-context-new-team').click();
		await expect(page.getByTestId('team-quick-action-result')).toHaveText('create');
		await row.getByText('Teams', { exact: true }).click();
		await expect(page.getByTestId('team-quick-action-result')).toHaveText('open');
	});
});

test.describe('Team workspace identity preview', () => {
	// contract-test: supporting surface=gui.web assertions=teams.context.full-switch-local
	test('keeps each Team avatar equal-sized, left, aligned, and faint on phone and desktop', async ({
		page
	}, testInfo) => {
		for (const viewport of [
			{ width: 390, height: 844 },
			{ width: 1440, height: 900 }
		]) {
			await page.setViewportSize(viewport);
			for (const surface of ['chats', 'projects', 'tasks', 'workflows'] as const) {
				await page.goto(`/dev/preview/teams/TeamWorkspaceIdentity?chrome=0&variant=${surface}`);
				await waitForComponentPreview(page);
				const avatar = page.getByTestId(`${surface}-workspace-team-avatar`);
				const icon = page.getByTestId(
					surface === 'chats' ? 'guest-workspace-icon' : `${surface}-workspace-background-icon`
				);
				await expect(avatar.locator('.team-avatar')).toBeVisible();
				await expectEqualWorkspaceIdentity(avatar, icon);
				await attachPreviewScreenshot(page, testInfo, `shared-${surface}-${viewport.width}.png`);
			}
		}
	});

	// contract-test: supporting surface=gui.web assertions=teams.workspace.surface-parity
	test('keeps the three actual workspace shells aligned at phone and desktop sizes', async ({
		page
	}, testInfo) => {
		for (const viewport of [
			{ width: 390, height: 844 },
			{ width: 1440, height: 900 }
		]) {
			await page.setViewportSize(viewport);
			for (const surface of ['projects', 'tasks', 'workflows'] as const) {
				await page.goto(
					`/dev/preview/teams/TeamWorkspaceIdentityPreviewHarness?chrome=0&theme=light&background=%23dbeafe&width=${viewport.width === 390 ? 360 : 440}${surface === 'projects' ? '' : `&variant=${surface}`}`
				);
				await waitForComponentPreview(page);
				const frame = page.getByTestId('team-workspace-preview-frame');
				const shell = page.getByTestId(`${surface}-workspace-home`);
				await expect(frame).toBeInViewport();
				await expect(shell).toBeInViewport();
				const [frameBox, shellBox] = await Promise.all([frame.boundingBox(), shell.boundingBox()]);
				expect(frameBox).not.toBeNull();
				expect(shellBox).not.toBeNull();
				expect(frameBox!.height).toBeGreaterThan(500);
				expect(shellBox!.height).toBeGreaterThan(500);
				await expect(page.getByRole('heading', { name: 'Preview workspace' })).toBeInViewport();
				const avatar = page.getByTestId(`${surface}-workspace-team-avatar`);
				const icon = page.getByTestId(`${surface}-workspace-background-icon`);
				await expect(avatar.locator('.team-avatar')).toBeVisible();
				await expectEqualWorkspaceIdentity(avatar, icon);
				await attachPreviewScreenshot(page, testInfo, `shell-${surface}-${viewport.width}.png`);
			}
		}
	});

	// contract-test: supporting surface=gui.web assertions=teams.context.full-switch-local
	test('shows the Personal workspace icon without a Team avatar', async ({ page }) => {
		await page.goto('/dev/preview/teams/TeamWorkspaceIdentity?chrome=0&variant=personal');
		await waitForComponentPreview(page);
		await expect(page.getByTestId('workflows-workspace-background-icon')).toBeVisible();
		await expect(page.getByTestId('workflows-workspace-team-avatar')).toHaveCount(0);
		await expect(page.locator('.workspace-identity .team-avatar')).toHaveCount(0);
	});
});

test.describe('Team profile badge preview', () => {
	// contract-test: supporting surface=gui.web assertions=teams.context.full-switch-local,teams.workspace.surface-parity
	test('shows only an accessible circular Team badge at the profile bottom-left', async ({
		page
	}, testInfo) => {
		for (const viewport of [
			{ width: 390, height: 844 },
			{ width: 1440, height: 900 }
		]) {
			await page.setViewportSize(viewport);
			await page.goto('/dev/preview/teams/TeamProfileBadgePreviewHarness?chrome=0');
			await waitForComponentPreview(page);
			const profile = page.getByTestId('profile-avatar-preview-parent');
			const badge = page.getByTestId('profile-active-team-avatar');
			await expect(profile).toBeVisible();
			await expect(badge).toBeVisible();
			await expect(badge).toHaveAttribute('role', 'img');
			await expect(badge).toHaveAttribute('aria-label', 'Active team: Preview team');
			await expect(badge).not.toHaveAttribute('title', /.+/);
			await expect(badge).toHaveText('');
			await expect(badge).toHaveCSS('width', '24px');
			await expect(badge).toHaveCSS('height', '24px');
			expect(
				await badge.evaluate((element) => {
					const radius = getComputedStyle(element).borderTopLeftRadius;
					return radius.endsWith('%')
						? Number.parseFloat(radius) >= 50
						: Number.parseFloat(radius) >= element.getBoundingClientRect().width / 2;
				})
			).toBe(true);
			await expect(badge.locator('.team-avatar')).toHaveCSS('width', '22px');
			const [profileBox, badgeBox] = await Promise.all([
				profile.boundingBox(),
				badge.boundingBox()
			]);
			expect(profileBox).not.toBeNull();
			expect(badgeBox).not.toBeNull();
			expect(profileBox!.width).toBe(50);
			expect(profileBox!.height).toBe(50);
			expect(Math.abs(badgeBox!.x - (profileBox!.x - 2))).toBeLessThanOrEqual(1);
			expect(Math.abs(badgeBox!.y + badgeBox!.height - (profileBox!.y + 54))).toBeLessThanOrEqual(
				1
			);
			await attachPreviewScreenshot(page, testInfo, `profile-badge-${viewport.width}.png`);
		}
	});
});

test.describe('Team avatar preview', () => {
	// contract-test: supporting surface=gui.web assertions=teams.workspace.surface-parity
	test('renders an authenticated uploaded image and a generated fallback', async ({ page }) => {
		await page.route('**/v1/teams/preview-team/profile-image', (route) =>
			route.fulfill({
				status: 200,
				contentType: 'image/png',
				body: Buffer.from(
					'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL/nwAAAABJRU5ErkJggg==',
					'base64'
				)
			})
		);
		await page.goto(
			'/dev/preview/teams/TeamAvatar?chrome=0&theme=light&background=%23dbeafe&variant=uploaded'
		);
		await waitForComponentPreview(page);
		await expect(page.getByTestId('preview-team-avatar').locator('img')).toBeVisible();
		await page.goto('/dev/preview/teams/TeamAvatar?chrome=0&theme=light&background=%23dbeafe');
		await waitForComponentPreview(page);
		await expect(
			page.getByTestId('preview-team-avatar').locator('.team-avatar-icon')
		).toBeVisible();
	});
});
