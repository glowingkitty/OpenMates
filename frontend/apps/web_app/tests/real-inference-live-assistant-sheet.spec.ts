// proof-video: not_required reason=visual_smoke_not_needed (the Playwright video and the named screenshots cover each state)
/* eslint-disable @typescript-eslint/no-require-imports -- spec helpers are CommonJS, shared with other specs */
export {};

/**
 * Real-inference live assistant edit (sheet variant) (real_inference CI group, isolated stack
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
 * Run: ci_coordinator.py submit --mode e2e --spec real-inference-live-assistant-sheet.spec.ts
 */

import type { Page } from '@playwright/test';

const { test, expect } = require('./helpers/cookie-audit');
const live = require('./helpers/live-collab');

test.afterEach(async () => {
	await live.attachLiveDiagnostics();
});
const { TURN_TIMEOUT, askAssistant, checkpointFile, finish, startSession } = require('./helpers/live-assistant');

// contract-test: direct surface=gui.web assertions=live-collab.assistant.live-edits
test('the assistant fills a sheet column and a cell the user edited becomes a suggestion', async ({ page }: { page: Page }) => {
	// Two attempts (test + one retry) must fit the 1200 s CI job cap with stack setup.
	test.setTimeout(500_000);
	const project = await startSession(page, 'sheet', 'Seed stock', 'Seed list');
	const chat = await page.context().newPage();
	try {
		const cell = (id: string) => page.locator(`[data-cell-id="${id}"]`);
		for (const [row, value] of [['r1', 'Tomato'], ['r2', 'Basil'], ['r3', 'Carrot']] as const) {
			await cell(`${row}:c1`).locator('.cell-text').click();
			await page.keyboard.type(value);
			await page.keyboard.press('Enter');
		}
		await checkpointFile(page, 'sheet');
		await live.shot(page, '01-sheet-before');
		await askAssistant(chat, project.projectName, project.projectId,
			'In the sheet "Seed list", fill column B with a typical sowing month for each plant in column A, rows 1 to 3.');
		// The user edits one cell of that column while the assistant works.
		await cell('r2:c2').locator('.cell-text').click();
		await page.keyboard.type('Whenever I like');
		await page.keyboard.press('Enter');
		await expect(cell('r1:c2')).not.toHaveText('', { timeout: TURN_TIMEOUT });
		await expect(cell('r3:c2')).not.toHaveText('', { timeout: TURN_TIMEOUT });
		await expect(cell('r2:c2')).toContainText('Whenever I like');
		await expect(cell('r2:c2').getByTestId('sheet-live-suggestion')).toBeVisible({ timeout: TURN_TIMEOUT });
		await live.shot(page, '02-sheet-suggestion-for-edited-cell');
	} finally {
		await chat.close().catch(() => undefined);
		await finish(page, project.projectId);
	}
});

// contract-test: direct surface=gui.web assertions=live-collab.assistant.live-edits,live-collab.assistant.human-wins
