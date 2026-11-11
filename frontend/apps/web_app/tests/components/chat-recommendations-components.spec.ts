// proof-video: not_required reason=visual_smoke_not_needed
/**
 * Focused component contract for chat Recommendations (replaced the quick tips card):
 * RecommendationsCard (category gradient, one embed preview at a time, Create/Update below
 * it, pager, busy state, no dismiss control),
 * ContextEntryEventNotice (saved-entry chat history notice with deep link) and the
 * WorkflowChatPaneLayout shell of the regular workflow editor opened from a chat
 * (side and fullscreen layouts, authoring/draft/saved/error states).
 * Plan: docs/plans/chat-recommendations/plan.yml
 */
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview

const BASE = 'theme=light&background=%23dbeafe&chrome=0';

async function openPreview(page: any, path: string, query: string, viewport = { width: 1280, height: 900 }) {
	await page.setViewportSize(viewport);
	await page.goto(`/dev/preview/${path}?${BASE}&${query}`);
	await waitForComponentPreview(page);
}

async function expectInside(page: any, outerTestId: string, innerTestId: string) {
	const outer = await page.getByTestId(outerTestId).first().boundingBox();
	const inner = await page.getByTestId(innerTestId).first().boundingBox();
	expect(outer && inner).toBeTruthy();
	expect(inner!.x).toBeGreaterThanOrEqual(outer!.x - 1);
	expect(inner!.x + inner!.width).toBeLessThanOrEqual(outer!.x + outer!.width + 1);
}

for (const width of [390, 680]) {
	// contract-test: direct surface=gui.web assertions=app-memories.suggestions.post-processor
	test(`recommendations card pages through three items one at a time at ${width}px`, async ({ page }) => {
		await openPreview(page, 'RecommendationsCard', `width=${width}`);
		const card = page.getByTestId('recommendations-card');
		await expect(card).toBeVisible();
		await expect(card).toHaveAttribute('data-count', '3');
		await expect(card.getByTestId('recommendation-item')).toHaveCount(1);
		await expect(card.getByTestId('recommendation-dot')).toHaveCount(3);
		// Call-to-action heading names the kind and whether it is new or an update.
		await expect(card.getByTestId('recommendation-heading')).toHaveText('New memory recommended');
		// The type is named once, in the embed header (no duplicate label in the body).
		await expect(card.getByTestId('embed-preview')).toContainText('Memory');
		await expect(card.getByTestId('recommendation-embed')).not.toContainText('Memory');
		await expect(card.getByTestId('recommendation-title')).toHaveText('Conference day pacing');
		await expect(card.getByTestId('recommendation-summary')).toContainText('hallway conversations');
		await expect(card.getByTestId('recommendation-action')).toHaveText('Create');
		// No dismiss/close control: saving an entry or the next turn replaces recommendations.
		await expect(card.getByTestId('recommendation-dismiss')).toHaveCount(0);
		// Colored chat-category gradient like the former quick tips card.
		expect(await card.evaluate((node) => getComputedStyle(node).backgroundImage)).toContain('linear-gradient');
		// The recommendation is an embed preview card; Create sits below it.
		const embed = card.getByTestId('recommendation-embed');
		await expect(embed).toHaveAttribute('data-kind', 'memory');
		const embedBox = await embed.boundingBox();
		const actionBox = await card.getByTestId('recommendation-action').boundingBox();
		expect(actionBox!.y).toBeGreaterThanOrEqual(embedBox!.y + embedBox!.height - 1);
		for (const id of ['recommendation-embed', 'recommendation-action', 'recommendation-next', 'recommendation-previous']) {
			await expectInside(page, 'recommendations-card', id);
		}
		const cardBox = await card.boundingBox();
		expect(cardBox!.width).toBeLessThanOrEqual(width + 1);
		// The heading sits above the embed preview inside the colored container.
		const headingBox = await card.getByTestId('recommendation-heading').boundingBox();
		expect(headingBox!.y + headingBox!.height).toBeLessThanOrEqual(embedBox!.y + 1);
		// A click on the embed preview opens the same draft as the Create button.
		const opened = () => page.evaluate(() => (document.body.dataset.recommendationOpened ?? '').split(':')[0]);
		await embed.click();
		await expect.poll(opened).toBe('preview-rec-1');
		await page.evaluate(() => { delete document.body.dataset.recommendationOpened; });
		await card.getByTestId('recommendation-action').click();
		await expect.poll(opened).toBe('preview-rec-1');

		await card.getByTestId('recommendation-next').click();
		await expect(card).toHaveAttribute('data-index', '1');
		await expect(card.getByTestId('recommendation-heading')).toHaveText('New workflow recommended');
		await expect(card.getByTestId('embed-preview')).toContainText('Workflow');
		await expect(card.getByTestId('recommendation-embed')).toHaveAttribute('data-kind', 'workflow');
		await expect(card.getByTestId('recommendation-title')).toHaveText('Weekly open source conference digest');
		await expect(card.getByTestId('recommendation-dot').nth(1)).toHaveAttribute('aria-current', 'true');

		await card.getByTestId('recommendation-next').click();
		await expect(card.getByTestId('recommendation-heading')).toHaveText('Memory update recommended');
		await expect(card.getByTestId('recommendation-action')).toHaveText('Update');
		await expect(card.getByTestId('recommendation-item')).toHaveAttribute('data-action', 'update');

		await card.getByTestId('recommendation-next').click();
		await expect(card).toHaveAttribute('data-index', '0');
		await card.getByTestId('recommendation-previous').click();
		await expect(card).toHaveAttribute('data-index', '2');
		await card.getByTestId('recommendation-dot').first().click();
		await expect(card.getByTestId('recommendation-title')).toHaveText('Conference day pacing');

		await card.getByTestId('recommendation-next').focus();
		await page.keyboard.press('Enter');
		await expect(card).toHaveAttribute('data-index', '1');
	});
}

