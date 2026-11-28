// playwright-account: not_required reason=isolated_component_preview
/**
 * Inline task card states on the bare component preview.
 * Specification: feature.task-inline-embeds@1
 * Assertions: task-inline.presentation.no-raw-ids, task-inline.validation.visible-and-fed-back, task-inline.surfaces.parity
 */
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

const PREVIEW = '/dev/preview/embeds/tasks/TaskEmbedPreview';
// The task icon (static/icons/task.svg): by file name, or inlined by Vite as a data URL with its checklist path.
const isTaskIcon = (mask: string) => /task\.svg/.test(mask) || decodeURIComponent(mask).includes('M12.142 1L5.504 7.677');
/** The card body has no icon of its own and its text starts where the header text starts. */
async function expectTextAlignedWithHeader(page: import('@playwright/test').Page) {
	const card = page.getByTestId('task-embed-card').first();
	await expect(card.locator('[aria-hidden="true"]')).toHaveCount(0);
	const header = await page.getByTestId('embed-result-identity').getByText('Task', { exact: true }).first().boundingBox();
	const title = await page.getByTestId('task-embed-title').first().boundingBox();
	expect(header && title && Math.abs(header.x - title.x) <= 2).toBe(true);
}
const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;

async function open(page: import('@playwright/test').Page, variant: string, width = '900', theme = 'light') {
	const query = new URLSearchParams({ theme, width, chrome: '0' });
	if (variant) query.set('variant', variant);
	await page.goto(`${PREVIEW}?${query}`, { waitUntil: 'domcontentloaded' });
	await waitForComponentPreview(page);
	const card = page.getByTestId('task-embed-card').first();
	await expect(card).toBeVisible();
	return card;
}

test.describe('inline task card', () => {
	// contract-test: supporting surface=gui.web assertions=task-inline.presentation.no-raw-ids,task-inline.surfaces.parity
	test('valid task shows the task icon, title, due date and status, never an id', async ({ page }, testInfo) => {
		const card = await open(page, '');
		await expect(card).toContainText('Buy starter soil and basil seeds');
		await expect(page.getByTestId('task-embed-due-date')).toContainText('Nov 24');
		await expect(page.getByTestId('task-embed-status')).toBeVisible();
		await expect(page.getByTestId('task-embed-validation-errors')).toHaveCount(0);
		await expectTextAlignedWithHeader(page);
		// The header corner shows the task icon (it was a blank square before).
		const cornerMask = await page.locator('[data-testid="embed-preview"] .result-corner > span').first().evaluate((el) => getComputedStyle(el).maskImage || getComputedStyle(el).webkitMaskImage);
		expect(isTaskIcon(cornerMask)).toBe(true);
		expect(await page.locator('body').innerText()).not.toMatch(UUID);
		await testInfo.attach('task-card-valid', { body: await page.locator('body').screenshot(), contentType: 'image/png' });
	});

	// contract-test: supporting surface=gui.web assertions=task-inline.presentation.no-raw-ids,task-inline.surfaces.parity
	test('task without a due date shows no due line', async ({ page }, testInfo) => {
		const card = await open(page, 'validWithoutDueDate');
		const status = await card.getByTestId('task-embed-status').innerText();
		await expect(card.getByText(status, { exact: true })).toHaveCount(1);
		await expect(page.getByTestId('task-embed-due-date')).toHaveCount(0);
		await testInfo.attach('task-card-no-due-date', { body: await page.locator('body').screenshot(), contentType: 'image/png' });
	});

	// contract-test: supporting surface=gui.web assertions=task-inline.presentation.no-raw-ids,task-inline.surfaces.parity
	test('invalid task lists each problem on the card', async ({ page }, testInfo) => {
		const card = await open(page, 'invalid');
		await expect(page.getByTestId('task-embed-validation-errors')).toBeVisible();
		await expect(page.getByTestId('task-embed-validation-error')).toHaveCount(2);
		await expect(page.getByTestId('task-embed-title')).toBeVisible();
		await expectTextAlignedWithHeader(page);
		await expect(card).not.toContainText('T-104');
		const errors = card.getByTestId('task-embed-validation-errors');
		await expect(errors).toContainText('was not found');
		await expect(errors).toContainText('timestamp with a UTC offset');
		const textFits = await errors.evaluate((element) => {
			const viewport = element.getBoundingClientRect();
			const lines = [...element.querySelectorAll('li')].flatMap((item) => {
				const range = document.createRange();
				range.selectNodeContents(item);
				return [...range.getClientRects()];
			});
			return lines.length >= 2 && lines.every((line) =>
				line.top >= viewport.top - 1 && line.bottom <= viewport.bottom + 1 &&
				line.left >= viewport.left - 1 && line.right <= viewport.right + 1);
		});
		expect(textFits, 'the full text of both validation messages fits inside the visible card').toBe(true);
		expect(await page.locator('body').innerText()).not.toMatch(UUID);
		await testInfo.attach('task-card-invalid', { body: await page.locator('body').screenshot(), contentType: 'image/png' });
	});

	// contract-test: supporting surface=gui.web assertions=task-inline.presentation.no-raw-ids,task-inline.surfaces.parity
	test('dark desktop card shows text only, aligned with the header', async ({ page }, testInfo) => {
		await open(page, '', '900', 'dark');
		await expectTextAlignedWithHeader(page);
		await testInfo.attach('task-card-valid-dark', { body: await page.locator('body').screenshot(), contentType: 'image/png' });
	});

	// contract-test: supporting surface=gui.web assertions=task-inline.presentation.no-raw-ids,task-inline.surfaces.parity
	test('long title and dark mobile layout stay inside the card', async ({ page }, testInfo) => {
		await page.setViewportSize({ width: 390, height: 844 });
		const card = await open(page, 'longTitle', '390', 'dark');
		const box = await card.boundingBox();
		await expectTextAlignedWithHeader(page);
		expect(box && box.width <= 390).toBe(true);
		// The long title is clamped to two lines and does not run under the description.
		const title = page.getByTestId('task-embed-title');
		const lineHeight = await title.evaluate((el) => parseFloat(getComputedStyle(el).lineHeight));
		const titleBox = await title.boundingBox();
		expect(titleBox && titleBox.height <= lineHeight * 2 + 1).toBe(true);
		await testInfo.attach('task-card-long-title-dark-mobile', { body: await page.locator('body').screenshot(), contentType: 'image/png' });
	});
});
