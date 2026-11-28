// playwright-account: required reason=signed_in_start_screens_layout
/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Start screens layout (TASK-1321): Chats, Apps, Workflows and (signed in) Projects share one start-screen layout
 * for signed-out visitors and signed-in users at phone, tablet and desktop widths.
 *
 * Each screen: no Daily Inspiration banner; a greeting with one short call to action; one
 * row of at most ten large cards whose first card is horizontally centred; the browse
 * actions as the last item of the row; suggestions below the row (Chats, Workflows).
 * A named screenshot of every state is attached for review.
 *
 * Suggestions are always one line (cut with an ellipsis), and on Chats the greeting never sits
 * under the top buttons row, also on a short phone screen (issue CCFK8).
 *
 * Assertions: daily-inspiration.start-row-actions, daily-inspiration.start-row-suggestions,
 * workspace-shell.start.available-space-cards, workflows-ui.home.prompt-suggestions.
 */

const { test, expect } = require('./helpers/cookie-audit');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const {
	assertNoMissingTranslations,
	createSignupLogger,
	createStepScreenshotter,
	getE2EDebugUrl,
	getTestAccount
} = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

const L = ['web-laptop'];

const START_SCREENS_PROOF = defineVideoProof({
	id: 'start-screens-layout',
	title: 'Chats, Apps, Workflows and Projects start screens share one layout',
	surface: 'web',
	devices: L,
	domain: 'app.dev.openmates.org',
	transcript: [
		{ id: 'chats', text: 'Chats: greeting, a row of large cards ending with Show all and Search, suggestions below.', checkpoint: 'chats-start', devices: L },
		{ id: 'apps', text: 'Apps: "Explore the apps OpenMates can use" above the same row, ending with Show all apps and Search.', checkpoint: 'apps-start', devices: L },
		{ id: 'workflows', text: 'Workflows: the same row ending with Show templates, workflow prompt suggestions below.', checkpoint: 'workflows-start', devices: L },
		{ id: 'projects', text: 'Projects: no banner; projects and project inspirations in the same row, ending with Show all projects and Search.', checkpoint: 'projects-start', devices: L },
		{ id: 'suggestion', text: 'Tapping a workflow suggestion fills the describe-a-workflow composer.', checkpoint: 'workflow-suggestion-filled', devices: L }
	],
	assertions: [
		{ id: 'start.chats_layout', checkpoint: 'chats-start', visual: 'No banner; the row ends with the Show all and Search tile; three suggestions sit below it.', devices: L },
		{ id: 'start.apps_layout', checkpoint: 'apps-start', visual: 'The Apps heading reads "Explore the apps OpenMates can use"; app cards have the chat card size.', devices: L },
		{ id: 'start.workflows_layout', checkpoint: 'workflows-start', visual: 'The Workflows row ends with Show templates; prompt suggestions sit below it.', devices: L },
		{ id: 'start.projects_layout', checkpoint: 'projects-start', visual: 'The Projects row has no banner above it and ends with Show all projects and Search.', devices: L },
		{ id: 'start.workflow_suggestion', checkpoint: 'workflow-suggestion-filled', visual: 'The describe-a-workflow composer contains the tapped suggestion.', devices: L }
	],
	tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 }
});

const VIEWPORTS = [
	{ name: 'phone', width: 390, height: 844 },
	{ name: 'tablet', width: 820, height: 1180 },
	{ name: 'desktop', width: 1280, height: 800 }
];

/** iPhone Safari with its toolbar showing (issue CCFK8): the welcome block is taller than the pane. */
const SHORT_PHONE = { name: 'short-phone', width: 390, height: 631 };

type Screen = {
	name: 'chats' | 'apps' | 'workflows' | 'projects';
	path: string;
	actionsTestId: string;
	suggestionsTestId: string | null;
	headingTestId: string;
	subtitleText: RegExp | null;
	actionIds: (signedIn: boolean) => string[];
};

/** Header switcher value / tab href of each start screen. */
const SCREEN_HREFS: Record<Screen['name'], string> = { chats: '/', apps: '/#apps', workflows: '/#workflows', projects: '/#projects' };

