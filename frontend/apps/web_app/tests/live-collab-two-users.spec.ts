// proof-video: not_required reason=visual_smoke_not_needed (the Playwright video of both browsers and the named screenshots cover each state)
/* eslint-disable @typescript-eslint/no-require-imports -- spec helpers are CommonJS, shared with other specs */
export {};

/**
 * Live collaboration between two real Team members (web, isolated CI stack).
 *
 * The owner creates a Team, invites the member, creates a Team Project with a
 * file, and both open that file in edit mode with the `live_collaboration`
 * flag on. Covers documents, sheets and slide decks: concurrent edits
 * converge, and each person sees the other's name and position.
 *
 * Specification: specifications/features/live-collaboration/specification.yml
 * (live-collab.sync.concurrent-convergence, live-collab.presence.who-and-where,
 * live-collab.access.roles). Run: ci_coordinator.py submit --mode e2e
 * --spec live-collab-two-users.spec.ts
 */

import type { Browser, Locator, Page, TestInfo } from '@playwright/test';

const { test, expect } = require('./helpers/cookie-audit');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getTestAccount } = require('./signup-flow-helpers');
const live = require('./helpers/live-collab');

test.afterEach(async () => {
	await live.attachLiveDiagnostics();
});

test.describe.configure({ mode: 'serial' });

async function begin(page: Page, browser: Browser, kind: 'document' | 'sheet' | 'slides', topic: string, file: string) {
	const owner = getTestAccount(1);
	const member = getTestAccount(2);
	test.skip(!owner.email || !member.email || owner.email === member.email, 'Two isolated account identities required.');
	await skipIfFeaturesDisabled(test, page, ['platform:teams', 'platform:projects']);
	await page.setViewportSize({ width: 1440, height: 1000 });
	await live.enableLiveFlag(page.context());
	await live.loginToTestAccount(page, undefined, undefined, { credentials: owner });
	return live.openLivePair(page, browser, owner, member, kind, topic, file);
}

/** Measure from input dispatch to the other browser's rendered text. */
async function measureRelay(
	receiver: Locator,
	text: string,
	edit: () => Promise<unknown>,
): Promise<number> {
	const target = await receiver.elementHandle();
	if (!target) throw new Error('Remote document editor is missing');
	try {
		const started = performance.now();
		const observed = receiver.page().waitForFunction(
			({ element, text }) => element.textContent?.includes(text),
			{ element: target, text },
			{ timeout: 15_000 },
		).then(async (result) => {
			const elapsed = Math.round(performance.now() - started);
			await result.dispose();
			return elapsed;
		});
		const [elapsed] = await Promise.all([observed, edit()]);
		return elapsed;
	} finally {
		await target.dispose();
	}
}

// contract-test: direct surface=gui.web assertions=live-collab.sync.concurrent-convergence,live-collab.presence.who-and-where,live-collab.access.roles
test('two Team members type in one document and both see the same text and each other', async ({ page, browser }: { page: Page; browser: Browser }, testInfo: TestInfo) => {
	test.setTimeout(420_000);
	const setup = await begin(page, browser, 'document', 'Garden newsletter', 'Spring issue');
	try {
		const a = page.getByTestId('project-embed-viewer').getByTestId('docs-editor-content');
		const b = setup.member.getByTestId('project-embed-viewer').getByTestId('docs-editor-content');
		await expect(a).toBeVisible({ timeout: 30_000 });
		await expect(b).toBeVisible({ timeout: 30_000 });
		await expect(page.getByTestId('live-header-status')).toHaveAttribute('data-status', 'saved', { timeout: 30_000 });
		await live.shot(page, 'owner-document-open');
		await live.shot(setup.member, 'member-document-open');

		await a.click();
		await page.keyboard.type('Tomatoes go in first');
		await expect.poll(() => live.editorText(b), { timeout: 15_000 }).toContain('Tomatoes go in first');
		await page.keyboard.press('Enter');
		await page.keyboard.type('Beans follow later');
		await expect.poll(() => live.editorText(b), { timeout: 15_000 }).toContain('Beans follow later');

		// Both type at the same moment, at different places.
		await a.click();
		await page.keyboard.press('Control+End');
		await page.keyboard.type(' (owner note)');
		await b.click();
		await setup.member.keyboard.press('Control+Home');
		await setup.member.keyboard.type('(member note) ');
		await expect.poll(() => live.editorText(a)).toContain('(owner note)');
		await expect.poll(() => live.editorText(a)).toContain('(member note)');
		await expect.poll(async () => (await live.editorText(a)) === (await live.editorText(b)), { timeout: 15_000 }).toBe(true);
		await live.shot(page, 'owner-document-converged');
		await live.shot(setup.member, 'member-document-converged');

		// Presence: the member's named caret and avatar are visible to the owner.
		await expect(page.getByTestId('project-embed-viewer').locator('.collaboration-carets__label').first()).toBeVisible({ timeout: 15_000 });
		await expect(page.getByTestId('live-peer').first()).toBeVisible();
		await live.shot(page, 'owner-sees-member-caret-and-avatar');
		await testInfo.attach('final-text', { body: await live.editorText(a), contentType: 'text/plain' });

		const shortEditMs: number[] = [];
		await a.click();
		await page.keyboard.press('Control+End');
		for (let index = 0; index < 5; index++) {
			const marker = ` [small edit ${index}]`;
			shortEditMs.push(await measureRelay(b, marker, () => page.keyboard.insertText(marker)));
		}
		const paragraphs = Array.from({ length: 240 }, (_, index) =>
			`Section ${index + 1}. The seed library shares planting dates, harvest notes, and storage instructions with every garden group.`,
		);
		const body = paragraphs.join('\n');
		const paragraphCountBeforePaste = await a.locator('p').count();
		await page.keyboard.press('Enter');
		const largePasteMs = await measureRelay(b, paragraphs[paragraphs.length - 1], () =>
			a.evaluate((editor, text) => {
				const clipboardData = new DataTransfer();
				clipboardData.setData('text/plain', text);
				editor.dispatchEvent(new ClipboardEvent('paste', { clipboardData, bubbles: true, cancelable: true }));
			}, body),
		);
		await expect(b.locator('p')).toHaveCount(paragraphCountBeforePaste + paragraphs.length);
		await b.locator('p').last().click();
		await setup.member.keyboard.press('Control+End');
		const largeEditMs: number[] = [];
		for (let index = 0; index < 5; index++) {
			const marker = ` [large edit ${index}]`;
			largeEditMs.push(await measureRelay(a, marker, () => setup.member.keyboard.insertText(marker)));
		}
		expect(await live.editorText(a)).toBe(await live.editorText(b));
		const performanceReport = { shortEditMs, largePasteMs, largeEditMs, pastedParagraphs: paragraphs.length, pastedBytes: Buffer.byteLength(body) };
		console.log('Live document relay measurements', JSON.stringify(performanceReport));
		await testInfo.attach('document-relay-timing', { body: JSON.stringify(performanceReport), contentType: 'application/json' });
	} finally {
		await live.cleanupTeam(page, setup);
	}
});

