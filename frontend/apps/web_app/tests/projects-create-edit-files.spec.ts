/* eslint-disable @typescript-eslint/no-require-imports -- spec helpers are CommonJS, shared with other specs */
export {};

/**
 * Create, edit and save new documents, sheets, slide decks and code files
 * inside a Project folder (web, Rust core build, real isolated stack).
 *
 * Specification: feature.projects `projects.items.create-documents` and
 * feature.doc-editor `doc-editor.edit.*`. Each test creates a fresh Project,
 * picks one entry of the Files tab Create menu, names the new file, edits it in
 * the fullscreen editor that opens, saves it as the next version through the
 * client core's user revision commit, then reloads the page and reopens the
 * file from the Project folder to prove the saved version came back from the
 * backend. No mocks: real backend, real encryption, real Project item links.
 *
 * Run: ci_coordinator.py submit --mode e2e --spec projects-create-edit-files.spec.ts
 */

const { test, expect } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled, skipWithoutCredentials } = require('./helpers/env-guard');
const { getTestAccount } = require('./signup-flow-helpers');
const { naturalProjectName } = require('./helpers/project-names');
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

type Kind = 'document' | 'sheet' | 'slides' | 'code';

const PROOF_DEVICE = 'web-laptop';
const LABEL: Record<Kind, string> = { document: 'document', sheet: 'sheet', slides: 'slide deck', code: 'code file' };

/** Video proof of one kind: created and edited, saved as a new version, reopened after a reload. */
function proofContract(kind: Kind) {
	const label = LABEL[kind];
	const devices = [PROOF_DEVICE];
	return defineVideoProof({
		id: `projects-create-edit-${kind}`,
		title: `Create, edit and save a ${label} in a Project`,
		surface: 'web',
		devices,
		domain: 'app.dev.openmates.org',
		transcript: [
			{ id: `${kind}-editing`, text: `A new ${label} is created from the Project's Create menu and edited in its editor.`, checkpoint: `${kind}-editing`, devices },
			{ id: `${kind}-saved`, text: `The edit is saved as the next version of the Project file.`, checkpoint: `${kind}-saved`, devices },
			{ id: `${kind}-after-reload`, text: `After a reload the ${label} reopens from the Project folder with the saved edit.`, checkpoint: `${kind}-after-reload`, devices },
		],
		assertions: [
			{ id: `projects.items.create-documents.${kind}.edit`, checkpoint: `${kind}-editing`, visual: `The new ${label} is open in its editor with the typed edit visible.`, devices },
			{ id: `projects.items.create-documents.${kind}.saved`, checkpoint: `${kind}-saved`, visual: `The editor has closed and the viewer shows the saved edit.`, devices },
			{ id: `projects.items.create-documents.${kind}.reloaded`, checkpoint: `${kind}-after-reload`, visual: `The reopened ${label} visibly shows the saved edit.`, devices },
		],
		tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 },
	});
}

function proofFor(kind: Kind, page: any) {
	const testInfo = test.info();
	return createVideoProofRuntime(proofContract(kind), {
		device: PROOF_DEVICE,
		attach: testInfo.attach.bind(testInfo),
		captureFrame: () => page.screenshot({ type: 'png' }),
	});
}

/** Attach a named screenshot of the page to the CI artifact. */
async function shot(page: any, name: string): Promise<void> {
	await test.info().attach(name, { body: await page.screenshot(), contentType: 'image/png' });
}

/** Create a Project through the start screen and return its id. */
async function createProject(page: any, topic: string): Promise<string> {
	await page.goto('/projects');
	await expect(page.getByTestId('projects-page')).toBeVisible({ timeout: 30_000 });
	const created = page.waitForResponse((response: any) => response.request().method() === 'POST'
		&& new URL(response.url()).pathname === '/v1/projects' && response.ok());
	await page.getByTestId('project-input-textarea').fill(naturalProjectName(topic));
	await page.getByTestId('project-input-submit').click();
	await page.getByTestId('project-write-policy-apply-and-show').check();
	await page.getByTestId('project-write-policy-confirm').click();
	const projectId = (await (await created).json()).project.project_id as string;
	await expect(page.getByTestId('project-workspace-header')).toBeVisible({ timeout: 30_000 });
	return projectId;
}

