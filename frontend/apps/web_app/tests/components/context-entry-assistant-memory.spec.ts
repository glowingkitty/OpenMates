// proof-video: not_required reason=visual_smoke_not_needed
/**
 * Focused component contract of the assistant-written Memory notice
 * (ContextEntryEventNotice with source: assistant): created and updated labels with
 * Open and Undo, the persisted undone state, a successful Undo, and the refused Undo
 * of a Memory edited since ("rule_changed").
 * Plan: docs/plans/assistant-memory-writes/plan.yml (TASK-3)
 */
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview

const BASE = 'theme=light&background=%23dbeafe&chrome=0&width=680';

async function openVariant(page: any, variant: string) {
	await page.setViewportSize({ width: 1280, height: 900 });
	await page.goto(`/dev/preview/ContextEntryEventNotice?${BASE}&variant=${variant}`);
	await waitForComponentPreview(page);
	return page.getByTestId('context-entry-event');
}

async function attach(testInfo: any, name: string, notice: any) {
	await testInfo.attach(name, { body: await notice.screenshot(), contentType: 'image/png' });
}

// contract-test: supporting surface=gui.web assertions=app-memories.lifecycle.encrypted-crud
test('assistant-created memory notice offers Open and Undo, and Undo marks it undone', async ({ page }, testInfo) => {
	const notice = await openVariant(page, 'assistant_created');
	await expect(notice).toHaveAttribute('data-source', 'assistant');
	await expect(notice.getByTestId('context-entry-event-label')).toHaveText('The assistant saved a memory: Favourite test colour');
	await expect(notice.getByTestId('context-entry-event-open')).toBeEnabled();
	await expect(notice.getByTestId('context-entry-event-undo')).toHaveText('Undo');
	await expect(notice.getByTestId('context-entry-event-undo')).toBeEnabled();
	await attach(testInfo, 'assistant-created', notice);

	await notice.getByTestId('context-entry-event-undo').click();
	await expect(notice).toHaveAttribute('data-undone', 'true');
	await expect(notice.getByTestId('context-entry-event-undone')).toHaveText('Undone');
	await expect(notice.getByTestId('context-entry-event-undo')).toHaveCount(0);
	// The deleted Memory is not reported as "No longer exists" next to "Undone".
	await expect(notice.getByTestId('context-entry-event-missing')).toHaveCount(0);
	await attach(testInfo, 'assistant-created-after-undo', notice);
});

// contract-test: supporting surface=gui.web assertions=app-memories.lifecycle.encrypted-crud
test('assistant-updated memory notice reads as an update', async ({ page }, testInfo) => {
	const notice = await openVariant(page, 'assistant_updated');
	await expect(notice.getByTestId('context-entry-event-label')).toHaveText('The assistant updated a memory: Favourite test colour');
	await expect(notice.getByTestId('context-entry-event-undo')).toBeVisible();
	await attach(testInfo, 'assistant-updated', notice);
});

// contract-test: supporting surface=gui.web assertions=app-memories.lifecycle.encrypted-crud
test('a persisted undone marker shows the undone state without Undo', async ({ page }, testInfo) => {
	const notice = await openVariant(page, 'assistant_undone');
	await expect(notice).toHaveAttribute('data-undone', 'true');
	await expect(notice.getByTestId('context-entry-event-undone')).toHaveText('Undone');
	await expect(notice.getByTestId('context-entry-event-undo')).toHaveCount(0);
	await expect(notice.getByTestId('context-entry-event-missing')).toHaveCount(0);
	await attach(testInfo, 'assistant-undone', notice);
});

// contract-test: supporting surface=gui.web assertions=app-memories.lifecycle.encrypted-crud
test('undo of a memory edited since is refused with a visible reason', async ({ page }, testInfo) => {
	const notice = await openVariant(page, 'assistant_undo_changed');
	await notice.getByTestId('context-entry-event-undo').click();
	const error = notice.getByTestId('context-entry-event-undo-error');
	await expect(error).toHaveText('This memory was edited since; undo is not available');
	await expect(error).toHaveAttribute('data-error', 'changed');
	await expect(notice.getByTestId('context-entry-event-undo')).toHaveCount(0);
	await expect(notice).toHaveAttribute('data-undone', 'false');
	await attach(testInfo, 'assistant-undo-changed', notice);
});

// contract-test: supporting surface=gui.web assertions=app-memories.lifecycle.encrypted-crud
test('user-saved memory notice keeps its title row and has no Undo', async ({ page }) => {
	await page.setViewportSize({ width: 1280, height: 900 });
	await page.goto(`/dev/preview/ContextEntryEventNotice?${BASE}`);
	await waitForComponentPreview(page);
	const notice = page.getByTestId('context-entry-event');
	await expect(notice).toHaveAttribute('data-source', 'user');
	await expect(notice.getByTestId('context-entry-event-label')).toHaveText('Conference day pacing');
	await expect(notice.getByTestId('context-entry-event-open')).toHaveAttribute('aria-label', 'Memory created: Conference day pacing');
	await expect(notice.getByTestId('context-entry-event-undo')).toHaveCount(0);
});
