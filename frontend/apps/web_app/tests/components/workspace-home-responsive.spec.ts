// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

test.describe('Responsive workspace homes', () => {
	// contract-test: supporting surface=gui.web assertions=workflows-ui.workspace.recommendation-led-composition,workflows-ui.workspace.owned-library-and-templates,workspace-shell.start.available-space-cards
	test('composed workflow home keeps cards, composer and browse controls usable at short and narrow sizes', async ({ page }) => {
		test.slow();
		for (const size of [{ width: 402, height: 660 }, { width: 1376, height: 700 }, { width: 1376, height: 1032 }]) {
			await page.setViewportSize(size);
			await page.goto('/dev/preview/workflows/WorkflowHomePreviewHarness?theme=light&chrome=0');
			await waitForComponentPreview(page);
			const inspiration = page.getByTestId('workflows-daily-inspiration-area').getByTestId('daily-inspiration-banner');
			await expect(inspiration.getByTestId('daily-inspiration-phrase')).toBeVisible();
			await expect(inspiration.getByTestId('daily-inspiration-cta-text')).toHaveCount(0);
			await expect(inspiration).not.toHaveAttribute('role', 'button');
			await expect(inspiration).not.toHaveAttribute('tabindex', '0');
			await expect(inspiration).toHaveCSS('cursor', 'default');
			await inspiration.click();
			await inspiration.dispatchEvent('keydown', { key: 'Enter', bubbles: true });
			await expect(page.getByTestId('workflow-input-textarea')).toHaveValue('');
			await expect(page.getByTestId('workflow-input-textarea')).toBeVisible();
			await expect(page.getByTestId('workflow-landing-card')).toHaveCount(4);
			await expect(page.getByTestId('workflows-show-all')).toBeVisible();
			await expect(page.getByTestId('workflows-show-templates')).toBeVisible();
			const [links, composer, banner] = await Promise.all([
				page.getByTestId('workflows-workspace-link-row').boundingBox(),
				page.getByTestId('workflow-input-composer').boundingBox(),
				page.getByTestId('workflows-daily-inspiration-area').boundingBox()
			]);
			expect(links && composer && banner).toBeTruthy();
			expect(links!.y).toBeGreaterThanOrEqual(banner!.y + banner!.height);
			expect(links!.y + links!.height).toBeLessThanOrEqual(composer!.y + 1);
			const firstCard = page.getByTestId('workflow-landing-card').first();
			const cardBox = await firstCard.boundingBox();
			expect(cardBox).not.toBeNull();
			expect(cardBox!.height).toBeLessThan(size.height < 800 ? 120 : 220);
			await page.getByTestId('workflows-show-all').click();
			await expect(page.getByTestId('all-workflows-view')).toBeVisible();
			await expect(page.getByTestId('workflow-landing-card')).toHaveCount(4);
			const [backBox, searchBox, sortBox, headingBox, gridBox] = await Promise.all([
				page.getByTestId('workflows-back-to-recent').boundingBox(),
				page.getByTestId('workflows-search').boundingBox(),
				page.getByTestId('workflows-sort').boundingBox(),
				page.locator('.workspace-all-items-heading').boundingBox(),
				page.getByTestId('all-workflows-grid').boundingBox(),
			]);
			expect(backBox && searchBox && sortBox && headingBox && gridBox).toBeTruthy();
			for (const box of [backBox!, searchBox!, sortBox!]) {
				expect(box.x).toBeGreaterThanOrEqual(0);
				expect(box.x + box.width).toBeLessThanOrEqual(size.width + 1);
				expect(box.y).toBeGreaterThanOrEqual(0);
				expect(box.y + box.height).toBeLessThanOrEqual(size.height + 1);
			}
			for (const control of [backBox!, searchBox!]) {
				const separate = control.x + control.width <= sortBox!.x + 1
					|| sortBox!.x + sortBox!.width <= control.x + 1
					|| control.y + control.height <= sortBox!.y + 1
					|| sortBox!.y + sortBox!.height <= control.y + 1;
				expect(separate, 'browse toolbar must not overlap the sort control').toBe(true);
			}
			expect(headingBox!.y).toBeGreaterThanOrEqual(Math.max(backBox!.y + backBox!.height, searchBox!.y + searchBox!.height, sortBox!.y + sortBox!.height) - 1);
			expect(gridBox!.y).toBeGreaterThanOrEqual(headingBox!.y + headingBox!.height - 1);
			await page.getByTestId('workflows-sort').selectOption('running-next');
			await expect(page.getByTestId('workflow-landing-card')).toHaveCount(4);
			await expect(page.getByTestId('workflow-input-textarea')).toBeVisible();
			await page.getByTestId('workflows-back-to-recent').click();
			await expect(page.getByTestId('workflow-landing-card')).toHaveCount(4);
			await page.getByTestId('workflows-show-templates').click();
			await expect(page.getByTestId('all-workflows-view')).toBeVisible();
			await expect(page.getByTestId('workflow-landing-card')).toHaveCount(2);
		}
	});

	// contract-test: direct surface=gui.web assertions=workspace-shell.start.available-space-cards
	test('project home selects compact cards from space below the banner', async ({ page }) => {
		test.slow();
		for (const size of [{ width: 402, height: 660 }, { width: 1376, height: 700 }, { width: 1376, height: 1032 }]) {
			await page.setViewportSize(size);
			await page.goto('/dev/preview/projects/ProjectsPage?variant=landing&theme=light&chrome=0');
			await waitForComponentPreview(page);
			const card = page.getByTestId('project-landing-card').first();
			await expect(card).toBeVisible();
			const [cardBox, composerBox, bannerBox] = await Promise.all([
				card.boundingBox(), page.getByTestId('project-input-composer').boundingBox(),
				page.getByTestId('projects-daily-inspiration-area').boundingBox()
			]);
			expect(cardBox && composerBox && bannerBox).toBeTruthy();
			expect(cardBox!.y).toBeGreaterThanOrEqual(bannerBox!.y + bannerBox!.height);
			expect(cardBox!.y + cardBox!.height).toBeLessThanOrEqual(composerBox!.y + 1);
			expect(cardBox!.height).toBeLessThan(size.height < 800 ? 120 : 220);
		}
	});

	// contract-test: direct surface=gui.web assertions=workflows-ui.workspace.owned-library-and-templates
	test('empty workflow home still exposes template and owned-workflow browsing', async ({ page }) => {
		test.slow();
		await page.setViewportSize({ width: 402, height: 660 });
		await page.goto('/dev/preview/workflows/WorkflowHomePreviewHarness?variant=empty&theme=light&chrome=0');
		await waitForComponentPreview(page);
		await expect(page.getByTestId('workflow-landing-card')).toHaveCount(0);
		await expect(page.getByTestId('workflows-show-templates')).toBeVisible();
		await page.getByTestId('workflows-show-templates').click();
		await expect(page.getByTestId('workflow-landing-card')).toHaveCount(2);
		await page.getByTestId('workflows-back-to-recent').click();
		await page.getByTestId('workflows-show-all').click();
		await expect(page.getByTestId('all-workflows-view')).toBeVisible();
		await expect(page.getByTestId('workflow-landing-card')).toHaveCount(0);
	});

	for (const size of [{ width: 390, height: 844 }, { width: 1440, height: 900 }]) {
		// contract-test: direct surface=gui.web assertions=workflows-ui.workspace.guest-template-preview
		test(`guest browses the existing workflow template detail without owner actions (${size.width}px)`, async ({ page }, testInfo) => {
			await page.setViewportSize(size);
			const ownedRequests: string[] = [];
			page.on('request', request => {
				if (/\/v1\/workflows(?:\/|\?|$)/.test(new URL(request.url()).pathname)) ownedRequests.push(request.url());
			});
			await page.goto('/dev/preview/workflows/WorkflowHomePreviewHarness?variant=guest&theme=light&chrome=0');
			await waitForComponentPreview(page);
			await expect(page.getByTestId('workflows-start-screen')).toBeVisible();
			await expect(page.getByTestId('all-workflows-view')).toBeVisible();
			await expect(page.getByTestId('workflow-landing-card')).toHaveCount(3);
			await expect(page.getByTestId('workflow-input-composer')).toHaveCount(0);
			await expect(page.getByTestId('workflows-sort')).toHaveCount(0);
			await page.getByTestId('workflow-landing-card').filter({ hasText: 'Daily planning reminder' }).click();
			await expect(page.getByTestId('workflow-detail')).toBeVisible();
			await expect(page.getByTestId('workspace-detail-header')).toBeVisible();
			await expect(page.getByTestId('workspace-detail-title')).toHaveText('Daily planning reminder');
			await expect(page.getByTestId('workflow-template-panel')).toBeVisible();
			const graph = page.getByTestId('workflow-graph-renderer');
			await expect(graph).toHaveAttribute('data-read-only', 'true');
			const nodes = graph.getByTestId('workflow-node-card');
			await expect(nodes).toHaveCount(2);
			await expect(page.getByTestId('toggle-workflow')).toBeDisabled();
			for (const id of ['workflow-input-composer', 'workflow-export', 'delete-workflow', 'run-workflow', 'workflow-share', 'workflow-add-step', 'workflow-node-save', 'workflow-test-action']) {
				await expect(page.getByTestId(id)).toHaveCount(0);
			}
			const firstSummary = nodes.first().getByTestId('workflow-node-summary');
			await firstSummary.click();
			await expect(firstSummary).toHaveAttribute('aria-expanded', 'true');
			const fields = nodes.first().getByTestId('workflow-node-expanded');
			await expect(fields).toBeVisible();
			await page.evaluate(async () => {
				await new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
				await Promise.all(document.getAnimations().filter(animation =>
					animation.effect instanceof KeyframeEffect && animation.effect.pseudoElement?.startsWith('::view-transition')
				).map(animation => animation.finished.catch(() => undefined)));
			});
			const [firstBox, fieldsBox, nextBox] = await Promise.all([
				firstSummary.boundingBox(), fields.boundingBox(), nodes.last().getByTestId('workflow-node-summary').boundingBox(),
			]);
			expect(firstBox && fieldsBox && nextBox).toBeTruthy();
			expect(fieldsBox!.y).toBeGreaterThanOrEqual(firstBox!.y + firstBox!.height - 1);
			expect(nextBox!.y).toBeGreaterThan(fieldsBox!.y + fieldsBox!.height + 8);
			expect(ownedRequests).toEqual([]);
			await page.screenshot({ path: testInfo.outputPath(`guest-workflow-detail-${size.width}.png`) });
		});
	}

});