const SCREENS: Screen[] = [
	{
		name: 'chats',
		path: '/',
		actionsTestId: 'start-row-actions',
		suggestionsTestId: 'start-screen-suggestions',
		headingTestId: 'chat-welcome-heading',
		subtitleText: null,
		actionIds: (signedIn) =>
			signedIn ? ['chat-show-all', 'chat-search'] : ['guest-interest-select-interests', 'guest-show-all-examples']
	},
	{
		name: 'apps',
		path: '/#apps',
		actionsTestId: 'apps-start-row-actions',
		suggestionsTestId: null,
		headingTestId: 'apps-home-heading',
		subtitleText: /Explore the apps OpenMates can use/,
		actionIds: () => ['apps-show-all', 'apps-search']
	},
	{
		name: 'workflows',
		path: '/workflows',
		actionsTestId: 'workflows-start-row-actions',
		suggestionsTestId: 'workflows-start-suggestions',
		headingTestId: 'workflows-home-heading',
		subtitleText: null,
		actionIds: () => ['workflows-show-templates']
	}
];

/** Projects needs an account, so it is checked in the signed-in pass only (TASK-1321). */
const PROJECTS_SCREEN: Screen = {
	name: 'projects',
	path: '/projects',
	actionsTestId: 'projects-start-row-actions',
	suggestionsTestId: null,
	headingTestId: 'projects-home-heading',
	subtitleText: /What do you want to organize next\?/,
	actionIds: () => ['projects-show-all', 'projects-search']
};
const SIGNED_IN_SCREENS: Screen[] = [...SCREENS, PROJECTS_SCREEN];

/** Suggestions block and input of each workspace that shows suggestions (Apps has no start-screen input). */
const SUGGESTION_LAYOUTS: Record<string, { suggestions: string; composer: string }> = {
	chats: { suggestions: 'start-screen-suggestions', composer: 'message-field' },
	workflows: { suggestions: 'workflows-start-suggestions', composer: 'workflow-input-composer' },
	projects: { suggestions: 'projects-start-suggestions', composer: 'project-input-composer' }
};

/**
 * Layout B (Marco, 22 Nov): the suggestions block is as wide as the input, centred on it,
 * directly above it, and its lines start at the same left edge inside it.
 */
async function expectSuggestionsLayoutB(page: any, name: string, viewport: string) {
	const ids = SUGGESTION_LAYOUTS[name];
	if (!ids) {
		// Apps has no start-screen input; Tasks has no suggestions at all, nothing overlays its board (Marco, 22 Nov).
		await expect(page.getByTestId(`${name}-start-suggestions`), `${name} shows no suggestions at ${viewport}`).toHaveCount(0);
		await expect(page.getByTestId('follow-up-suggestion-item'), `${name} shows no suggestion lines at ${viewport}`).toHaveCount(0);
		return;
	}
	const suggestions = page.getByTestId(ids.suggestions);
	await expect(suggestions.getByTestId('follow-up-suggestion-item').first(), `${name} shows suggestions at ${viewport}`).toBeVisible({ timeout: 30000 });
	let layout: any = null;
	let previous = '';
	await expect
		.poll(
			async () => {
				layout = await page.evaluate((testIds: { suggestions: string; composer: string }) => {
					const visible = (id: string) => [...document.querySelectorAll<HTMLElement>(`[data-testid="${id}"]`)].find((el) => el.getClientRects().length > 0);
					const block = visible(testIds.suggestions);
					const composer = visible(testIds.composer);
					if (!block || !composer) return null;
					const items = [...block.querySelectorAll<HTMLElement>('[data-testid="follow-up-suggestion-item"]')].map((el) => el.getBoundingClientRect().x);
					const b = block.getBoundingClientRect();
					const c = composer.getBoundingClientRect();
					return { block: { x: b.x, y: b.y, width: b.width, height: b.height }, composer: { x: c.x, y: c.y, width: c.width }, lefts: items };
				}, ids);
				const current = JSON.stringify(layout);
				const stable = layout !== null && current === previous;
				previous = current;
				return stable;
			},
			{ message: `${name} suggestions and input settle at ${viewport}`, timeout: 30000, intervals: [300] }
		)
		.toBe(true);
	const { block, composer, lefts } = layout;
	const where = `${name} at ${viewport}`;
	expect(Math.abs(block.width - composer.width), `${where}: suggestions as wide as the input`).toBeLessThanOrEqual(4);
	expect(Math.abs(block.x + block.width / 2 - (composer.x + composer.width / 2)), `${where}: suggestions centred on the input`).toBeLessThanOrEqual(4);
	expect(block.y + block.height, `${where}: suggestions above the input`).toBeLessThanOrEqual(composer.y + 1);
	expect(composer.y - block.y - block.height, `${where}: suggestions directly above the input`).toBeLessThanOrEqual(40);
	expect(lefts.length).toBeGreaterThan(0);
	expect(Math.max(...lefts) - Math.min(...lefts), `${where}: lines left-aligned`).toBeLessThanOrEqual(1);
	expect(Math.min(...lefts) - composer.x, `${where}: lines start near the input's left edge`).toBeLessThanOrEqual(32);
}