/** Open the Files tab of the current Project. */
async function openFiles(page: any): Promise<void> {
	await page.getByTestId('project-tab-folders').click();
	await expect(page.getByTestId('project-folders-panel')).toBeVisible({ timeout: 30_000 });
}

/** Create a file of `kind` named `name` from the Files tab Create menu; resolves once its viewer is open. */
async function createFile(page: any, kind: Kind, name: string): Promise<void> {
	await openFiles(page);
	await page.getByTestId('project-folder-create-menu-button').click();
	await expect(page.getByTestId(`project-create-${kind}`).first()).toBeVisible();
	await shot(page, `${kind}-create-menu`);
	await page.getByTestId(`project-create-${kind}`).first().click();
	const nameInput = page.getByTestId('project-create-name-input');
	await expect(nameInput).toBeVisible();
	await nameInput.fill(name);
	const stored = page.waitForResponse((response: any) => response.request().method() === 'POST'
		&& /\/v1\/projects\/[^/]+\/upload-embed$/.test(new URL(response.url()).pathname), { timeout: 30_000 });
	await page.getByTestId('project-create-name-submit').click();
	expect((await stored).ok(), 'the new Project file should be stored').toBe(true);
	await expect(page.getByTestId('project-embed-viewer')).toBeVisible({ timeout: 30_000 });
	await expect(page.getByTestId('project-item-card').filter({ hasText: name }).first()).toBeVisible({ timeout: 30_000 });
}

/**
 * Press the round Edit button in the embed header (`testId` is the type's id
 * for the shared button) and check that it turned into the check-mark Save.
 * spec: embed-user-edits.header.edit-save-button.
 */
async function startEditing(page: any, testId: string, kind: string): Promise<void> {
	const button = page.getByTestId(testId);
	await expect(button).toHaveAttribute('data-edit-state', 'edit', { timeout: 30_000 });
	await expect(button.getByTestId('embed-edit-icon')).toBeVisible();
	await button.click();
	await expect(button).toHaveAttribute('data-edit-state', 'save');
	await expect(button.getByTestId('embed-edit-save-icon')).toBeVisible();
	await shot(page, `${kind}-header-save-button`);
}

/** Press the header check mark: saves and leaves edit mode (the button is the pencil again). */
async function finishEditing(page: any, testId: string): Promise<void> {
	const button = page.getByTestId(testId);
	await expect(button).toHaveAttribute('data-edit-state', 'save');
	await button.click();
	await expect(button).toHaveAttribute('data-edit-state', 'edit', { timeout: 60_000 });
}

/**
 * Wait for a successful user revision commit (the editor's save). A first
 * edit of a new file is answered 409 `base_snapshot_required` and the core
 * resends it with version 1's snapshot, so only a 2xx answer counts.
 */
function revisionSaved(page: any) {
	return page.waitForResponse((response: any) => response.request().method() === 'POST'
		&& /\/v1\/embeds\/[^/]+\/user-revisions$/.test(new URL(response.url()).pathname)
		&& response.status() < 300, { timeout: 60_000 });
}

/** Reload, reopen the Project and its file from the Files tab; resolves with the viewer. */
async function reopenFile(page: any, projectId: string, name: string): Promise<any> {
	await page.goto(`/projects/${encodeURIComponent(projectId)}`, { waitUntil: 'domcontentloaded' });
	await expect(page.getByTestId('project-workspace-header')).toBeVisible({ timeout: 60_000 });
	await openFiles(page);
	const card = page.getByTestId('project-item-card').filter({ hasText: name }).first();
	await expect(card).toBeVisible({ timeout: 60_000 });
	await card.click();
	const viewer = page.getByTestId('project-embed-viewer');
	await expect(viewer).toBeVisible({ timeout: 30_000 });
	return viewer;
}

