// playwright-account: not_required reason=isolated_component_preview
// proof-video: not_required reason=isolated_component_preview
// Selection toolbar over embed cards (production finding: the Highlight /
// Highlight & comment / Explain in new chat toolbar opened over an event card
// after the card was clicked). The read-only message editor turns a click on
// an atom node into a node selection and writes it into the page selection,
// sometimes on a later re-render; that is a click, not selected text.
import { expect, test } from '../helpers/cookie-audit';
import type { Locator, Page, TestInfo } from '@playwright/test';
import { waitForComponentPreview } from '../helpers/component-preview';

const previewUrl = `/dev/preview/ChatMessage?${new URLSearchParams({
	chrome: '0', width: '720', theme: 'light', background: '#f3f3f3', variant: 'eventCardAnswer',
	props: JSON.stringify({ containerWidth: 720 }),
})}`;

async function attach(testInfo: TestInfo, name: string, target: Locator) {
	await testInfo.attach(name, { body: await target.screenshot(), contentType: 'image/png' });
}

/** Write a ProseMirror-style node selection (range wrapping one element) around the card. */
async function selectCardAsNode(page: Page) {
	await page.evaluate(() => {
		const card = document.querySelector('[data-testid="embed-preview-large-node"]')!;
		const parent = card.parentNode!;
		const index = Array.prototype.indexOf.call(parent.childNodes, card);
		const range = document.createRange();
		range.setStart(parent, index);
		range.setEnd(parent, index + 1);
		const selection = window.getSelection()!;
		selection.removeAllRanges();
		selection.addRange(range);
	});
}

async function selectText(page: Page, text: string, from: 'start' | 'card-crossing') {
	await page.evaluate(({ text, from }) => {
		const body = document.querySelector('[data-testid="mate-message-content"]')!;
		const paragraphs = Array.from(body.querySelectorAll('p')).filter((p) => p.textContent?.trim());
		const first = paragraphs[0].firstChild!;
		const range = document.createRange();
		const start = first.textContent!.indexOf(text);
		range.setStart(first, start);
		if (from === 'start') {
			range.setEnd(first, start + text.length);
		} else {
			const last = paragraphs[paragraphs.length - 1].firstChild!;
			range.setEnd(last, 5);
		}
		const selection = window.getSelection()!;
		selection.removeAllRanges();
		selection.addRange(range);
	}, { text, from });
}

// contract-test: direct surface=gui.web assertions=message-highlights.selection-toolbar
test('selection toolbar stays closed for a clicked event card and opens for selected answer text', async ({ page }, testInfo) => {
	test.setTimeout(60_000);
	await page.setViewportSize({ width: 900, height: 900 });
	await page.goto(previewUrl);
	const canvas = await waitForComponentPreview(page);
	const content = canvas.getByTestId('mate-message-content');
	const card = content.getByTestId('embed-preview-large-node');
	const toolbar = page.getByTestId('message-selection-toolbar');
	await expect(content).toContainText('The next edition takes place');
	await expect(card).toBeVisible();
	await expect(card).toContainText('Local founders Gathering');

	await test.step('clicking the card dismisses the toolbar', async () => {
		await selectText(page, 'next edition', 'start');
		await expect(toolbar).toBeVisible();
		await card.click();
		await expect(toolbar).toBeHidden();
		await attach(testInfo, '1-after-card-click', canvas);
	});

	await test.step('a node selection of the card (as the editor writes it later) dismisses the toolbar', async () => {
		await selectText(page, 'next edition', 'start');
		await expect(toolbar).toBeVisible();
		await selectCardAsNode(page);
		await expect(toolbar).toBeHidden();
		await attach(testInfo, '2-card-node-selection', canvas);
	});

	await test.step('selected answer text opens the toolbar above it', async () => {
		await selectText(page, 'next edition', 'start');
		await expect(toolbar).toBeVisible();
		await expect(toolbar.getByTestId('message-selection-highlight')).toBeVisible();
		const toolbarBox = (await toolbar.boundingBox())!;
		const cardBox = (await card.boundingBox())!;
		expect(toolbarBox.y + toolbarBox.height, 'toolbar sits above the text, not over the card').toBeLessThanOrEqual(cardBox.y);
		await attach(testInfo, '3-text-selection-toolbar', canvas);
	});

	await test.step('a selection running across the card still opens the toolbar for the text', async () => {
		await page.evaluate(() => window.getSelection()?.removeAllRanges());
		await expect(toolbar).toBeHidden();
		await selectText(page, 'startup hub', 'card-crossing');
		await expect(toolbar).toBeVisible();
		await attach(testInfo, '4-selection-across-card', canvas);
	});
});
