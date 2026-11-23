/* eslint-disable @typescript-eslint/no-require-imports -- spec helpers are CommonJS, shared with other specs */
export {};

/**
 * Project tiles get a description, icon and category gradient (TASK-1807), on the
 * web app with the Rust client core, real isolated stack.
 *
 * Specification: feature.projects `projects.presentation.*`. A Project without
 * presentation state (as every Project from before the feature, or one named by
 * hand on the start screen) that has one file is described once
 * when the Projects workspace opens: the client sends the Project's decrypted
 * context to the suggest route, the core plans the write, and the client stores
 * only ciphertext. A manual icon change in Project settings is then kept.
 *
 * Isolated CI has no AI inference, so the browser forwards the suggest request to
 * the real backend (which must accept the session and the bounded body) and answers
 * with a fixed proposal in place of the model's reply. Everything else is real:
 * encryption, the core decisions, the PATCH and the tiles.
 *
 * Run: ci_coordinator.py submit --mode e2e --spec projects-presentation-flow.spec.ts
 */

const { test, expect } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled, skipWithoutCredentials } = require('./helpers/env-guard');
const { getTestAccount } = require('./signup-flow-helpers');
const { naturalProjectName } = require('./helpers/project-names');
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

const PROPOSAL = {
	description: 'Weekly meal plans and the recipes behind them.',
	icon: 'chef-hat',
	category: 'cooking_food',
};
const PROOF_DEVICES = ['web-laptop'];
const proofContract = defineVideoProof({
	id: 'projects-presentation-backfill',
	title: 'A Project without presentation gets a description, icon and category on its tile',
	surface: 'web',
	devices: PROOF_DEVICES,
	domain: 'app.dev.openmates.org',
	transcript: [
		{ id: 'before', text: 'A Project without presentation yet: plain folder tile, no description.', checkpoint: 'before', devices: PROOF_DEVICES },
		{ id: 'backfilled', text: 'Opening the Projects workspace describes it once: description, chef hat and the cooking colours.', checkpoint: 'backfilled', devices: PROOF_DEVICES },
		{ id: 'manual-icon', text: 'An icon chosen by hand in Project settings stays after a reload.', checkpoint: 'manual-icon', devices: PROOF_DEVICES },
	],
	assertions: [
		{ id: 'projects.presentation.backfill.tile', checkpoint: 'backfilled', visual: 'The tile shows the one-line description, the chef hat icon and the cooking gradient.', devices: PROOF_DEVICES },
		{ id: 'projects.presentation.manual-lock.icon', checkpoint: 'manual-icon', visual: 'The tile shows the book icon chosen by hand.', devices: PROOF_DEVICES },
	],
	tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 },
});

async function shot(page: any, name: string): Promise<void> {
	await test.info().attach(name, { body: await page.screenshot(), contentType: 'image/png' });
}

async function createProject(page: any, name: string): Promise<string> {
	await page.goto('/projects');
	await expect(page.getByTestId('projects-page')).toBeVisible({ timeout: 30_000 });
	const created = page.waitForResponse((response: any) => response.request().method() === 'POST'
		&& new URL(response.url()).pathname === '/v1/projects' && response.ok());
	await page.getByTestId('project-input-textarea').fill(name);
	await page.getByTestId('project-input-submit').click();
	await page.getByTestId('project-write-policy-apply-and-show').check();
	await page.getByTestId('project-write-policy-confirm').click();
	const projectId = (await (await created).json()).project.project_id as string;
	await expect(page.getByTestId('project-workspace-header')).toBeVisible({ timeout: 30_000 });
	return projectId;
}