async function deleteProject(page: any, projectId: string): Promise<void> {
	await page.goto(`/projects/${encodeURIComponent(projectId)}`, { waitUntil: 'domcontentloaded' });
	await expect(page.getByTestId('project-workspace-header')).toBeVisible({ timeout: 60_000 });
	const deleted = page.waitForResponse((response: any) => response.request().method() === 'DELETE'
		&& new URL(response.url()).pathname === `/v1/projects/${projectId}`);
	page.once('dialog', (dialog: any) => dialog.accept());
	await page.getByTestId('project-more-button').click();
	await page.getByTestId('project-delete-button').click();
	await deleted;
}

/**
 * Diagnostics only: records the server's `error` frames and the request types
 * sent on the Rust core's shared-Worker websockets (Playwright cannot see
 * worker sockets), so a refused save names the server's reason. Error frames
 * carry no file content or key material.
 */
async function watchWorkerSockets(page: any, sink: string[]): Promise<() => Promise<void>> {
	const browser = page.context().browser();
	if (!browser) return async () => {};
	const cdp = await browser.newBrowserCDPSession();
	const attached = new Set<string>();
	const note = (direction: string, data: string) => {
		let frame: any;
		try {
			frame = JSON.parse(data);
		} catch {
			return;
		}
		const type = frame?.type ?? frame?.event;
		if (direction === 'sent' && typeof type === 'string') sink.push(`ws sent ${type}`);
		if (direction === 'received' && type === 'error') sink.push(`ws error frame: ${JSON.stringify(frame.payload ?? frame).slice(0, 400)}`);
	};
	cdp.on('Target.receivedMessageFromTarget', (event: any) => {
		const message = JSON.parse(event.message);
		if (message.method === 'Network.webSocketFrameReceived') note('received', message.params.response.payloadData);
		if (message.method === 'Network.webSocketFrameSent') note('sent', message.params.response.payloadData);
	});
	const attach = async (info: any) => {
		if (!['shared_worker', 'worker'].includes(info.type) || attached.has(info.targetId)) return;
		attached.add(info.targetId);
		const { sessionId } = await cdp.send('Target.attachToTarget', { targetId: info.targetId, flatten: false });
		await cdp.send('Target.sendMessageToTarget', { sessionId, message: JSON.stringify({ id: 1, method: 'Network.enable' }) });
		sink.push(`watching ${info.type} websockets`);
	};
	cdp.on('Target.targetCreated', (event: any) => void attach(event.targetInfo).catch((error: unknown) => sink.push(`worker watch failed: ${String(error)}`)));
	await cdp.send('Target.setDiscoverTargets', { discover: true });
	const { targetInfos } = await cdp.send('Target.getTargets');
	for (const info of targetInfos) await attach(info).catch((error: unknown) => sink.push(`worker watch failed: ${String(error)}`));
	return async () => { await cdp.detach().catch(() => {}); };
}