/** Where a workspace puts its panel and report-issue button (Marco, 21 Nov: identical on every workspace). */
type WorkspaceFrame = { name: string; reportX: number; reportY: number; panelBottom: number; label: string };

async function measureWorkspaceFrame(page: any, name: string): Promise<WorkspaceFrame> {
	// After a full page load the session is restored a moment later and the signed-in
	// layout replaces the signed-out one (the report button is rendered again), so wait
	// for the signed-in header, then measure in one DOM read until two reads agree.
	await expect(page.getByTestId('header-login-signup-btn')).toBeHidden({ timeout: 30000 });
	const read = () =>
		page.evaluate(() => {
			const button = [...document.querySelectorAll<HTMLElement>('[data-testid="report-issue-button"]')].find((el) => el.getClientRects().length > 0);
			if (!button) return null;
			const box = button.getBoundingClientRect();
			let node: HTMLElement | null = button;
			while (node && !/(^|\s)((chat|workflows|projects|tasks)-container|apps-route-body)(\s|$)/.test(node.className)) node = node.parentElement;
			const panelBottom = node ? node.getBoundingClientRect().bottom - parseFloat(getComputedStyle(node).paddingBottom) : Number.NaN;
			return { reportX: box.x, reportY: box.y, panelBottom, label: button.innerText.trim() };
		});
	let previous = '';
	let frame: Omit<WorkspaceFrame, 'name'> | null = null;
	await expect
		.poll(
			async () => {
				frame = await read();
				const current = JSON.stringify(frame);
				const stable = frame !== null && current === previous;
				previous = current;
				return stable;
			},
			{ message: `report-issue button on ${name} renders and stops moving`, timeout: 30000, intervals: [300] }
		)
		.toBe(true);
	return { name, ...(frame as unknown as Omit<WorkspaceFrame, 'name'>) };
}

/** Panel bottom and report button match Chats within 1px; the label shows where it fits (pane >= 640px). */
function expectSameWorkspaceFrame(frames: WorkspaceFrame[], viewport: { name: string; width: number }) {
	const where = frames.map((f) => `${f.name} report ${Math.round(f.reportX)},${Math.round(f.reportY)} panel bottom ${Math.round(f.panelBottom)} label "${f.label}"`).join('; ');
	for (const frame of frames) {
		expect(Number.isNaN(frame.panelBottom), `no panel container found on ${frame.name}`).toBe(false);
		expect(Math.abs(frame.reportX - frames[0].reportX), `report button x at ${viewport.name}: ${where}`).toBeLessThanOrEqual(1);
		expect(Math.abs(frame.reportY - frames[0].reportY), `report button y at ${viewport.name}: ${where}`).toBeLessThanOrEqual(1);
		expect(Math.abs(frame.panelBottom - frames[0].panelBottom), `panel bottom at ${viewport.name}: ${where}`).toBeLessThanOrEqual(1);
		expect(frame.label, `report label at ${viewport.name}: ${where}`).toBe(viewport.width >= 700 ? 'Report Issue' : '');
	}
}

/** The start rows may differ in height on screen by at most this much at one width. */
const ROW_TOP_TOLERANCE_PX = 40;

/**
 * Asserts the shared start-screen layout of one screen, attaches its screenshot and returns
 * the row's top edge so the caller can compare it across the start screens.
 */
