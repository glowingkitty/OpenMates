/* eslint-disable @typescript-eslint/no-require-imports -- E2E helpers expose CommonJS exports. */
/**
 * Shared steps for the live-collaboration E2E specs (live-collab-*.spec.ts).
 *
 * Two real accounts: the owner creates a Team and invites the member (secure
 * link flow of teams-invite-acceptance.spec.ts), the owner creates a Team
 * Project with a file (document, sheet, deck, code), and both open that file in
 * edit mode with the `live_collaboration` web flag on. Spec:
 * specifications/features/live-collaboration/specification.yml.
 */
export {};
import type { Browser, BrowserContext, Locator, Page, Response } from '@playwright/test';

const { expect } = require('./cookie-audit');
const { createIsolatedBrowserContext, declareTestState, loginToTestAccount } = require('./chat-test-helpers');
const { naturalProjectName } = require('./project-names');
const { selectTeamInQuickPicker, setTeamMode } = require('./team-quick-context');

export type LiveKind = 'document' | 'sheet' | 'slides' | 'code';
export type Account = { email: string; password: string; otpKey?: string };

const MEMBER_STATE = declareTestState({
	auth: 'sign in through the secure Team invitation',
	browserStorage: 'fresh',
	account: 'second isolated CI account',
	chat: 'no existing chat required',
	notifications: 'fixture uses the Team invitation',
	securityReminders: 'standard first-sign-in handling',
});

/** Header Edit toggle test id per file kind (same ids as projects-create-edit-files.spec.ts). */
export const EDIT_TOGGLE: Record<LiveKind, string> = {
	document: 'docs-edit-button',
	sheet: 'sheet-edit-toggle',
	slides: 'slides-edit',
	code: 'code-edit-button'
};

export async function shot(page: Page, name: string): Promise<void> {
	const { test } = require('./cookie-audit');
	await test.info().attach(name, { body: await page.screenshot(), contentType: 'image/png' });
}

/** Turn the live collaboration web flag on before any app code runs. */
export async function enableLiveFlag(context: BrowserContext): Promise<void> {
	await context.addInitScript(() => window.localStorage.setItem('om_live_collaboration', '1'));
}

function isApi(response: Response, method: string, suffix: RegExp): boolean {
	return response.request().method() === method && suffix.test(new URL(response.url()).pathname);
}

/** Document text without remote caret labels (their names are not content). */
export async function editorText(locator: Locator): Promise<string> {
	return locator.evaluate((root: Element) => {
		const clone = root.cloneNode(true) as HTMLElement;
		clone
			.querySelectorAll('.collaboration-carets__caret, .collaboration-carets__label, .collaboration-cursor__caret, .cm-ySelectionCaret, .cm-ySelectionInfo, .cm-ySelectionCaretDot')
			.forEach((node) => node.remove());
		const blocks = clone.querySelectorAll('p, h1, h2, h3, h4, h5, h6, li, .cm-line');
		const lines = blocks.length ? Array.from(blocks, (node) => node.textContent ?? '') : [clone.textContent ?? ''];
		return lines.join('\n').trim();
	});
}

export type TeamSetup = { teamId: string; teamName: string; projectId: string; projectName: string; member: Page; memberContext: BrowserContext };