test.describe('Create and edit files in a Project', () => {
	test.describe.configure({ timeout: 240_000 });

	/** Browser console errors of the current test, attached to the report so a failed save names its cause. */
	let consoleErrors: string[] = [];
	let stopWorkerWatch: () => Promise<void> = async () => {};

	test.afterEach(async () => {
		await stopWorkerWatch();
		if (!consoleErrors.length) return;
		await test.info().attach('browser-console-errors', { body: consoleErrors.join('\n'), contentType: 'text/plain' });
		console.log(`[browser console errors]\n${consoleErrors.join('\n')}`);
	});

	test.beforeEach(async ({ page }: { page: any }) => {
		consoleErrors = [];
		page.on('console', (message: any) => {
			if (message.type() === 'error') consoleErrors.push(message.text().slice(0, 600));
		});
		page.on('pageerror', (error: any) => consoleErrors.push(`pageerror: ${String(error).slice(0, 600)}`));
		page.on('response', (response: any) => {
			if (response.status() >= 400) consoleErrors.push(`http ${response.status()} ${response.request().method()} ${response.url().replace(/[?#].*$/, '')}`);
		});
		stopWorkerWatch = await watchWorkerSockets(page, consoleErrors);
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
		await skipIfFeaturesDisabled(test, page, ['platform:projects']);
		await page.setViewportSize({ width: 1440, height: 1000 });
		await loginToTestAccount(page);
	});

	// contract-test: direct surface=gui.web assertions=projects.items.create-documents,doc-editor.edit.rich-text
	test('creates a document, formats it in the editor and reopens the saved version', async ({ page }: { page: any }) => {
		const proof = proofFor('document', page);
		const projectId = await createProject(page, 'Conference talk');
		try {
			await createFile(page, 'document', 'Talk outline');
			const viewer = page.getByTestId('project-embed-viewer');
			await startEditing(page, 'docs-edit-button', 'document');
			const content = viewer.getByTestId('docs-editor-content');
			await expect(content).toBeVisible();
			await content.click();
			await page.keyboard.press('ControlOrMeta+a');
			await page.keyboard.type('Why privacy matters');
			await viewer.getByTestId('docs-editor-h2').click();
			await page.keyboard.press('End');
			await page.keyboard.press('Enter');
			await viewer.getByTestId('docs-editor-paragraph').click();
			await viewer.getByTestId('docs-editor-bold').click();
			await page.keyboard.type('Encrypted by default');
			await proof.assert('projects.items.create-documents.document.edit', async () => {
				await expect(content.locator('h2')).toContainText('Why privacy matters');
				await expect(content.locator('strong, b').first()).toContainText('Encrypted by default');
			});
			await proof.checkpoint('document-editing');
			const saved = revisionSaved(page);
			await finishEditing(page, 'docs-edit-button');
			await proof.assert('projects.items.create-documents.document.saved', async () => {
				expect((await saved).ok(), 'the document edit should be committed').toBe(true);
				await expect(viewer.getByTestId('docs-editor')).toHaveCount(0, { timeout: 30_000 });
				await expect(viewer.getByTestId('docs-editor-error')).toHaveCount(0);
				await expect(viewer).toContainText('Encrypted by default');
			});
			await proof.checkpoint('document-saved');

			const reopened = await reopenFile(page, projectId, 'Talk outline');
			await proof.assert('projects.items.create-documents.document.reloaded', async () => {
				await expect(reopened.locator('h2').filter({ hasText: 'Why privacy matters' }).first()).toBeVisible({ timeout: 30_000 });
				await expect(reopened).toContainText('Encrypted by default');
			});
			await proof.checkpoint('document-after-reload');
			await proof.attach();
		} finally {
			await deleteProject(page, projectId);
		}
	});

	// contract-test: direct surface=gui.web assertions=projects.items.create-documents
	test('creates a sheet, edits cells and reopens the saved version', async ({ page }: { page: any }) => {
		const proof = proofFor('sheet', page);
		const projectId = await createProject(page, 'Event budget');
		const cell = (id: string) => page.locator(`[data-testid="sheet-cell"][data-cell="${id}"]`);
		const setCell = async (id: string, value: string) => {
			await cell(id).click();
			const input = page.getByTestId('sheet-cell-input');
			await input.fill(value);
			await input.press('Enter');
		};
		try {
			await createFile(page, 'sheet', 'Budget');
			await startEditing(page, 'sheet-edit-toggle', 'sheet');
			const saved = revisionSaved(page);
			await setCell('A1', 'Venue');
			await setCell('B1', '1200');
			await proof.assert('projects.items.create-documents.sheet.edit', async () => {
				await expect(cell('A1')).toHaveText('Venue');
				await expect(cell('B1')).toHaveText('1200');
			});
			await proof.checkpoint('sheet-editing');
			await proof.assert('projects.items.create-documents.sheet.saved', async () => {
				await finishEditing(page, 'sheet-edit-toggle');
				await expect(page.getByTestId('sheet-save-status')).toHaveAttribute('data-state', 'saved', { timeout: 60_000 });
				expect((await saved).ok(), 'the sheet edit should be committed').toBe(true);
				await expect(page.getByTestId('sheet-cell-input')).toHaveCount(0);
			});
			await proof.checkpoint('sheet-saved');

			await reopenFile(page, projectId, 'Budget');
			await proof.assert('projects.items.create-documents.sheet.reloaded', async () => {
				await expect(cell('A1')).toHaveText('Venue', { timeout: 30_000 });
				await expect(cell('B1')).toHaveText('1200');
			});
			await proof.checkpoint('sheet-after-reload');
			await proof.attach();
		} finally {
			await deleteProject(page, projectId);
		}
	});

	// contract-test: direct surface=gui.web assertions=projects.items.create-documents
	test('creates a slide deck, edits the title and reopens the saved version', async ({ page }: { page: any }) => {
		const proof = proofFor('slides', page);
		const projectId = await createProject(page, 'Product launch');
		const editor = () => page.getByTestId('slides-editor');
		try {
			await createFile(page, 'slides', 'Launch deck');
			const viewer = page.getByTestId('project-embed-viewer');
			await expect(viewer.getByTestId('slides-deck-fullscreen')).toBeVisible({ timeout: 30_000 });
			await startEditing(page, 'slides-edit', 'slides');
			await expect(editor()).toHaveAttribute('data-status', 'ready', { timeout: 60_000 });
			await expect(page.getByTestId('slides-editor-done'), 'Done lives in the header').toHaveCount(0);
			await page.getByTestId('slides-editor-element').first().dblclick();
			const input = page.getByTestId('slides-editor-text-input');
			await expect(input).toBeFocused();
			await page.keyboard.press('ControlOrMeta+a');
			await page.keyboard.type('Launch day');
			await page.keyboard.press('Escape');
			await proof.assert('projects.items.create-documents.slides.edit', async () => {
				await expect(editor()).toHaveAttribute('data-dirty', 'true');
				await expect(page.getByTestId('slides-editor-canvas').getByTestId('slide-canvas')).toContainText('Launch day');
			});
			await proof.checkpoint('slides-editing');
			const saved = revisionSaved(page);
			await finishEditing(page, 'slides-edit');
			await proof.assert('projects.items.create-documents.slides.saved', async () => {
				expect((await saved).ok(), 'the deck edit should be committed').toBe(true);
				await expect(editor()).toHaveCount(0, { timeout: 30_000 });
				await expect(page.getByTestId('slides-editor-save-failed')).toHaveCount(0);
				await expect(viewer.getByTestId('slide-canvas').first()).toContainText('Launch day');
			});
			await proof.checkpoint('slides-saved');

			const reopened = await reopenFile(page, projectId, 'Launch deck');
			await proof.assert('projects.items.create-documents.slides.reloaded', async () => {
				await expect(reopened.getByTestId('slide-canvas').first()).toContainText('Launch day', { timeout: 30_000 });
			});
			await proof.checkpoint('slides-after-reload');
			await proof.attach();
		} finally {
			await deleteProject(page, projectId);
		}
	});

	// contract-test: direct surface=gui.web assertions=projects.items.create-documents
	test('creates a code file, edits it and reopens the saved version', async ({ page }: { page: any }) => {
		const proof = proofFor('code', page);
		const projectId = await createProject(page, 'Weather station');
		const code = 'def greet(name):\n  return f"Hello, {name}!"\n\nprint(greet("OpenMates"))';
		try {
			await createFile(page, 'code', 'greet.py');
			const viewer = page.getByTestId('project-embed-viewer');
			await startEditing(page, 'code-edit-button', 'code');
			await expect(viewer.getByTestId('code-editor-save'), 'Save lives in the header').toHaveCount(0);
			const textarea = viewer.getByTestId('code-editor-textarea');
			await expect(textarea).toBeVisible();
			await textarea.fill(code);
			await proof.assert('projects.items.create-documents.code.edit', async () => {
				await expect(textarea).toHaveValue(code);
			});
			await proof.checkpoint('code-editing');
			const saved = revisionSaved(page);
			await finishEditing(page, 'code-edit-button');
			await proof.assert('projects.items.create-documents.code.saved', async () => {
				expect((await saved).ok(), 'the code edit should be committed').toBe(true);
				await expect(viewer.getByTestId('code-editor')).toHaveCount(0, { timeout: 30_000 });
				await expect(viewer).toContainText('print(greet("OpenMates"))');
			});
			await proof.checkpoint('code-saved');

			const reopened = await reopenFile(page, projectId, 'greet.py');
			await proof.assert('projects.items.create-documents.code.reloaded', async () => {
				await expect(reopened).toContainText('print(greet("OpenMates"))', { timeout: 30_000 });
				await expect(reopened).toContainText('def greet(name):');
			});
			await proof.checkpoint('code-after-reload');
			await proof.attach();
		} finally {
			await deleteProject(page, projectId);
		}
	});

	// contract-test: direct surface=gui.web assertions=projects.items.create-documents
	test('every Create menu item is created in the open subfolder', async ({ page }: { page: any }) => {
		// Six creations, a reload and the cleanup take longer than one file's flow.
		test.setTimeout(480_000);
		const projectId = await createProject(page, 'Venue research');
		const panel = page.getByTestId('project-folders-panel');
		const card = (name: string) => page.getByTestId('project-item-card').filter({ hasText: name });
		const folderCard = (name: string) => page.getByTestId('project-folder-card').filter({ hasText: name });
		const openFolder = async (name: string) => {
			await folderCard(name).first().click();
			await expect(panel.getByRole('heading', { name })).toBeVisible({ timeout: 30_000 });
		};
		const openMenu = async () => {
			await page.getByTestId('project-folder-create-menu-button').click();
			await expect(page.getByTestId('project-create-menu')).toBeVisible();
		};
		/** Create a folder in the open folder; resolves with its id from the request. */
		const createFolder = async (name: string): Promise<string> => {
			await openMenu();
			await page.getByTestId('project-create-folder').click();
			await page.getByTestId('project-create-name-input').fill(name);
			const created = page.waitForResponse((response: any) => response.request().method() === 'POST'
				&& new URL(response.url()).pathname === `/v1/projects/${projectId}/folders`, { timeout: 30_000 });
			await page.getByTestId('project-create-name-submit').click();
			const response = await created;
			expect(response.ok(), 'the folder should be stored').toBe(true);
			await expect(folderCard(name).first()).toBeVisible({ timeout: 30_000 });
			return response.request().postDataJSON().folder_id as string;
		};
		const files: { kind: Kind; name: string }[] = [
			{ kind: 'document', name: 'Venue checklist' },
			{ kind: 'sheet', name: 'Catering quotes' },
			{ kind: 'slides', name: 'Venue pitch' },
			{ kind: 'code', name: 'compare.py' },
		];
		try {
			await openFiles(page);
			const quotesId = await createFolder('Quotes');
			await openFolder('Quotes');
			const caterersId = await createFolder('Caterers');
			expect(caterersId).not.toBe(quotesId);
			await openFolder('Caterers');

			await openMenu();
			for (const id of ['chat', 'workflow', 'plan', 'folder', 'document', 'sheet', 'slides', 'code']) {
				await expect(page.getByTestId(`project-create-${id}`).first(), `Create menu offers ${id}`).toBeVisible();
			}
			await shot(page, 'subfolder-create-menu');
			await page.getByTestId('project-folder-create-menu-button').click();

			for (const file of files) {
				await openMenu();
				await page.getByTestId(`project-create-${file.kind}`).first().click();
				await page.getByTestId('project-create-name-input').fill(file.name);
				const stored = page.waitForResponse((response: any) => response.request().method() === 'POST'
					&& /\/v1\/projects\/[^/]+\/upload-embed$/.test(new URL(response.url()).pathname), { timeout: 30_000 });
				await page.getByTestId('project-create-name-submit').click();
				const response = await stored;
				expect(response.ok(), `${file.kind} should be stored`).toBe(true);
				// The Project item that places the new file rides in the same upload request.
				expect(response.request().postDataJSON().item?.folder_id, `${file.kind} is stored in the open subfolder`).toBe(caterersId);
				await expect(page.getByTestId('project-embed-viewer')).toBeVisible({ timeout: 30_000 });
				await expect(card(file.name).first()).toBeVisible({ timeout: 30_000 });
			}
			await shot(page, 'subfolder-files-created');

			// After a reload the files are in Caterers only: not in the root, not in Quotes.
			await page.goto(`/projects/${encodeURIComponent(projectId)}`, { waitUntil: 'domcontentloaded' });
			await expect(page.getByTestId('project-workspace-header')).toBeVisible({ timeout: 60_000 });
			await openFiles(page);
			await expect(folderCard('Quotes').first()).toBeVisible({ timeout: 60_000 });
			for (const file of files) await expect(card(file.name)).toHaveCount(0);
			await openFolder('Quotes');
			await expect(folderCard('Caterers').first()).toBeVisible({ timeout: 30_000 });
			for (const file of files) await expect(card(file.name)).toHaveCount(0);
			await openFolder('Caterers');
			for (const file of files) await expect(card(file.name).first()).toBeVisible({ timeout: 30_000 });
			await shot(page, 'subfolder-after-reload');

			// A new workflow from the subfolder is filed in that folder.
			await openMenu();
			await page.getByTestId('project-create-workflow').click();
			await expect(page.getByTestId('workflow-blank-creator')).toBeVisible({ timeout: 30_000 });
			await page.getByTestId('workflow-blank-title-input').fill('Ask caterers for quotes');
			const linked = page.waitForResponse((response: any) => response.request().method() === 'POST'
				&& new URL(response.url()).pathname === `/v1/projects/${projectId}/items` && response.ok(), { timeout: 60_000 });
			await page.getByTestId('workflow-blank-create').click();
			expect((await linked).request().postDataJSON()).toMatchObject({ folder_id: caterersId, item_type: 'workflow' });

			// A new chat from the subfolder starts with that folder as its Project context.
			await page.goto(`/projects/${encodeURIComponent(projectId)}`, { waitUntil: 'domcontentloaded' });
			await expect(page.getByTestId('project-workspace-header')).toBeVisible({ timeout: 60_000 });
			await openFiles(page);
			await openFolder('Quotes');
			await openFolder('Caterers');
			await openMenu();
			await page.getByTestId('project-create-chat').click();
			const messageEditor = page.getByTestId('message-editor');
			await expect(messageEditor).toBeVisible({ timeout: 30_000 });
			await page.getByTestId('message-field').click();
			const mention = messageEditor.locator('[data-type="generic-mention"].mention-project-folder');
			await expect(mention).toBeVisible({ timeout: 10_000 });
			const syntax = await mention.getAttribute('data-mention-syntax');
			expect(syntax, 'the chat targets the subfolder').toMatch(new RegExp(`^@project-folder:${projectId}:[^:]*Caterers:`));
			await shot(page, 'subfolder-new-chat');
		} finally {
			await deleteProject(page, projectId);
		}
	});
});