async function expectStartScreen(page: any, testInfo: any, screen: Screen, viewport: (typeof VIEWPORTS)[number], signedIn: boolean): Promise<number> {
	const actions = page.getByTestId(screen.actionsTestId);
	await expect(actions).toBeVisible({ timeout: 30000 });
	const row = actions.locator('xpath=..');

	// No banner and no banner heading on any start screen.
	await expect(page.getByTestId('daily-inspiration-banner')).toHaveCount(0);
	await expect(page.locator('[data-testid$="daily-inspiration-area"]')).toHaveCount(0);

	// Greeting: "Hey <name>" / "Hey there", then one call to action.
	const heading = page.getByTestId(screen.headingTestId);
	await expect(heading).toBeVisible();
	await expect(heading).toContainText(/Hey/);
	if (signedIn) {
		// Signed in: greeted by name once sign-in and chat sync have finished, never as a guest.
		await expect(heading).not.toContainText(/Hey there/, { timeout: 30000 });
		if (screen.name === 'chats') {
			await expect(page.getByTestId('guest-interest-prompt')).toHaveCount(0, { timeout: 30000 });
			await expect(page.locator('.decrypting-chats-text')).toHaveCount(0, { timeout: 30000 });
		}
	}
	if (screen.subtitleText) await expect(page.getByTestId(`${screen.name}-home-subtitle`)).toHaveText(screen.subtitleText);

	// The header names the workspace on screen from the first load (phone: switcher, wider: tab bar).
	const mobileSwitcher = page.getByTestId('workspace-mobile-select');
	if (await mobileSwitcher.isVisible()) {
		await expect(mobileSwitcher).toHaveAttribute('data-active-workspace', SCREEN_HREFS[screen.name]);
	} else {
		await expect(page.locator('[data-testid="global-header"] .webapp-center-tabs').getByTestId(`${screen.name}-nav-link`)).toHaveAttribute('aria-current', 'page');
	}

	// The actions tile is the last item of the row and holds the expected actions.
	const children = row.locator(':scope > *');
	const childCount = await children.count();
	await expect(children.nth(childCount - 1)).toHaveAttribute('data-testid', screen.actionsTestId);
	const ids: string[] = await actions.locator('button').evaluateAll((nodes: Element[]) =>
		nodes.map((node) => node.getAttribute('data-testid') || '')
	);
	for (const id of screen.actionIds(signedIn)) expect(ids).toContain(id);
	// Nothing about browsing sits below the row.
	await expect(page.locator('[data-testid="chat-browse-controls"], [data-testid="guest-example-link-row"], [data-testid$="-workspace-link-row"]:visible')).toHaveCount(0);

	// At most ten cards, all large and of the same size, the first one centred.
	const cardCount = childCount - 1;
	const rowTop = (await row.boundingBox()).y;
	expect(cardCount).toBeLessThanOrEqual(10);
	if (cardCount > 0) {
		const rowBox = await row.boundingBox();
		// Inspiration cards sit in a `display: contents` placement wrapper (no box of its own),
		// so measure the first card itself.
		const firstCard = row.locator(':scope > :not(.workflow-card-placement), :scope > .workflow-card-placement > *').first();
		const first = await firstCard.boundingBox();
		expect(first, `first start-row card of ${screen.name} at ${viewport.name} has no box`).not.toBeNull();
		const expectedWidth = viewport.width <= 480 ? Math.min(280, viewport.width * 0.76) : 300;
		expect(Math.abs(first.width - expectedWidth)).toBeLessThanOrEqual(1);
		expect(Math.abs(first.height - 200)).toBeLessThanOrEqual(1);
		expect(Math.abs(first.x + first.width / 2 - (rowBox.x + rowBox.width / 2))).toBeLessThanOrEqual(2);
	} else {
		// Nothing to show yet: the browse actions are the only item and sit centred.
		const rowBox = await row.boundingBox();
		const actionsBox = await actions.boundingBox();
		expect(Math.abs(actionsBox.x + actionsBox.width / 2 - (rowBox.x + rowBox.width / 2))).toBeLessThanOrEqual(2);
	}

	// Suggestions below the row.
	if (screen.suggestionsTestId) {
		const suggestions = page.getByTestId(screen.suggestionsTestId);
		await expect(suggestions).toBeVisible();
		await expect(suggestions.getByTestId('follow-up-suggestion-item').first()).toBeVisible();
		const rowBox = await row.boundingBox();
		const box = await suggestions.boundingBox();
		expect(box.y).toBeGreaterThan(rowBox.y + rowBox.height - 1);
		if (screen.name === 'chats') {
			// Chats suggestions sit directly above the composer, not under the row (issue AJV2Q).
			const composerBox = await page.getByTestId('message-field').boundingBox();
			expect(composerBox).toBeTruthy();
			expect(box.y + box.height).toBeLessThanOrEqual(composerBox.y + 1);
			expect(composerBox.y - box.y - box.height).toBeLessThanOrEqual(40);
		}
		await expectSingleLineSuggestions(suggestions, `${screen.name} at ${viewport.name}`);
	}
	if (screen.name === 'chats') await expectGreetingBelowTopButtons(page, heading, viewport.name);

	const name = `${signedIn ? 'signed-in' : 'signed-out'}-${screen.name}-${viewport.name}`;
	await testInfo.attach(name, { body: await page.screenshot(), contentType: 'image/png' });
	await actions.scrollIntoViewIfNeeded();
	await testInfo.attach(`${name}-row-end`, { body: await page.screenshot(), contentType: 'image/png' });
	return rowTop;
}