/** Owner creates a Team, invites the member, the member joins in their own browser context. */
export async function createTeamWithMember(owner: Page, browser: Browser, ownerAcct: Account, memberAcct: Account): Promise<{ teamId: string; teamName: string; member: Page; memberContext: BrowserContext }> {
	await owner.evaluate(() => {
		Object.defineProperty(navigator, 'clipboard', {
			configurable: true,
			value: { writeText: async (text: string) => { document.body.dataset.secureInvite = text; } }
		});
	});
	await owner.getByTestId('profile-container').click();
	await owner.getByTestId('settings-teams-item').click();
	await owner.getByTestId('team-create-open').click();
	const teamName = naturalProjectName('Garden club');
	await owner.getByTestId('team-name-input').fill(teamName);
	await owner.getByTestId('team-create-continue').click();
	const created = owner.waitForResponse((r: Response) => isApi(r, 'POST', /^\/v1\/teams$/) && r.ok());
	await owner.getByTestId('team-create-submit').click();
	const teamId = String((await (await created).json()).team.team_id);
	await expect(owner.getByTestId('team-settings-header')).toContainText(teamName);
	await owner.getByTestId('team-members-open').click();
	await owner.getByTestId('team-invite-email-input').fill(memberAcct.email);
	const invited = owner.waitForResponse((r: Response) => isApi(r, 'POST', /\/invites$/) && r.ok());
	await owner.getByTestId('team-invite-submit').click();
	const inviteId: string = (await (await invited).json()).invite.invite_id;
	await owner.getByTestId('team-invite-copy-secure-link').click();
	const secureUrl = await owner.locator('body').getAttribute('data-secure-invite');
	expect(secureUrl).toMatch(/\/teams\/invites\/[^#]+#key=/);

	const viewport = owner.viewportSize() ?? { width: 1440, height: 1000 };
	const { test } = require('./cookie-audit');
	const memberContext: BrowserContext = await createIsolatedBrowserContext(browser, MEMBER_STATE, {
		baseURL: new URL(secureUrl!).origin,
		viewport,
		recordVideo: { dir: test.info().outputPath('member-video'), size: viewport }
	});
	await enableLiveFlag(memberContext);
	const member = await memberContext.newPage();
	captureLiveDiagnostics(member, test.info(), 'member');
	await member.goto(secureUrl!);
	// The guest handoff moves the fragment key into this tab's sessionStorage;
	// logging in before that happens loses the key ("link is missing its secure key").
	await expect.poll(() => member.url()).not.toContain('#key=');
	await expect
		.poll(() => member.evaluate((id: string) => !!sessionStorage.getItem(`openmates:team-invite:${id}`), inviteId))
		.toBe(true);
	await loginToTestAccount(member, undefined, undefined, { credentials: memberAcct });
	await member.goto(secureUrl!.split('#')[0]);
	await expect(member.getByTestId('team-invite-recipient-email')).toBeVisible({ timeout: 30_000 });
	await member.getByTestId('team-invite-recipient-email').fill(memberAcct.email);
	await member.getByTestId('team-invite-accept').click();
	await expect(member.getByTestId('team-invite-result')).toContainText(/joined/i, { timeout: 60_000 });
	return { teamId, teamName, member, memberContext };
}

/** Switch a page into the Team workspace through the quick picker. */
export async function enterTeam(page: Page, teamId: string, teamName: string): Promise<void> {
	// The quick picker lives on the root of the settings menu, so leave the invite
	// page (member) and any Teams sub page (owner) first, as teams-settings-context does.
	if (page.url().includes('/teams/invites')) await page.goto('/', { waitUntil: 'domcontentloaded' });
	const picker = page.getByTestId('team-quick-context-dropdown');
	for (let step = 0; step < 6 && !(await picker.isVisible().catch(() => false)); step++) {
		if (!(await page.getByTestId('settings-menu').isVisible().catch(() => false))) {
			await page.getByTestId('profile-container').click();
		} else if (await page.getByTestId('banner-back-button').isVisible().catch(() => false)) {
			await page.getByTestId('banner-back-button').click();
		}
		await picker.waitFor({ state: 'visible', timeout: 5_000 }).catch(() => undefined);
	}
	await selectTeamInQuickPicker(page, teamId, teamName);
	await setTeamMode(page, true);
	await page.getByTestId('icon-button-close').click();
	await expect(page.getByTestId('settings-menu')).not.toBeVisible({ timeout: 15_000 });
}

/**
 * Record console messages and live/assistant WebSocket frames of a page and attach
 * them to the test (also on failure). Frame payloads are ciphertext; only the frame
 * direction and the first 300 characters are kept. Worker console is not exposed by
 * Playwright, so it is not captured. Returns an async function to call in afterEach/finally.
 */
export function captureLiveDiagnostics(page: Page, testInfo: { attach: (name: string, options: { body: string; contentType: string }) => Promise<void> }, label: string): () => Promise<void> {
	const flush = collectDiagnostics(page, testInfo, label);
	pendingDiagnostics.push(flush);
	return flush;
}

const pendingDiagnostics: Array<() => Promise<void>> = [];

/** Attach every captured log of this test; call from `test.afterEach` so failures keep them. */
export async function attachLiveDiagnostics(): Promise<void> {
	const flushes = pendingDiagnostics.splice(0);
	for (const flush of flushes) await flush();
}

function collectDiagnostics(page: Page, testInfo: { attach: (name: string, options: { body: string; contentType: string }) => Promise<void> }, label: string): () => Promise<void> {
	const lines: string[] = [];
	const stamp = () => new Date().toISOString();
	page.on('console', (message) => lines.push(`${stamp()} console.${message.type()} ${message.text().slice(0, 500)}`));
	page.on('pageerror', (error) => lines.push(`${stamp()} pageerror ${String(error).slice(0, 500)}`));
	page.on('websocket', (ws) => {
		const record = (type: string) => (frame: { payload: string | Buffer }) => {
			const payload = typeof frame.payload === 'string' ? frame.payload : frame.payload.toString('utf8');
			if (payload.includes('live_item_') || payload.includes('embed_assistant_')) lines.push(`${stamp()} ws.${type} ${payload.slice(0, 300)}`);
		};
		ws.on('framesent', record('sent'));
		ws.on('framereceived', record('received'));
	});
	return async () => {
		await testInfo.attach(`${label}-live-log`, { body: lines.join('\n') || '(empty)', contentType: 'text/plain' }).catch(() => undefined);
	};
}

/** Create a Project in the active Team context and one file of `kind`; resolves with the project id. */
export async function createTeamProjectFile(owner: Page, kind: LiveKind, topic: string, fileName: string): Promise<{ projectId: string; projectName: string }> {
	const projectName = naturalProjectName(topic);
	await owner.goto('/projects');
	await expect(owner.getByTestId('projects-page')).toBeVisible({ timeout: 30_000 });
	const created = owner.waitForResponse((r: Response) => isApi(r, 'POST', /^\/v1\/projects$/) && r.ok());
	await owner.getByTestId('project-input-textarea').fill(projectName);
	await owner.getByTestId('project-input-submit').click();
	await owner.getByTestId('project-write-policy-apply-and-show').check();
	await owner.getByTestId('project-write-policy-confirm').click();
	const projectId = (await (await created).json()).project.project_id as string;
	await expect(owner.getByTestId('project-workspace-header')).toBeVisible({ timeout: 30_000 });
	await owner.getByTestId('project-tab-folders').click();
	await owner.getByTestId('project-folder-create-menu-button').click();
	await owner.getByTestId(`project-create-${kind}`).first().click();
	await owner.getByTestId('project-create-name-input').fill(fileName);
	const stored = owner.waitForResponse((r: Response) => isApi(r, 'POST', /\/v1\/projects\/[^/]+\/upload-embed$/) && r.ok());
	await owner.getByTestId('project-create-name-submit').click();
	await stored;
	await expect(owner.getByTestId('project-embed-viewer')).toBeVisible({ timeout: 30_000 });
	return { projectId, projectName };
}

/** Open an existing Project file from its Files tab (the member side). */
export async function openProjectFile(page: Page, projectId: string, fileName: string): Promise<void> {
	await page.goto(`/projects/${encodeURIComponent(projectId)}`, { waitUntil: 'domcontentloaded' });
	await expect(page.getByTestId('project-workspace-header')).toBeVisible({ timeout: 60_000 });
	await page.getByTestId('project-tab-folders').click();
	// The stored file name joins words with "_" and adds the kind's extension ("Spring_issue.docx").
	const words = fileName.trim().split(/\s+/).map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
	const card = page.getByTestId('project-item-card').filter({ hasText: new RegExp(words.join('[ _]')) }).first();
	await expect(card).toBeVisible({ timeout: 60_000 });
	await card.click();
	await expect(page.getByTestId('project-embed-viewer')).toBeVisible({ timeout: 30_000 });
}

/** Press the header Edit toggle; in live mode there is no Save step. */
export async function startLiveEditing(page: Page, kind: LiveKind): Promise<void> {
	const button = page.getByTestId(EDIT_TOGGLE[kind]);
	await expect(button).toHaveAttribute('data-edit-state', 'edit', { timeout: 30_000 });
	await button.click();
	await expect(page.getByTestId('live-header-status')).toBeVisible({ timeout: 30_000 });
}

/** Owner side: Team + member + Team Project with one file, both sides open it in live edit mode. */
export async function openLivePair(owner: Page, browser: Browser, ownerAcct: Account, memberAcct: Account, kind: LiveKind, topic: string, fileName: string): Promise<TeamSetup> {
	captureLiveDiagnostics(owner, require('./cookie-audit').test.info(), 'owner');
	const joined = await createTeamWithMember(owner, browser, ownerAcct, memberAcct);
	await enterTeam(owner, joined.teamId, joined.teamName);
	const project = await createTeamProjectFile(owner, kind, topic, fileName);
	await enterTeam(joined.member, joined.teamId, joined.teamName);
	await openProjectFile(joined.member, project.projectId, fileName);
	await startLiveEditing(owner, kind);
	await startLiveEditing(joined.member, kind);
	return { ...joined, ...project };
}

/** Best-effort cleanup: delete the Project and the Team; never fails the spec. */
export async function cleanupTeam(owner: Page, setup: Partial<TeamSetup>): Promise<void> {
	if (setup.memberContext) await setup.memberContext.close().catch(() => undefined);
	if (setup.projectId) {
		await owner.request.delete(`/v1/projects/${setup.projectId}`).catch(() => undefined);
	}
}

export { loginToTestAccount };
