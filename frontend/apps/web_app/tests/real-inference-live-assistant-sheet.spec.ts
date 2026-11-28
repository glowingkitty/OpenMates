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
const { deleteActiveChat, focusMessageEditor, loginToTestAccount, sendMessage, startNewChat, waitForChatReady } = require('./helpers/chat-test-helpers');
const { requireRealInference } = require('./helpers/real-inference-guard');
const { createSignupLogger, getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');
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

const baseUrl = process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org';
const geminiFlash = /Gemini 3\.8 Flash/i;
const prompt = [
  'Create an editable spreadsheet called July budget with exactly two columns and two data rows.',
  'Merge the first row across both columns, with July budget as its text.',
  'Set its background to #DBEAFE, its text to black, bold and centered, and its height to 42 px.',
  'Set the column widths to 100 and 110 px.',
  'Use Supplies and one thousand two hundred fifty dollars and fifty cents for the first data row, and Transport and 480 for the second.',
  'Format both amounts in US dollars with two decimal places. Freeze the top row.',
].join(' ');

// contract-test: direct surface=gui.web assertions=rich-sheets.creation.validated-formatting
test('the assistant creates a formatted spreadsheet from a natural-language request', async ({ page }: { page: Page }) => {
  test.setTimeout(180_000);
  requireRealInference('Formatted sheet authoring', baseUrl);
  if (!getTestAccount().email) throw new Error('Real-inference CI requires a provisioned test account.');
  const log = createSignupLogger('REAL_INFERENCE_FORMATTED_SHEET');
  await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
  await loginToTestAccount(page, log);
  await startNewChat(page, log);

  try {
    await waitForChatReady(page);
    await focusMessageEditor(page.getByTestId('message-editor'));
    await page.keyboard.insertText('@Gemini-3.8-Flash');
    const dropdown = page.getByTestId('mention-dropdown');
    await expect(dropdown.getByTestId('mention-result-name').filter({ hasText: geminiFlash }).first()).toBeVisible();
    await page.keyboard.press('Tab');
    await sendMessage(page, ` ${prompt}`, log, undefined, 'formatted-sheet-creation', { preserveExistingContent: true });
    const answer = page.getByTestId('message-assistant').last();
    const sheet = answer.locator(
      '[data-testid="embed-preview"][data-app-id="sheets"]:is([data-status="finished"], [data-status="error"])'
    );
    await expect(sheet).toHaveCount(1, { timeout: 110_000 });
    await expect(sheet).toHaveAttribute('data-status', 'finished');
    const heading = sheet.getByRole('columnheader', { name: 'July budget', exact: true });
    await expect(heading).toHaveAttribute('colspan', '2');
    await expect(heading).toHaveCSS('background-color', 'rgb(219, 234, 254)');
    await expect(heading).toHaveCSS('color', 'rgb(0, 0, 0)');
    await expect(heading).toHaveCSS('text-align', 'center');
    await expect(sheet.getByRole('cell', { name: '$1,250.50', exact: true })).toBeVisible();
    await expect(sheet.getByRole('cell', { name: '$480.00', exact: true })).toBeVisible();
    await expect(answer).not.toContainText('openmates_sheet');
    await expect(answer.getByTestId('generated-by')).toContainText(geminiFlash);
    await sheet.scrollIntoViewIfNeeded();
    await test.info().attach('assistant-sheet-creation-result', {
      body: await sheet.screenshot({ animations: 'disabled' }), contentType: 'image/png',
    });
  } catch (error) {
    await live.shot(page, 'assistant-sheet-creation-error').catch(() => undefined);
    const sendDebug = await page.evaluate(() =>
      (window as Window & { __openmatesLastSendDebug?: unknown }).__openmatesLastSendDebug);
    log('Formatted sheet test failed', { sendDebug });
    throw error;
  } finally {
    await deleteActiveChat(page);
  }
});

// contract-test: direct surface=gui.web assertions=rich-sheets.collaboration.shared-history
test('the assistant formats a cell in an open sheet while the user edits a different cell', async ({ page }: { page: Page }) => {
  test.setTimeout(300_000);
  const project = await startSession(page, 'sheet', 'Market inventory', 'Produce inventory');
  const chat = await page.context().newPage();
  const cell = (id: string) => page.getByTestId('sheet-live-cell').and(page.locator(`[data-cell-id="${id}"]`));
  const editCell = async (id: string, value: string) => {
    await cell(id).getByRole('button').click();
    const input = page.getByTestId('sheet-live-cell-input');
    await input.fill(value);
    await input.press('Enter');
    await expect(cell(id)).toContainText(value);
  };

  try {
    await editCell('r1:c1', 'Tomatoes');
    await checkpointFile(page, 'sheet');
    await live.shot(page, 'sheet-before-assistant-formatting');
    await askAssistant(chat, project.projectName, project.projectId,
      'In the open Produce inventory sheet, make the cell containing Tomatoes bold and give it the pale blue fill #DBEAFE. Keep all existing cell values.');
    await editCell('r2:c2', 'Four crates');
    await expect(cell('r1:c1')).toHaveCSS('background-color', 'rgb(219, 234, 254)', { timeout: TURN_TIMEOUT });
    await expect(cell('r1:c1')).toHaveCSS('font-weight', '700');
    await expect(cell('r1:c1').getByRole('button')).toHaveText('Tomatoes');
    await expect(cell('r2:c2').getByRole('button')).toHaveText('Four crates');
    await expect(chat.getByTestId('message-assistant').last().getByTestId('generated-by')).toContainText(geminiFlash, { timeout: TURN_TIMEOUT });
    await live.shot(page, 'assistant-style-and-user-value-visible-together');
  } catch (error) {
    await live.shot(chat, 'assistant-formatting-project-reply').catch(() => undefined);
    throw error;
  } finally {
    await chat.close();
    await finish(page, project.projectId);
  }
});