/** Every start-screen suggestion is one line high; longer text is cut with an ellipsis. */
async function expectSingleLineSuggestions(suggestions: any, where: string) {
	const lines: { text: string; height: number; lineHeight: number; whiteSpace: string }[] = await suggestions
		.getByTestId('follow-up-suggestion-text')
		.evaluateAll((nodes: Element[]) =>
			nodes.map((node) => {
				const style = getComputedStyle(node);
				return {
					text: (node.textContent || '').trim(),
					height: node.getBoundingClientRect().height,
					lineHeight: parseFloat(style.lineHeight),
					whiteSpace: style.whiteSpace
				};
			})
		);
	expect(lines.length).toBeGreaterThan(0);
	for (const line of lines) {
		expect(line.whiteSpace, `suggestion "${line.text}" on ${where} may wrap`).toBe('nowrap');
		expect(line.height, `suggestion "${line.text}" on ${where} is ${line.height}px high`).toBeLessThan(line.lineHeight * 1.5);
	}
}

/** The Chats greeting starts below the report/tasks/call buttons row instead of sliding under it. */
async function expectGreetingBelowTopButtons(page: any, heading: any, viewportName: string) {
	const topButtons = page.getByTestId('chat-top-actions');
	await expect(topButtons).toBeVisible();
	const buttonsBox = await topButtons.boundingBox();
	const headingBox = await heading.boundingBox();
	expect(
		headingBox.y,
		`greeting top ${Math.round(headingBox.y)}px vs top buttons bottom ${Math.round(buttonsBox.y + buttonsBox.height)}px at ${viewportName}`
	).toBeGreaterThanOrEqual(buttonsBox.y + buttonsBox.height - 1);
}

/** All start screens show their rows at the same height on screen. */
function expectAlignedRows(rowTops: number[], viewportName: string) {
	const spread = Math.max(...rowTops) - Math.min(...rowTops);
	expect(spread, `start rows at ${viewportName} sit at ${rowTops.map(Math.round).join(', ')}px`).toBeLessThanOrEqual(ROW_TOP_TOLERANCE_PX);
}

