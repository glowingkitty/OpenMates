/* eslint-disable @typescript-eslint/no-require-imports -- E2E helpers expose CommonJS exports. */
/**
 * Shared steps for the real-inference live assistant edit specs
 * (real-inference-live-assistant-{doc,sheet,code}.spec.ts).
 */
import type { Page } from '@playwright/test';

const { expect } = require('./cookie-audit');
const { focusMessageEditor, loginToTestAccount, sendMessage, waitForChatReady } = require('./chat-test-helpers');
const { getTestAccount } = require('../signup-flow-helpers');
const { requireRealInference } = require('./real-inference-guard');
const live = require('./live-collab');

const BASE_URL = process.env.PLAYWRIGHT_TEST_BASE_URL || 'http://localhost:5173';
const MODEL_NAME = /Gemini 3\.8 Flash/i;
export const TURN_TIMEOUT = 240_000;

/** Observe the rendered indicator before sending a turn, since a Project commit can clear it within one polling interval. */
export async function observeAssistantEditing(page: Page, runTurn: () => Promise<void>): Promise<void> {
	const probe = await page.getByTestId('live-header-status').evaluateHandle((header) => {
		let label = '';
		const observer = new MutationObserver(() => {
			const indicator = header.querySelector('[data-testid="live-assistant-editing"]');
			if (indicator?.checkVisibility({ visibilityProperty: true })) {
				label = indicator.textContent?.trim() ?? '';
			}
		});
		observer.observe(header, { childList: true, subtree: true, characterData: true });
		return { read: () => label, stop: () => observer.disconnect() };
	});
	try {
		await runTurn();
		await expect.poll(() => probe.evaluate((observer) => observer.read()), {
			message: 'The editor should show the assistant editing indicator during the turn',
			timeout: TURN_TIMEOUT,
		}).toMatch(/is editing here/i);
		const label = await probe.evaluate((observer) => observer.read());
		expect(label).not.toContain('[object Object]');
		await require('./cookie-audit').test.info().attach('assistant-editing-indicator', {
			body: label,
			contentType: 'text/plain',
		});
	} finally {
		await probe.evaluate((observer) => observer.stop()).catch(() => undefined);
		await probe.dispose();
	}
}

export async function startSession(page: Page, kind: 'document' | 'sheet' | 'code', topic: string, file: string) {
	requireRealInference('Live assistant edit', BASE_URL);
	if (!getTestAccount().email) throw new Error('Real-inference CI requires a provisioned test account.');
	await page.setViewportSize({ width: 1440, height: 1000 });
	live.captureLiveDiagnostics(page, require('./cookie-audit').test.info(), 'assistant');
	await live.enableLiveFlag(page.context());
	await loginToTestAccount(page);
	const project = await live.createTeamProjectFile(page, kind, topic, file);
	await live.startLiveEditing(page, kind);
	return project;
}

/** Establish the version the assistant reads, then keep its editor open for the turn. */
export async function checkpointFile(page: Page, kind: 'document' | 'sheet' | 'code'): Promise<void> {
	const saved = page.waitForResponse(
		async (response) => {
			if (response.request().method() !== 'POST' || !new URL(response.url()).pathname.endsWith('/user-revisions')) {
				return false;
			}
			// The first checkpoint on an item without history retries with its base snapshot.
			return response.status() !== 409 || (await response.json()).detail !== 'base_snapshot_required';
		},
		{ timeout: 30_000 },
	);
	await page.getByTestId(live.EDIT_TOGGLE[kind]).click();
	const response = await saved;
	expect(response.ok(), `Checkpoint HTTP status ${response.status()}`).toBe(true);
	expect((await response.json()).status).toBe('committed');
	await live.startLiveEditing(page, kind);
	await expect(page.getByTestId('live-header-status')).toHaveAttribute('data-status', 'saved');
}

/** Ask Gemini in a new chat of the Project (second tab) to edit the open file. */
export async function askAssistant(chat: Page, projectName: string, projectId: string, prompt: string): Promise<void> {
	// The chat tab's console (incl. the send step trail) goes into the attached log too.
	live.captureLiveDiagnostics(chat, require('./cookie-audit').test.info(), 'chat');
	await chat.goto(`/projects/${encodeURIComponent(projectId)}`);
	await expect(chat.getByTestId('project-workspace-header')).toBeVisible({ timeout: 60_000 });
	await chat.getByTestId('project-tab-folders').click();
	await chat.getByTestId('project-folder-create-menu-button').click();
	await chat.getByTestId('project-create-chat').click();
	await waitForChatReady(chat);
	await chat.getByTestId('message-field').click();
	const editor = chat.getByTestId('message-editor');
	const projectMention = editor.locator(`[data-type="generic-mention"][data-mention-type="project"][data-project-id="${projectId}"]`);
	await expect(projectMention).toContainText(projectName, { timeout: 30_000 });
	await focusMessageEditor(editor);
	await chat.keyboard.press('End');
	await chat.keyboard.insertText('@Gemini-3.8-Flash');
	const dropdown = chat.getByTestId('mention-dropdown');
	await expect(dropdown.getByTestId('mention-result-name').filter({ hasText: MODEL_NAME }).first()).toBeVisible({ timeout: 10_000 });
	await chat.keyboard.press('Tab');
	await sendMessage(chat, ` ${prompt}`, undefined, undefined, 'live-assistant-edit', { preserveExistingContent: true });
}

export async function finish(page: Page, projectId: string): Promise<void> {
	await live.cleanupTeam(page, { projectId });
}

// contract-test: direct surface=gui.web assertions=live-collab.assistant.live-edits,live-collab.assistant.human-wins
