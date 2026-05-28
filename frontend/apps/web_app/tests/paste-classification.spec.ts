/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Paste classification regression test.
 * Verifies the composer keeps short prose editable while auto-converting
 * formatted documents, tables, and code to their matching embed types.
 * Runs unauthenticated so the test is fast and exercises preview embeds.
 */

const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl, assertNoMissingTranslations } = require('./signup-flow-helpers');
const { closeFullscreen } = require('./helpers/embed-test-helpers');

async function openUnauthenticatedNewChat(page: any): Promise<any> {
	await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
	await page.waitForLoadState('networkidle');

	const newChatButton = page.getByTestId('new-chat-cta-fullwidth');
	await expect(newChatButton).toBeVisible({ timeout: 15000 });
	await newChatButton.click();

	const editor = page.getByTestId('message-editor');
	await expect(editor).toBeVisible({ timeout: 10000 });
	await editor.click();
	return editor;
}

async function pasteIntoEditor(
	page: any,
	editor: any,
	text: string,
	html?: string,
	vsCodeEditorData?: string
): Promise<void> {
	await editor.click();
	await page.evaluate(
		({ text, html, vsCodeEditorData }: { text: string; html?: string; vsCodeEditorData?: string }) => {
			const editorEl =
				document.querySelector('[data-testid="message-editor"] [contenteditable="true"]') ||
				document.querySelector('[data-testid="message-editor"]');
			if (!editorEl) throw new Error('message-editor not found');

			const clipboardData = new DataTransfer();
			clipboardData.setData('text/plain', text);
			if (html) clipboardData.setData('text/html', html);
			if (vsCodeEditorData) clipboardData.setData('vscode-editor-data', vsCodeEditorData);

			const pasteEvent = new ClipboardEvent('paste', {
				clipboardData,
				bubbles: true,
				cancelable: true
			});
			editorEl.dispatchEvent(pasteEvent);
		},
		{ text, html, vsCodeEditorData }
	);
}

async function clearEditor(page: any, editor: any): Promise<void> {
	const fullscreenOverlay = page.getByTestId('embed-fullscreen-overlay');
	if (await fullscreenOverlay.isVisible({ timeout: 1000 }).catch(() => false)) {
		await closeFullscreen(page, fullscreenOverlay);
	}

	await editor.click();
	await page.keyboard.press('Control+A');
	await page.keyboard.press('Backspace');
	await expect(editor.locator('[data-testid="embed-full-width-wrapper"]')).toHaveCount(0, {
		timeout: 5000
	});
}

async function focusEditorAtEnd(page: any): Promise<void> {
	await page.evaluate(() => {
		const editable = document.querySelector('[data-testid="message-editor"] [contenteditable="true"]');
		if (!(editable instanceof HTMLElement)) throw new Error('contenteditable editor not found');

		const range = document.createRange();
		range.selectNodeContents(editable);
		range.collapse(false);

		const selection = window.getSelection();
		selection?.removeAllRanges();
		selection?.addRange(range);
		editable.focus();
	});
}

test('composer paste classifies text, docs, sheets, and code with Paste as text recovery', async ({
	page
}: {
	page: any;
}) => {
	test.setTimeout(180000);
	await page.setViewportSize({ width: 390, height: 844 });

	const editor = await openUnauthenticatedNewChat(page);

	await pasteIntoEditor(page, editor, 'Liebe Familie,\n\nich freue mich sehr, heute hier zu sein.');
	await expect(editor).toContainText('Liebe Familie', { timeout: 5000 });
	await expect(editor.locator('[data-testid="embed-full-width-wrapper"]')).toHaveCount(0);

	await clearEditor(page, editor);

	await pasteIntoEditor(
		page,
		editor,
		'Quarterly plan\nGoal one',
		'<h1>Quarterly plan</h1><p>Goal one</p>'
	);
	await expect(
		editor.locator('[data-testid="embed-full-width-wrapper"][data-embed-type="docs-doc"]')
	).toBeVisible({ timeout: 10000 });
	const pasteAsTextChip = page.getByTestId('paste-as-text-chip');
	await expect(pasteAsTextChip).toBeVisible({ timeout: 5000 });
	await pasteAsTextChip.click();
	await expect(editor.locator('[data-testid="embed-full-width-wrapper"]')).toHaveCount(0, {
		timeout: 5000
	});
	await expect(editor).toContainText('Quarterly plan', { timeout: 5000 });

	await clearEditor(page, editor);

	await pasteIntoEditor(page, editor, 'Name\tScore\nAda\t10\nGrace\t9');
	await expect(
		editor.locator('[data-testid="embed-full-width-wrapper"][data-embed-type="sheets-sheet"]')
	).toBeVisible({ timeout: 10000 });
	await expect(page.getByTestId('paste-as-text-chip')).toBeVisible({ timeout: 5000 });
	await focusEditorAtEnd(page);
	await page.keyboard.type('x');
	await expect(page.getByTestId('paste-as-text-chip')).toBeHidden({ timeout: 5000 });

	await clearEditor(page, editor);

	await pasteIntoEditor(page, editor, "import { test } from 'vitest';\nconst answer = 42;");
	await expect(
		editor.locator('[data-testid="embed-full-width-wrapper"][data-embed-type="code-code"]')
	).toBeVisible({ timeout: 10000 });
	await expect(page.getByTestId('paste-as-text-chip')).toBeVisible({ timeout: 5000 });

	await assertNoMissingTranslations(page);
});
