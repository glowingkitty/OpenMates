// proof-video: not_required reason=visual_smoke_not_needed (the Playwright video and the named screenshots cover each state)
/* eslint-disable @typescript-eslint/no-require-imports -- spec helpers are CommonJS, shared with other specs */
export {};

/**
 * Real-inference live assistant edit (code variant) (real_inference CI group, isolated stack
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
 * Run: ci_coordinator.py submit --mode e2e --spec real-inference-live-assistant-code.spec.ts
 */

import type { Page } from '@playwright/test';

const { test, expect } = require('./helpers/cookie-audit');
const live = require('./helpers/live-collab');

test.afterEach(async () => {
	await live.attachLiveDiagnostics();
});
const { TURN_TIMEOUT, askAssistant, checkpointFile, finish, observeAssistantEditing, startSession } = require('./helpers/live-assistant');

// contract-test: direct surface=gui.web assertions=live-collab.assistant.live-edits,live-collab.assistant.human-wins
test('the assistant edits a code file while the user types elsewhere in it', async ({ page }: { page: Page }) => {
	// Two attempts (test + one retry) must fit the 1200 s CI job cap with stack setup.
	test.setTimeout(500_000);
	const project = await startSession(page, 'code', 'Weather script', 'greet.py');
	const chat = await page.context().newPage();
	try {
		const code = page.getByTestId('project-embed-viewer').getByTestId('code-editor-textarea');
		await expect(code).toBeVisible({ timeout: 30_000 });
		// CodeMirror mounts before the Worker finishes opening the live item.
		await expect(page.getByTestId('live-header-status')).toHaveAttribute('data-status', 'saved', { timeout: 30_000 });
		const initial = '# user header comment\ndef greet(name):\n    return name\n';
		await code.click();
		await page.keyboard.insertText(initial);
		await checkpointFile(page, 'code');
		await expect.poll(() => live.editorText(code)).toBe(initial.trimEnd());
		await live.shot(page, '01-code-before');
		await observeAssistantEditing(page, async () => {
			await askAssistant(chat, project.projectName, project.projectId,
				'In greet.py, make greet return "Hello, " followed by the name and leave the rest of the file unchanged. Use the path and base hash from project_read_text. The diff needs only one removal line and one addition line for the return statement, with no extra context.');
			await code.getByText('# user header comment', { exact: true }).click();
			await page.keyboard.press('End');
			await page.keyboard.type(' (kept)');
		});
		await expect.poll(() => live.editorText(code), { timeout: TURN_TIMEOUT }).toContain('Hello, ');
		expect(await live.editorText(code)).toContain('# user header comment (kept)');
		await live.shot(page, '03-code-after-assistant');
	} finally {
		await chat.close().catch(() => undefined);
		await finish(page, project.projectId);
	}
});
