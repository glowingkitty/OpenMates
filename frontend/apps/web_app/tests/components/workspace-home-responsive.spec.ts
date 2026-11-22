// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
import { CATEGORY_GRADIENTS } from '../../../../packages/chatCategoryTheme';

const guestTemplates = [
	{ title: 'Weekly Berlin AI events', category: 'science', icon: 'calendar-days', nodes: 3 },
	{ title: 'Daily Munich apartments', category: 'finance', icon: 'home', nodes: 3 },
	{ title: 'Morning weather', category: 'general_knowledge', icon: 'sun', nodes: 3 },
	{ title: 'Weekly dinner inspiration', category: 'cooking_food', icon: 'utensils', nodes: 3 },
	{ title: 'Website changes', category: 'software_development', icon: 'globe', nodes: 5 },
];

test.describe('Responsive workspace homes', () => {
	// contract-test: supporting surface=gui.web assertions=workflows-ui.workspace.recommendation-led-composition,workflows-ui.workspace.owned-library-and-templates,workspace-shell.start.available-space-cards
	test('composed workflow home keeps cards, composer and browse controls usable at short and narrow sizes', async ({ page }) => {
		test.slow();
		for (const size of [{ width: 402, height: 660 }, { width: 1376, height: 700 }, { width: 1376, height: 1032 }]) {
			await page.setViewportSize(size);
			await page.goto('/dev/preview/workflows/WorkflowHomePreviewHarness?theme=light&chrome=0');
			await waitForComponentPreview(page);
			await expect(page.getByTestId('workflows-daily-inspiration-area')).toHaveCount(0);
			await expect(page.getByTestId('daily-inspiration-banner')).toHaveCount(0);
			await expect(page.getByTestId('workflow-input-textarea')).toHaveValue('');
			await expect(page.getByTestId('workflow-input-textarea')).toBeVisible();
			await expect(page.getByTestId('workflow-landing-card')).toHaveCount(4);
			// TASK-1321: the browse actions are the last tile of the row; nothing browse-related sits below it.
			await expect(page.getByTestId('workflows-workspace-link-row')).toHaveCount(0);
			const actionsTile = page.getByTestId('workflows-start-row-actions');
			await expect(actionsTile.getByTestId('workflows-show-all')).toBeAttached();
			await expect(actionsTile.getByTestId('workflows-show-templates')).toBeAttached();
			await expect(actionsTile.getByTestId('workflows-search')).toBeAttached();
			expect(await actionsTile.evaluate(element => element === element.parentElement?.lastElementChild)).toBe(true);
			await expect(page.getByTestId('workflows-start-suggestions')).toBeVisible();
			expect(await page.getByTestId('workflows-start-suggestions').locator('button').count()).toBeGreaterThanOrEqual(3);
			await expect(page.locator('.workspace-subtitle')).toHaveText('What do you want to automate next?');
			await expect(page.locator('.workspace-continue-label')).toHaveCount(0);
			const firstCard = page.getByTestId('workflow-landing-card').first();
			const cardBox = await firstCard.boundingBox();
			expect(cardBox).not.toBeNull();
			// TASK-1321: the Workflows start screen always uses large cards, on every viewport.
			expect(cardBox!.height).toBeGreaterThanOrEqual(150);
			expect(cardBox!.height).toBeLessThan(220);
			await expect(page.locator('[data-testid="resume-chat-card"]')).toHaveCount(0);
			const welcomeBox = await page.locator('.welcome-text').boundingBox();
			expect(welcomeBox).not.toBeNull();
			expect(Math.abs(cardBox!.y - welcomeBox!.y - welcomeBox!.height - 17.5)).toBeLessThanOrEqual(1);
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

	for (const size of [{ width: 390, height: 844 }, { width: 1280, height: 800 }]) {
		// contract-test: direct surface=gui.web assertions=workspace-shell.start.available-space-cards,daily-inspiration.workspace-start-screens
		test(`project start row shows project inspirations and no banner at ${size.width}px (issue ZSN8N)`, async ({ page }, testInfo) => {
			await page.setViewportSize(size);
			await page.goto('/dev/preview/projects/ProjectsPage?variant=landing&theme=light&chrome=0');
			await waitForComponentPreview(page);
			await expect(page.getByTestId('projects-daily-inspiration-area')).toHaveCount(0);
			await expect(page.getByTestId('daily-inspiration-banner')).toHaveCount(0);
			const row = page.getByTestId('project-mixed-row');
			const card = row.getByTestId('project-landing-card').first();
			await expect(card).toBeVisible();
			const inspiration = row.getByTestId('project-inspiration-card').first();
			await expect(inspiration).toBeAttached();
			const [rowBox, cardBox, composerBox] = await Promise.all([
				row.boundingBox(), card.boundingBox(), page.getByTestId('project-input-composer').boundingBox()
			]);
			expect(rowBox && cardBox && composerBox).toBeTruthy();
			// Same large start-row card as Chats, Apps and Workflows, first card centred, above the composer.
			expect(cardBox!.height).toBeCloseTo(200, 0);
			expect(Math.abs(cardBox!.x + cardBox!.width / 2 - (rowBox!.x + rowBox!.width / 2))).toBeLessThanOrEqual(2);
			expect(cardBox!.y + cardBox!.height).toBeLessThanOrEqual(composerBox!.y + 1);
			expect(await row.locator('[data-testid="project-landing-card"], [data-testid="project-inspiration-card"]').count()).toBeLessThanOrEqual(10);
			// Greeting and row are centred vertically in the room above the composer (Marco, 21 Nov).
			const [headingBox, shellBox] = await Promise.all([
				page.getByTestId('projects-home-heading').boundingBox(),
				page.getByTestId('projects-start-screen').boundingBox()
			]);
			const blockCentre = (headingBox!.y + rowBox!.y + rowBox!.height) / 2;
			const roomCentre = (shellBox!.y + composerBox!.y) / 2;
			expect(Math.abs(blockCentre - roomCentre), `greeting and row centre ${Math.round(blockCentre)}px vs room centre ${Math.round(roomCentre)}px`).toBeLessThanOrEqual(48);
			await testInfo.attach(`project-start-row-${size.width}.png`, { body: await page.screenshot(), contentType: 'image/png' });

			await inspiration.scrollIntoViewIfNeeded();
			const inspirationText = (await inspiration.textContent()) ?? '';
			await inspiration.click();
			const value = await page.getByTestId('project-input-textarea').inputValue();
			expect(value.trim().length).toBeGreaterThan(0);
			expect(inspirationText).toContain(value.trim());
		});
	}

	for (const size of [{ width: 390, height: 844 }, { width: 820, height: 1180 }, { width: 1280, height: 800 }]) {
		// contract-test: direct surface=gui.web assertions=daily-inspiration.start-row-actions
		test(`project start row ends with Show all projects and Search at ${size.width}px (TASK-1321)`, async ({ page }, testInfo) => {
			await page.setViewportSize(size);
			await page.goto('/dev/preview/projects/ProjectsPage?variant=landing&theme=light&chrome=0');
			await waitForComponentPreview(page);
			const row = page.getByTestId('project-mixed-row');
			await expect(row.getByTestId('project-landing-card').first()).toBeVisible();
			// The actions are the last item of the row, after every project and inspiration card.
			const actionsTile = page.getByTestId('projects-start-row-actions');
			await expect(actionsTile).toBeAttached();
			await expect(actionsTile.getByTestId('projects-show-all')).toHaveText(/Show all projects/);
			await expect(actionsTile.getByTestId('projects-search')).toHaveText(/Search/);
			const lastItemIsActions = await page.evaluate(() => {
				const tile = document.querySelector('[data-testid="projects-start-row-actions"]');
				const cards = [...document.querySelectorAll('[data-testid="project-mixed-row"] [data-testid="project-landing-card"], [data-testid="project-mixed-row"] [data-testid="project-inspiration-card"]')];
				if (!tile || cards.length === 0) return false;
				const tileLeft = tile.getBoundingClientRect().left;
				return cards.every((card) => card.getBoundingClientRect().left < tileLeft);
			});
			expect(lastItemIsActions).toBe(true);
			await actionsTile.scrollIntoViewIfNeeded();
			await testInfo.attach(`project-row-actions-${size.width}.png`, { body: await page.screenshot(), contentType: 'image/png' });

			await actionsTile.getByTestId('projects-show-all').click();
			const allView = page.getByTestId('all-projects-view');
			await expect(allView).toBeVisible();
			await expect(allView.getByRole('heading', { name: 'All projects' })).toBeVisible();
			const allCount = await page.getByTestId('all-projects-grid').getByTestId('project-landing-card').count();
			expect(allCount).toBeGreaterThan(0);
			await testInfo.attach(`project-all-${size.width}.png`, { body: await page.screenshot(), contentType: 'image/png' });

			await page.getByTestId('projects-back-to-recent').click();
			await expect(allView).toHaveCount(0);
			await expect(page.getByTestId('projects-start-row-actions')).toBeAttached();

			await page.getByTestId('projects-start-row-actions').getByTestId('projects-search').click();
			const search = page.getByTestId('projects-search-input');
			await expect(search).toBeFocused();
			await search.fill('zz no such project');
			await expect(page.getByTestId('projects-all-items-empty')).toHaveText('No projects match your search.');
			await search.fill('');
			const grid = page.getByTestId('all-projects-grid');
			await expect(grid.getByTestId('project-landing-card')).toHaveCount(allCount);
			// A single search hit stays centred under the heading, and so does the search box.
			const firstTitle = ((await grid.getByTestId('project-landing-card').first().textContent()) ?? '').trim();
			await search.fill(firstTitle);
			const hits = grid.getByTestId('project-landing-card');
			if ((await hits.count()) === 1) {
				const [gridBox, hitBox] = await Promise.all([grid.boundingBox(), hits.first().boundingBox()]);
				expect(Math.abs(hitBox!.x + hitBox!.width / 2 - (gridBox!.x + gridBox!.width / 2))).toBeLessThanOrEqual(2);
			}
			const [viewBox, searchBox] = await Promise.all([allView.boundingBox(), search.boundingBox()]);
			expect(Math.abs(searchBox!.x + searchBox!.width / 2 - (viewBox!.x + viewBox!.width / 2))).toBeLessThanOrEqual(2);
			await testInfo.attach(`project-search-${size.width}.png`, { body: await page.screenshot(), contentType: 'image/png' });
		});
	}

	for (const size of [{ width: 390, height: 844 }, { width: 820, height: 1180 }, { width: 1280, height: 800 }]) {
		// contract-test: direct surface=gui.web assertions=workspace-shell.start.available-space-cards
		test(`workflow start row matches the Chats start row at ${size.width}px`, async ({ page }, testInfo) => {
			await page.setViewportSize(size);
			await page.goto('/dev/preview/workflows/WorkflowHomePreviewHarness?theme=light&chrome=0');
			await waitForComponentPreview(page);
			const row = page.getByTestId('workflow-mixed-row');
			const cards = row.getByTestId('workflow-landing-card');
			expect(await cards.count()).toBeLessThanOrEqual(10);
			const [rowBox, cardBox] = await Promise.all([row.boundingBox(), cards.first().boundingBox()]);
			expect(rowBox && cardBox).toBeTruthy();
			expect(Math.abs(cardBox!.x + cardBox!.width / 2 - (rowBox!.x + rowBox!.width / 2))).toBeLessThanOrEqual(2);
			expect(cardBox!.height).toBeCloseTo(200, 0);
			expect(cardBox!.width).toBeCloseTo(size.width <= 480 ? Math.min(280, 0.76 * size.width) : 300, 0);
			expect(await row.evaluate(element => getComputedStyle(element).justifyContent)).not.toBe('center');
			expect(await page.getByTestId('workflows-start-row-actions').evaluate(element => element === element.parentElement?.lastElementChild)).toBe(true);
			const suggestions = page.getByTestId('workflows-start-suggestions');
			await expect(suggestions).toBeVisible();
			// Suggestions sit directly above the composer, and the greeting and row are centred
			// vertically in the room above them (Marco, 21 Nov).
			const [suggestionsBox, composerBox, headingBox, shellBox] = await Promise.all([
				suggestions.boundingBox(),
				page.getByTestId('workflow-input-composer').boundingBox(),
				page.getByTestId('workflows-home-heading').boundingBox(),
				page.getByTestId('workflows-start-screen').boundingBox()
			]);
			expect(suggestionsBox!.y + suggestionsBox!.height).toBeLessThanOrEqual(composerBox!.y + 1);
			expect(composerBox!.y - (suggestionsBox!.y + suggestionsBox!.height)).toBeLessThanOrEqual(24);
			expect(suggestionsBox!.y).toBeGreaterThan(rowBox!.y + rowBox!.height);
			// Single-line suggestions stay on screen (truncated), never past the pane edge.
			for (const item of await suggestions.getByTestId('follow-up-suggestion-item').all()) {
				const itemBox = await item.boundingBox();
				expect(itemBox!.x).toBeGreaterThanOrEqual(0);
				expect(itemBox!.x + itemBox!.width).toBeLessThanOrEqual(size.width + 1);
			}
			const blockCentre = (headingBox!.y + rowBox!.y + rowBox!.height) / 2;
			const roomCentre = (shellBox!.y + suggestionsBox!.y) / 2;
			expect(Math.abs(blockCentre - roomCentre), `greeting and row centre ${Math.round(blockCentre)}px vs room centre ${Math.round(roomCentre)}px`).toBeLessThanOrEqual(48);
			await testInfo.attach(`workflow-start-row-${size.width}.png`, { body: await page.screenshot(), contentType: 'image/png' });
		});
	}

	for (const size of [{ width: 390, height: 844 }, { width: 1280, height: 800 }]) {
		// contract-test: direct surface=gui.web assertions=workflows-ui.home.prompt-suggestions
		test(`suggestions are as wide as the input, centred on it, lines left-aligned at ${size.width}px`, async ({ page }, testInfo) => {
			await page.setViewportSize(size);
			await page.goto('/dev/preview/workflows/WorkflowHomePreviewHarness?theme=light&chrome=0');
			await waitForComponentPreview(page);
			const suggestions = page.getByTestId('workflows-start-suggestions');
			await expect(suggestions).toBeVisible();
			const [blockBox, composerBox] = await Promise.all([
				suggestions.boundingBox(),
				page.getByTestId('workflow-input-composer').boundingBox()
			]);
			const itemBoxes = await Promise.all(
				(await suggestions.getByTestId('follow-up-suggestion-item').all()).map((item) => item.boundingBox())
			);
			expect(itemBoxes.length).toBeGreaterThan(0);
			// Layout B (Marco, 22 Nov): as wide as the input, centred on it, lines start at the same left edge inside it.
			expect(Math.abs(blockBox!.width - composerBox!.width)).toBeLessThanOrEqual(2);
			expect(Math.abs(blockBox!.x + blockBox!.width / 2 - (composerBox!.x + composerBox!.width / 2))).toBeLessThanOrEqual(2);
			const lefts = itemBoxes.map((box) => box!.x);
			expect(Math.max(...lefts) - Math.min(...lefts)).toBeLessThanOrEqual(1);
			expect(Math.min(...lefts)).toBeGreaterThanOrEqual(composerBox!.x);
			expect(Math.min(...lefts) - composerBox!.x).toBeLessThanOrEqual(32);
			await testInfo.attach(`suggestions-layout-${size.width}.png`, { body: await page.screenshot(), contentType: 'image/png' });
		});
	}

	// contract-test: direct surface=gui.web assertions=workflows-ui.home.prompt-suggestions
	test('tapping a workflow suggestion fills the describe-a-workflow input', async ({ page }) => {
		await page.setViewportSize({ width: 1280, height: 800 });
		await page.goto('/dev/preview/workflows/WorkflowHomePreviewHarness?theme=light&chrome=0');
		await waitForComponentPreview(page);
		await page.getByTestId('workflows-start-suggestions').locator('button').first().click();
		await expect(page.getByTestId('workflow-input-textarea')).toHaveValue('Every morning, summarise new emails from my team');
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
			test.slow();
			await page.setViewportSize(size);
			const ownedRequests: string[] = [];
			page.on('request', request => {
				if (/\/v1\/workflows(?:\/|\?|$)/.test(new URL(request.url()).pathname)) ownedRequests.push(request.url());
			});
			await page.goto('/dev/preview/workflows/WorkflowHomePreviewHarness?variant=guest&theme=light&chrome=0');
			await waitForComponentPreview(page);
			await expect(page.getByTestId('workflows-start-screen')).toBeVisible();
			await expect(page.getByTestId('workflows-daily-inspiration-area')).toHaveCount(0);
			const continuation = page.getByTestId('workflows-workspace-continue');
			await expect(page.locator('.workspace-subtitle')).toHaveText('Explore the workflow automations:');
			await expect(page.locator('.workspace-continue-label')).toHaveCount(0);
			await expect(continuation.getByTestId('workflow-landing-card')).toHaveCount(5);
			await expect(page.getByTestId('all-workflows-view')).toHaveCount(0);
			await expect(page.getByTestId('workflows-show-all')).toHaveCount(0);
			await expect(page.getByTestId('workflow-input-composer')).toBeVisible();
			const signupInput = page.getByTestId('workflow-guest-signup');
			await signupInput.focus();
			await signupInput.press('Enter');
			await expect(page.getByTestId('workflow-signup-dialog')).toBeVisible();
			await page.getByTestId('workflow-signup-dialog').getByRole('button', { name: 'Close' }).click();
			await expect(page.getByTestId('workflows-sort')).toHaveCount(0);
			for (const template of guestTemplates) {
				const card = continuation.getByTestId('workflow-landing-card').filter({ hasText: template.title });
				const colors = CATEGORY_GRADIENTS[template.category];
				expect(await card.evaluate(el => getComputedStyle(el).getPropertyValue('--orb-color-a').trim())).toBe(colors.start);
				expect(await card.evaluate(el => getComputedStyle(el).getPropertyValue('--orb-color-b').trim())).toBe(colors.end);
			}
			await page.getByTestId('workflows-show-templates').click();
			await expect(page.getByTestId('all-workflows-view')).toBeVisible();
			await expect(page.getByTestId('all-workflows-grid').getByTestId('workflow-landing-card')).toHaveCount(5);
			await page.getByTestId('workflows-back-to-recent').click();
			await expect(continuation).toBeVisible();
			const firstCard = continuation.getByTestId('workflow-landing-card').filter({ hasText: 'Weekly Berlin AI events' });
			await firstCard.hover();
			await firstCard.focus();
			await expect(firstCard).toBeFocused();
			await firstCard.press('Enter');
			await expect(page.getByTestId('workflow-detail')).toBeVisible();
			await expect(page.getByTestId('workspace-detail-header')).toBeVisible();
			await expect(page.getByTestId('workspace-detail-title')).toHaveText('Weekly Berlin AI events');
			await expect(page.getByTestId('workspace-detail-header')).toHaveAttribute('data-category', 'science');
			await expect(page.getByTestId('workspace-detail-header')).toHaveAttribute('data-icon', 'calendar-days');
			await expect(page.getByTestId('workflow-template-panel')).toBeVisible();
			const graph = page.getByTestId('workflow-graph-renderer');
			await expect(graph).toHaveAttribute('data-read-only', 'true');
			const nodes = graph.getByTestId('workflow-node-card');
			await expect(nodes).toHaveCount(3);
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
			for (const template of guestTemplates.slice(1)) {
				await test.step(`Read-only ${template.title} uses its category and icon`, async () => {
					await page.getByTestId('workflow-detail-back').click();
					await continuation.getByTestId('workflow-landing-card').filter({ hasText: template.title }).click();
					await expect(page.getByTestId('workspace-detail-title')).toHaveText(template.title);
					await expect(page.getByTestId('workspace-detail-header')).toHaveAttribute('data-category', template.category);
					await expect(page.getByTestId('workspace-detail-header')).toHaveAttribute('data-icon', template.icon);
					await expect(page.getByTestId('workflow-node-card')).toHaveCount(template.nodes);
					await expect(page.getByTestId('workflow-graph-renderer')).toHaveAttribute('data-read-only', 'true');
				});
			}
			expect(ownedRequests).toEqual([]);
		});
	}

});