test.describe('start screens layout', () => {
	// contract-test: direct surface=gui.web assertions=daily-inspiration.start-row-actions,daily-inspiration.start-row-suggestions,workspace-shell.start.available-space-cards
	test('signed-out Chats, Apps and Workflows share the start-screen layout at every width', async ({ browser }: { browser: any }, testInfo: any) => {
		test.setTimeout(240000);
		for (const viewport of VIEWPORTS) {
			const context = await browser.newContext({
				viewport: { width: viewport.width, height: viewport.height },
				recordVideo: { dir: testInfo.outputPath(`video-signed-out-${viewport.name}`), size: { width: viewport.width, height: viewport.height } }
			});
			const page = await context.newPage();
			const rowTops: number[] = [];
			for (const screen of SCREENS) {
				await page.goto(getE2EDebugUrl(screen.path), { waitUntil: 'domcontentloaded' });
				rowTops.push(await expectStartScreen(page, testInfo, screen, viewport, false));
			}
			expectAlignedRows(rowTops, viewport.name);
			await context.close();
		}
	});

	// contract-test: direct surface=gui.web assertions=daily-inspiration.start-row-actions,daily-inspiration.start-row-suggestions,workspace-shell.start.available-space-cards,workflows-ui.home.prompt-suggestions,daily-inspiration.start-suggestions-layout
	test('signed-in Chats, Apps, Workflows and Projects share the start-screen layout at every width', async ({ page }: { page: any }, testInfo: any) => {
		test.slow();
		test.setTimeout(300000);
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
		const log = createSignupLogger('START_SCREENS');
		const screenshot = createStepScreenshotter(log);
		const proof = createVideoProofRuntime(START_SCREENS_PROOF, {
			device: 'web-laptop',
			attach: testInfo.attach.bind(testInfo),
			captureFrame: () => page.screenshot({ type: 'png' })
		});
		await page.setViewportSize({ width: 1280, height: 800 });
		await loginToTestAccount(page, log, screenshot);

		// Phone and tablet first; the desktop pass last so the proof video ends on the laptop layout.
		for (const viewport of [VIEWPORTS[0], VIEWPORTS[1], VIEWPORTS[2]]) {
			await page.setViewportSize({ width: viewport.width, height: viewport.height });
			const rowTops: number[] = [];
			for (const screen of SIGNED_IN_SCREENS) {
				await page.goto(getE2EDebugUrl(screen.path), { waitUntil: 'domcontentloaded' });
				if (viewport.name !== 'desktop') {
					rowTops.push(await expectStartScreen(page, testInfo, screen, viewport, true));
					continue;
				}
				await proof.assert(`start.${screen.name}_layout`, async () => {
					rowTops.push(await expectStartScreen(page, testInfo, screen, viewport, true));
				});
				await page.getByTestId(screen.actionsTestId).locator('xpath=..').evaluate((node: Element) => node.scrollTo({ left: 0 }));
				await proof.checkpoint(`${screen.name}-start`);
			}
			expectAlignedRows(rowTops, viewport.name);
			// Panel, input area and report-issue button sit exactly where they do on Chats, Tasks included.
			const frames: WorkspaceFrame[] = [];
			for (const screen of [...SIGNED_IN_SCREENS, { name: 'tasks', path: '/tasks' }]) {
				await page.goto(getE2EDebugUrl(screen.path), { waitUntil: 'domcontentloaded' });
				frames.push(await measureWorkspaceFrame(page, screen.name));
				// Every signed-in workspace greets the user by name ("Hey <username>!"), never "Hey there!".
				await expect(page.getByText(/^Hey .+!$/).first(), `${screen.name} greets the user`).toBeVisible({ timeout: 15000 });
				await expect(page.getByText('Hey there!', { exact: true }), `${screen.name} greets the user by name`).toHaveCount(0, { timeout: 15000 });
				await expectSuggestionsLayoutB(page, screen.name, viewport.name);
				await testInfo.attach(`frame-${viewport.name}-${screen.name}`, { body: await page.screenshot(), contentType: 'image/png' });
			}
			expectSameWorkspaceFrame(frames, viewport);
		}

		// Short phone screen (issue CCFK8): Chats keeps one-line suggestions and the greeting below the buttons.
		await page.setViewportSize({ width: SHORT_PHONE.width, height: SHORT_PHONE.height });
		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await expectStartScreen(page, testInfo, SCREENS[0], SHORT_PHONE, true);
		await page.setViewportSize({ width: VIEWPORTS[2].width, height: VIEWPORTS[2].height });
		await page.goto(getE2EDebugUrl('/workflows'), { waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('workflows-start-suggestions')).toBeVisible({ timeout: 30000 });
		// Workflows suggestions sit directly above the describe-a-workflow input (Marco, 21 Nov).
		await expect(page.getByTestId('workflow-input-composer')).toBeVisible({ timeout: 30000 });
		// The suggestions list is rendered again once the user's own workflow suggestions
		// load, so both boxes are read in one DOM pass, after the list has settled.
		const readWorkflowBoxes = () =>
			page.evaluate(() => {
				const box = (testId: string) => {
					const el = document.querySelector(`[data-testid="${testId}"]`);
					if (!el || el.getClientRects().length === 0) return null;
					const r = el.getBoundingClientRect();
					return { y: r.y, height: r.height };
				};
				return { suggestions: box('workflows-start-suggestions'), composer: box('workflow-input-composer') };
			});
		let workflowBoxes: any = null;
		let previousBoxes = '';
		await expect
			.poll(
				async () => {
					workflowBoxes = await readWorkflowBoxes();
					const current = JSON.stringify(workflowBoxes);
					const stable = !!workflowBoxes.suggestions && !!workflowBoxes.composer && current === previousBoxes;
					previousBoxes = current;
					return stable;
				},
				{ message: 'Workflows suggestions and composer are on screen and settled', timeout: 30000, intervals: [300] }
			)
			.toBe(true);
		const workflowSuggestionsBox = workflowBoxes.suggestions;
		const workflowComposerBox = workflowBoxes.composer;
		expect(workflowSuggestionsBox.y + workflowSuggestionsBox.height).toBeLessThanOrEqual(workflowComposerBox.y + 1);
		expect(workflowComposerBox.y - workflowSuggestionsBox.y - workflowSuggestionsBox.height).toBeLessThanOrEqual(24);

		// Tapping a workflow suggestion fills the describe-a-workflow composer.
		const suggestion = page.getByTestId('workflows-start-suggestions').getByTestId('follow-up-suggestion-item').first();
		const text = (await suggestion.innerText()).trim();
		await suggestion.click();
		await proof.assert('start.workflow_suggestion', () => expect(page.getByTestId('workflow-input-textarea')).toHaveValue(text));
		await proof.checkpoint('workflow-suggestion-filled');
		await testInfo.attach('signed-in-workflows-suggestion-filled', { body: await page.screenshot(), contentType: 'image/png' });

		// Tapping a Chats suggestion puts it into the composer.
		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		const chatSuggestion = page.getByTestId('start-screen-suggestions').getByTestId('follow-up-suggestion-item').first();
		await expect(chatSuggestion).toBeVisible({ timeout: 30000 });
		const chatText = (await chatSuggestion.innerText()).trim();
		await chatSuggestion.click();
		await expect(page.getByTestId('message-editor').locator('.ProseMirror')).toContainText(chatText);
		await testInfo.attach('signed-in-chats-suggestion-filled', { body: await page.screenshot(), contentType: 'image/png' });
		await proof.attach();
	});

	// contract-test: direct surface=gui.web assertions=workspace-shell.start.available-space-cards
	test('signed-in start screens of all five workspaces are clean on desktop and phone', async ({ page }: { page: any }, testInfo: any) => {
		test.slow();
		test.setTimeout(300000);
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
		const log = createSignupLogger('START_SCREENS_ALL');
		const screenshot = createStepScreenshotter(log);
		await page.setViewportSize({ width: 1280, height: 800 });
		await loginToTestAccount(page, log, screenshot);

		const workspaces = [
			...SIGNED_IN_SCREENS.map((screen) => ({ name: screen.name as string, path: screen.path, ready: screen.headingTestId })),
			{ name: 'tasks', path: '/tasks', ready: 'task-board' }
		];
		// Tasks last at both sizes, so a Tasks problem never hides the other four screens.
		const visits = [false, true].flatMap((tasksPass) => [VIEWPORTS[2], VIEWPORTS[0]].flatMap((viewport) =>
			workspaces.filter((workspace) => (workspace.name === 'tasks') === tasksPass).map((workspace) => ({ viewport, workspace }))));
		for (const { viewport, workspace } of visits) {
			{
				await page.setViewportSize({ width: viewport.width, height: viewport.height });
				await page.goto(getE2EDebugUrl(workspace.path), { waitUntil: 'domcontentloaded' });
				await expect(page.getByTestId(workspace.ready), `${workspace.name} ready at ${viewport.name}`).toBeVisible({ timeout: 30000 });
				if (workspace.name === 'tasks') {
					await expect(page.getByTestId('tasks-loading')).toHaveCount(0, { timeout: 30000 });
				} else {
					await expect(page.getByTestId(`${workspace.name === 'chats' ? 'start-row' : workspace.name + '-start-row'}-actions`)).toBeVisible({ timeout: 30000 });
				}
				const text: string = await page.locator('body').innerText();
				await assertNoMissingTranslations(page);
				expect(text, `${workspace.name} shows Untitled chat at ${viewport.name}`).not.toContain('Untitled chat');
				await expect(page.locator('[data-testid="notification"].notification-error'), `error notification on ${workspace.name} at ${viewport.name}`).toHaveCount(0);
				await testInfo.attach(`${viewport.name}-${workspace.name}`, { body: await page.screenshot(), contentType: 'image/png' });
			}
		}
	});
});