// contract-test: direct surface=gui.web assertions=app-memories.suggestions.post-processor
test('recommendations card hides the pager for one item and shows six dots for six', async ({ page }) => {
	await openPreview(page, 'RecommendationsCard', 'width=680&variant=single');
	const card = page.getByTestId('recommendations-card');
	await expect(card.getByTestId('recommendation-dot')).toHaveCount(1);
	await expect(card.getByTestId('recommendation-next')).toHaveCount(0);
	await expect(card.getByTestId('recommendation-previous')).toHaveCount(0);

	await openPreview(page, 'RecommendationsCard', 'width=680&variant=six');
	await expect(page.getByTestId('recommendation-dot')).toHaveCount(6);

	// Without a chat category the card falls back to the primary brand gradient token.
	await openPreview(page, 'RecommendationsCard', 'width=680&variant=no_category');
	await expect(page.getByTestId('recommendation-embed')).toBeVisible();
	await expect(page.getByTestId('recommendations-card')).toHaveAttribute('style', /var\(--color-primary\)/);
	expect(await page.getByTestId('recommendations-card').evaluate((node) => getComputedStyle(node).backgroundImage)).toContain('gradient');
});

// contract-test: direct surface=gui.web assertions=app-memories.suggestions.post-processor
test('recommendations card disables the action while a draft is prepared and shows status text', async ({ page }) => {
	await openPreview(page, 'RecommendationsCard', 'width=680&variant=busy');
	const card = page.getByTestId('recommendations-card');
	await expect(card.getByTestId('recommendation-action')).toBeDisabled();
	await expect(card.getByTestId('recommendation-status')).toHaveText('Preparing draft…');

	await openPreview(page, 'RecommendationsCard', 'width=680&variant=up_to_date');
	await expect(page.getByTestId('recommendation-status')).toHaveText('This memory is already up to date.');
	await expect(page.getByTestId('recommendation-action')).toBeEnabled();
});

// contract-test: direct surface=gui.web assertions=app-memories.suggestions.post-processor
test('saved-entry notice labels kind and action and links to the entry', async ({ page }) => {
	await openPreview(page, 'ContextEntryEventNotice', 'width=680');
	const notice = page.getByTestId('context-entry-event');
	await expect(notice.getByTestId('context-entry-event-label')).toHaveText('Conference day pacing');
	await expect(notice.getByTestId('context-entry-event-open')).toBeEnabled();
	await expect(notice.getByTestId('context-entry-event-open')).toHaveAttribute('aria-label', 'Memory created: Conference day pacing');
	await expect(notice.getByTestId('context-entry-event-open')).not.toContainText('Open');

	await openPreview(page, 'ContextEntryEventNotice', 'width=680&variant=memory_updated');
	await expect(page.getByTestId('context-entry-event-label')).toHaveText('Conference day pacing');
	await expect(page.getByTestId('context-entry-event-open')).toHaveAttribute('aria-label', 'Memory updated: Conference day pacing');

	await openPreview(page, 'ContextEntryEventNotice', 'width=680&variant=workflow_updated');
	await expect(page.getByTestId('context-entry-event-label')).toHaveText('Weekly open source conference digest');
	await expect(page.getByTestId('context-entry-event-open')).toHaveAttribute('aria-label', 'Workflow updated: Weekly open source conference digest');
	await expect(page.getByTestId('context-entry-event-open')).toHaveAttribute('href', /workflow-id=preview-workflow/);

	await openPreview(page, 'ContextEntryEventNotice', 'width=680&variant=missing');
	await expect(page.getByTestId('context-entry-event-missing')).toHaveText('No longer exists');
	await expect(page.getByTestId('context-entry-event-open')).toHaveCount(0);
});

/** Resolve with the detail of the next window event of this name. */
function nextPreviewEvent(page: any, name: string): Promise<unknown> {
	return page.evaluate((eventName: string) => new Promise((resolve) =>
		window.addEventListener(eventName, (event) => resolve((event as CustomEvent).detail ?? null), { once: true })), name);
}