async function createDocument(page: any, name: string): Promise<void> {
	await page.getByTestId('project-tab-folders').click();
	await expect(page.getByTestId('project-folders-panel')).toBeVisible({ timeout: 30_000 });
	await page.getByTestId('project-folder-create-menu-button').click();
	await page.getByTestId('project-create-document').first().click();
	await page.getByTestId('project-create-name-input').fill(name);
	const stored = page.waitForResponse((response: any) => response.request().method() === 'POST'
		&& /\/v1\/projects\/[^/]+\/upload-embed$/.test(new URL(response.url()).pathname), { timeout: 30_000 });
	await page.getByTestId('project-create-name-submit').click();
	expect((await stored).ok(), 'the Project file should be stored').toBe(true);
	await expect(page.getByTestId('project-item-card').filter({ hasText: name }).first()).toBeVisible({ timeout: 30_000 });
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

function projectPatch(page: any, projectId: string) {
	return page.waitForResponse((response: any) => response.request().method() === 'PATCH'
		&& new URL(response.url()).pathname === `/v1/projects/${projectId}` && response.ok(), { timeout: 60_000 });
}

test.describe('Project tile presentation', () => {
	test.describe.configure({ timeout: 300_000 });

	test.beforeEach(async ({ page }: { page: any }) => {
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
		await skipIfFeaturesDisabled(test, page, ['platform:projects']);
		await page.setViewportSize({ width: 1440, height: 1000 });
		await loginToTestAccount(page);
	});

	// contract-test: direct surface=gui.web assertions=projects.presentation.backfill,projects.presentation.encrypted,projects.presentation.suggest-route,projects.presentation.manual-lock,projects.presentation.tile
	test('a Project without presentation is described once from its content and a manual icon is kept', async ({ page }: { page: any }) => {
		const testInfo = test.info();
		const proof = createVideoProofRuntime(proofContract, {
			device: 'web-laptop', attach: testInfo.attach.bind(testInfo), captureFrame: () => page.screenshot({ type: 'png' }),
		});
		const name = naturalProjectName('Meal planning');
		const suggestions: any[] = [];
		const backendStatuses: number[] = [];
		await page.route('**/v1/projects/presentation/suggest', async (route: any) => {
			const body = route.request().postDataJSON();
			if (body.name !== name) return route.continue();
			suggestions.push(body);
			// The real route must accept the session and this bounded body; only the model's reply is fixed.
			const real = await route.fetch();
			backendStatuses.push(real.status());
			await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ presentation: PROPOSAL }) });
		});
		const projectId = await createProject(page, name);
		try {
			await createDocument(page, 'Weekly menu');
			const tile = () => page.getByTestId('project-landing-card').filter({ hasText: name }).first();

			const backfillPatch = projectPatch(page, projectId);
			await page.goto('/projects');
			await expect(tile()).toBeVisible({ timeout: 30_000 });
			await proof.checkpoint('before');
			const patch = await backfillPatch;
			const body = JSON.stringify(patch.request().postDataJSON());
			expect(body).toContain('encrypted_category');
			expect(body).toContain('encrypted_presentation_state');
			for (const plaintext of [PROPOSAL.description, PROPOSAL.category, PROPOSAL.icon, 'backfill']) expect(body).not.toContain(plaintext);
			expect(suggestions).toHaveLength(1);
			expect(suggestions[0]).toMatchObject({ purpose: 'backfill', specification: null });
			expect(suggestions[0].item_names).toContain('Weekly menu');
			expect(backendStatuses[0], 'the suggest route must accept the session and body').not.toBe(401);
			expect(backendStatuses[0]).not.toBe(422);

			await proof.assert('projects.presentation.backfill.tile', async () => {
				await expect(tile()).toContainText(PROPOSAL.description, { timeout: 30_000 });
				await expect(tile()).toHaveAttribute('data-category', 'cooking_food');
				await expect(tile()).toHaveAttribute('data-icon', 'chef-hat');
			});
			await shot(page, 'backfilled-project-tile');
			await proof.checkpoint('backfilled');

			// Once per Project: after a reload the Project has a state, so nothing is asked again.
			await page.reload();
			await expect(tile()).toContainText(PROPOSAL.description, { timeout: 30_000 });
			await page.waitForTimeout(3_000);
			expect(suggestions).toHaveLength(1);

			await tile().click();
			await expect(page.getByTestId('project-workspace-header')).toBeVisible({ timeout: 30_000 });
			await page.getByTestId('project-more-button').click();
			await page.getByTestId('project-settings-button').click();
			const iconSelect = page.getByTestId('project-appearance-icon');
			await expect(iconSelect).toHaveValue('chef-hat', { timeout: 30_000 });
			const manualPatch = projectPatch(page, projectId);
			await iconSelect.selectOption('book-open');
			expect(JSON.stringify((await manualPatch).request().postDataJSON())).not.toContain('book-open');
			await shot(page, 'manual-icon-settings');

			await page.goto('/projects');
			await proof.assert('projects.presentation.manual-lock.icon', async () => {
				await expect(tile()).toHaveAttribute('data-icon', 'book-open', { timeout: 30_000 });
				await expect(tile()).toHaveAttribute('data-category', 'cooking_food');
			});
			await shot(page, 'manual-icon-tile');
			await proof.checkpoint('manual-icon');
			expect(suggestions).toHaveLength(1);
			await proof.attach();
		} finally {
			await deleteProject(page, projectId);
		}
	});
});
