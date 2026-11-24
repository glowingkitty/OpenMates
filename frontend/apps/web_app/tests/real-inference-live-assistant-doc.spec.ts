// proof-video: not_required reason=visual_smoke_not_needed (the Playwright video and the named screenshots cover each state)
/* eslint-disable @typescript-eslint/no-require-imports -- spec helpers are CommonJS, shared with other specs */
export {};

/**
 * Real-inference live assistant edit (doc variant) (real_inference CI group, isolated stack
 * with real Gemini, `live_collaboration` flag on).
 *
 * One user has a Project file open in live edit mode in one tab and asks
 * @Gemini-3.8-Flash in a Project chat (second tab) to change part of it while
 * the user keeps typing in another part. The assistant change lands in place
 * ("<mate> is editing here" shows while it works), the user's own text is
 * intact, and one undo removes only the assistant change. Sheet and code
 * variants cover the per-cell suggestion rule and the code editor.
 *
 * Specification: live-collab.assistant.live-edits, live-collab.assistant.human-wins.
 * Run: ci_coordinator.py submit --mode e2e --spec real-inference-live-assistant-doc.spec.ts
 */

import type { Page } from '@playwright/test';

const { test, expect } = require('./helpers/cookie-audit');
const live = require('./helpers/live-collab');

test.afterEach(async () => {
	await live.attachLiveDiagnostics();
});
const { TURN_TIMEOUT, askAssistant, checkpointFile, finish, observeAssistantEditing, startSession } = require('./helpers/live-assistant');

// contract-test: direct surface=gui.web assertions=live-collab.assistant.live-edits,live-collab.assistant.human-wins
test('the assistant rewrites paragraph 2 while the user types in paragraph 1', async ({ page }: { page: Page }) => {
	// Two attempts (test + one retry) must fit the 1200 s CI job cap with stack setup.
	test.setTimeout(500_000);
	const project = await startSession(page, 'document', 'Soup cookbook', 'Pumpkin soup');
	const chat = await page.context().newPage();
	try {
		const doc = page.getByTestId('project-embed-viewer').getByTestId('docs-editor-content');
		await expect(doc).toBeVisible({ timeout: 30_000 });
		await doc.click();
		await page.keyboard.type('Paragraph one stays mine.');
		await page.keyboard.press('Enter');
		await page.keyboard.type('Paragraph two is about onions.');
		await page.keyboard.press('Enter');
		await page.keyboard.type('Paragraph three is about salt.');
		await expect(page.getByTestId('live-header-status')).toHaveAttribute('data-status', 'saved', { timeout: 30_000 });
		await checkpointFile(page, 'document');
		const firstParagraph = doc.getByText('Paragraph one stays mine.', { exact: true });
		const editedParagraph = doc.getByText('Paragraph one stays mine. Typed during the turn.', { exact: true });
		await expect(firstParagraph).toBeVisible();
		await live.shot(page, '01-document-before');

		await observeAssistantEditing(page, async () => {
			await askAssistant(chat, project.projectName, project.projectId,
				'Use project_list_files to find the Project path for the document titled "Pumpkin soup". Read that exact path with project_read_text. Replace "Paragraph two is about onions." with "Paragraph two is about roasted carrots." Use project_update_file with the path and base hash returned by the tools. Copy the complete raw line into the removal line and alter only the sentence in the addition line, preserving the surrounding HTML. If the raw line has no trailing newline, include the unified diff no-newline marker after both lines.');
			// While the assistant works the user keeps typing at the end of paragraph one.
			await firstParagraph.click();
			await page.keyboard.press('End');
			await page.keyboard.type(' Typed during the turn.');
			await expect(editedParagraph).toBeVisible();
		});

		await expect.poll(() => live.editorText(doc), { timeout: TURN_TIMEOUT }).toMatch(/carrot/i);
		const text = await live.editorText(doc);
		expect(text).toContain('Paragraph one stays mine. Typed during the turn.');
		expect(text).toContain('Paragraph three is about salt.');
		expect(text).not.toContain('onions');
		await live.shot(page, '03-document-after-assistant');

		// One undo removes the assistant change and nothing the user typed.
		await editedParagraph.click();
		await page.keyboard.press('ControlOrMeta+z');
		await expect.poll(() => live.editorText(doc), { timeout: 15_000 }).not.toMatch(/carrot/i);
		await expect(editedParagraph).toBeVisible();
		await live.shot(page, '04-document-after-undo');
	} finally {
		await chat.close().catch(() => undefined);
		await finish(page, project.projectId);
	}
});

// contract-test: direct surface=gui.web assertions=live-collab.assistant.live-edits,live-collab.assistant.human-wins