// contract-test: direct surface=gui.web assertions=app-memories.suggestions.post-processor,workflows-ui.authoring.composer-and-preview
test('chat workflow editor shows the regular draft editor with save, then authoring, saved and error states', async ({ page }, testInfo) => {
	await openPreview(page, 'workflows/WorkflowChatPaneLayout', 'width=640');
	const pane = page.getByTestId('workflow-chat-pane');
	await expect(pane).toHaveAttribute('data-layout', 'side');
	await expect(pane).toHaveAttribute('data-state', 'draft');
	// The regular workflow header and editor, not a chat-only shell.
	await expect(pane.getByTestId('workspace-detail-header')).toHaveAttribute('data-detail-state', 'draft');
	await expect(pane.getByTestId('workflow-draft-title-input')).toHaveValue('Weekly school weather brief');
	await expect(pane.getByTestId('workflow-save-draft')).toBeEnabled();
	await expect(pane.getByTestId('toggle-workflow')).toBeDisabled();
	await expect(pane.getByTestId('workflow-editor')).toBeVisible();
	await expect(pane).not.toContainText('Not saved yet');
	await expectInside(page, 'workflow-chat-pane', 'workflow-save-draft');
	await expectInside(page, 'workflow-chat-pane', 'workflow-detail-back');
	await testInfo.attach('workflow-chat-pane-draft', { body: await pane.screenshot(), contentType: 'image/png' });
	const saved = nextPreviewEvent(page, 'workflow-preview-save-draft');
	await pane.getByTestId('workflow-save-draft').click();
	expect(await saved).toEqual({ title: 'Weekly school weather brief' });
	const closed = nextPreviewEvent(page, 'workflow-preview-close');
	await pane.getByTestId('workflow-detail-back').click();
	await closed;

	await openPreview(page, 'workflows/WorkflowChatPaneLayout', 'width=640&variant=authoring');
	await expect(page.getByTestId('workflow-chat-pane')).toHaveAttribute('data-state', 'authoring');
	await expect(page.getByTestId('workspace-detail-header')).toHaveAttribute('data-detail-state', 'provisional');
	await expect(page.getByTestId('workflow-ai-pending-preview')).toBeVisible();
	await expect(page.getByTestId('workflow-ai-accepted-nodes')).toBeVisible();
	await expect(page.getByTestId('workflow-ai-stop')).toBeEnabled();
	await expect(page.getByTestId('workflow-save-draft')).toHaveCount(0);
	await testInfo.attach('workflow-chat-pane-authoring', { body: await page.getByTestId('workflow-chat-pane').screenshot(), contentType: 'image/png' });
	const stopped = nextPreviewEvent(page, 'workflow-preview-stop');
	await page.getByTestId('workflow-ai-stop').click();
	await stopped;

	await openPreview(page, 'workflows/WorkflowChatPaneLayout', 'width=640&variant=saved');
	await expect(page.getByTestId('workflow-chat-pane')).toHaveAttribute('data-state', 'saved');
	await expect(page.getByTestId('workspace-detail-title')).toHaveText('Weekly school weather brief');
	await expect(page.getByTestId('workflow-enabled-state')).toHaveAttribute('data-enabled', 'false');
	await expect(page.getByTestId('toggle-workflow')).toBeVisible();
	await expect(page.getByTestId('workflow-view-tabs')).toBeVisible();
	await expect(page.getByTestId('workflow-template-test-now')).toBeVisible();
	await expect(page.getByTestId('workflow-save-draft')).toHaveCount(0);
	await expect(page.getByTestId('workflow-chat-pane')).not.toContainText('Saved to your workflows');
	await testInfo.attach('workflow-chat-pane-saved', { body: await page.getByTestId('workflow-chat-pane').screenshot(), contentType: 'image/png' });

	await openPreview(page, 'workflows/WorkflowChatPaneLayout', 'width=640&variant=error');
	await expect(page.getByTestId('workflow-chat-pane-error')).toContainText('could not be generated');
	await expect(page.getByTestId('workflow-chat-pane-retry')).toHaveText('Try again');
	await expect(page.getByTestId('workflow-detail-back')).toBeVisible();
	const retried = nextPreviewEvent(page, 'workflow-preview-retry');
	await page.getByTestId('workflow-chat-pane-retry').click();
	await retried;
});

// contract-test: direct surface=gui.web assertions=workflows-ui.authoring.composer-and-preview
test('chat workflow editor fullscreen layout fits a phone viewport', async ({ page }, testInfo) => {
	await openPreview(page, 'workflows/WorkflowChatPaneLayout', 'width=390&variant=fullscreen', { width: 390, height: 844 });
	const pane = page.getByTestId('workflow-chat-pane');
	await expect(pane).toHaveAttribute('data-layout', 'fullscreen');
	const box = await pane.boundingBox();
	expect(box!.width).toBeLessThanOrEqual(391);
	await expectInside(page, 'workflow-chat-pane', 'workflow-save-draft');
	await expectInside(page, 'workflow-chat-pane', 'workflow-detail-back');
	await expectInside(page, 'workflow-chat-pane', 'workflow-draft-title-input');
	// The editable name keeps a readable width on a phone.
	const titleBox = await pane.getByTestId('workflow-draft-title-input').boundingBox();
	expect(titleBox!.width).toBeGreaterThanOrEqual(120);
	await testInfo.attach('workflow-chat-pane-phone', { body: await pane.screenshot(), contentType: 'image/png' });
});