// contract-test: direct surface=gui.web assertions=live-collab.sync.concurrent-convergence,live-collab.presence.who-and-where,live-collab.access.roles
test('two Team members edit cells of one sheet and see each other selection', async ({ page, browser }: { page: Page; browser: Browser }) => {
	test.setTimeout(420_000);
	const setup = await begin(page, browser, 'sheet', 'Seed budget', 'Seeds');
	try {
		const cell = (p: Page, id: string) => p.locator(`[data-cell-id="${id}"]`);
		await expect(cell(page, 'r1:c1')).toBeVisible({ timeout: 30_000 });
		await expect(cell(setup.member, 'r1:c1')).toBeVisible({ timeout: 30_000 });
		await live.shot(page, 'owner-sheet-open');

		await cell(page, 'r1:c1').locator('.cell-text').click();
		await page.keyboard.type('Rye flour');
		await page.keyboard.press('Enter');
		await cell(setup.member, 'r2:c1').locator('.cell-text').click();
		await setup.member.keyboard.type('Duck eggs');
		await setup.member.keyboard.press('Enter');
		for (const p of [page, setup.member]) {
			await expect(cell(p, 'r1:c1')).toContainText('Rye flour', { timeout: 15_000 });
			await expect(cell(p, 'r2:c1')).toContainText('Duck eggs', { timeout: 15_000 });
		}
		await live.shot(page, 'owner-sheet-converged');
		await live.shot(setup.member, 'member-sheet-converged');

		// Presence: the member's selected cell is outlined with their name for the owner.
		await cell(setup.member, 'r3:c2').locator('.cell-text').click();
		await expect(cell(page, 'r3:c2').getByTestId('sheet-live-peer')).toBeVisible({ timeout: 15_000 });
		await expect(page.getByTestId('live-peer').first()).toBeVisible();
		await live.shot(page, 'owner-sees-member-selected-cell');
	} finally {
		await live.cleanupTeam(page, setup);
	}
});

// contract-test: direct surface=gui.web assertions=live-collab.sync.concurrent-convergence,live-collab.presence.who-and-where,live-collab.access.roles
test('two Team members edit different elements of one deck and see each other selection', async ({ page, browser }: { page: Page; browser: Browser }) => {
	test.setTimeout(420_000);
	const setup = await begin(page, browser, 'slides', 'Harvest talk', 'Harvest deck');
	try {
		const ownerEditor = page.getByTestId('slides-editor');
		const memberEditor = setup.member.getByTestId('slides-editor');
		await expect(ownerEditor).toHaveAttribute('data-status', 'ready', { timeout: 60_000 });
		await expect(memberEditor).toHaveAttribute('data-status', 'ready', { timeout: 60_000 });
		const elements = (p: Page) => p.getByTestId('slides-editor-canvas').getByTestId('slides-editor-element');
		// A new Project deck starts with its title only. Add the second element
		// through the editor and wait for it to reach the other member.
		await expect(elements(page)).toHaveCount(1);
		await page.getByTestId('slides-editor-add-text').click();
		await expect(elements(page)).toHaveCount(2);
		await expect(elements(setup.member)).toHaveCount(2, { timeout: 15_000 });
		await live.shot(page, 'owner-deck-open');

		await elements(page).first().dblclick();
		await page.getByTestId('slides-editor-text-input').fill('Autumn harvest');
		await page.keyboard.press('Escape');
		await elements(setup.member).nth(1).dblclick();
		await setup.member.getByTestId('slides-editor-text-input').fill('Pumpkins and squash');
		await setup.member.keyboard.press('Escape');
		for (const p of [page, setup.member]) {
			await expect(p.getByTestId('slides-editor-canvas').getByTestId('slide-canvas')).toContainText('Autumn harvest', { timeout: 15_000 });
			await expect(p.getByTestId('slides-editor-canvas').getByTestId('slide-canvas')).toContainText('Pumpkins and squash', { timeout: 15_000 });
		}
		await live.shot(page, 'owner-deck-converged');
		await live.shot(setup.member, 'member-deck-converged');

		await elements(setup.member).first().click();
		await expect(page.getByTestId('slides-editor-peer-selection')).toBeVisible({ timeout: 15_000 });
		await live.shot(page, 'owner-sees-member-selected-element');
	} finally {
		await live.cleanupTeam(page, setup);
	}
});
