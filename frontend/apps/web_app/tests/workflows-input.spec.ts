/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
import type { Page, Route } from '@playwright/test';
/**
 * Workflows input home coverage.
 *
 * Purpose: verifies the deployed Workflows landing keeps Daily Inspiration,
 * renders owned workflows on home, browses executable templates, and returns to the created workflow
 * after the workflow-input session reports a committed result.
 * Security: uses the shared E2E account and deletes only workflows created by
 * this spec run.
 */

const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

function deriveApiUrl(baseUrl: string): string {
	try {
		const url = new URL(baseUrl);
		if (url.hostname === 'openmates.org' || url.hostname === 'www.openmates.org') return 'https://api.openmates.org';
		if (url.hostname.startsWith('app.')) return `${url.protocol}//api.${url.hostname.slice(4)}`;
		if (url.hostname === 'localhost') return 'http://localhost:8000';
	} catch {
		// Fall through to the production API default.
	}
	return 'https://api.openmates.org';
}

function sseSession(session: Record<string, unknown>): string {
	return `data: ${JSON.stringify({ type: 'session', session })}\n\n`;
}

function blankWorkflowGraph(index: number) {
	return {
		version: 1,
		trigger_node_id: 'trigger',
		nodes: [
			{
				id: 'trigger',
				type: 'schedule_trigger',
				title: `Spec schedule ${index}`,
				config: { schedule: { type: 'daily', time: '09:00', timezone: 'Europe/Berlin' } }
			},
			{ id: 'message', type: 'send_chat_message', title: 'Spec message', config: { title: 'Spec message', message: 'Ready' } },
			{ id: 'end', type: 'end', title: 'Done', config: {} }
		],
		edges: [{ from: 'trigger', to: 'message' }, { from: 'message', to: 'end' }]
	};
}

test.use({
	launchOptions: { args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] },
	permissions: ['microphone']
});

test.describe('Workflows input home', () => {
	// contract-test: supporting surface=gui.web assertions=workflows-ui.workspace.recommendation-led-composition,workflows-ui.workspace.title-first-draft,workflows-ui.mvp.authoring
	test('opens a committed AI workflow and returns without a New pill', async ({ page }: { page: Page }) => {
		test.setTimeout(240000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:workflows']);

		const apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
		const createdWorkflowIds = new Set<string>();
		const log = (message: string, metadata: Record<string, unknown> = {}) => {
			console.log(`[WORKFLOWS_INPUT_E2E] ${message} ${JSON.stringify(metadata)}`);
		};
		const screenshot = async () => {};
		let committedWorkflow: Record<string, unknown> | null = null;

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page, log, screenshot);

		try {
			for (let index = 0; index < 6; index += 1) {
				const title = `Input spec seed ${Date.now()} ${index}`;
				const response = await page.request.post(`${apiUrl}/v1/workflows`, {
					data: {
						title,
						graph: blankWorkflowGraph(index),
						enabled: index < 3,
						run_content_retention: index % 2 === 0 ? 'last_5' : 'none'
					}
				});
				expect(response.ok(), await response.text()).toBe(true);
				const data = await response.json();
				createdWorkflowIds.add(data.workflow.id);
				if (index === 5) committedWorkflow = data.workflow;
			}

			await page.setViewportSize({ width: 1024, height: 844 });
			await page.goto(getE2EDebugUrl('/workflows'), { waitUntil: 'domcontentloaded' });
			await expect(page.getByTestId('workflows-page')).toBeVisible({ timeout: 30000 });
			await expect(page.getByTestId('chats-nav-link')).toBeVisible();
			await expect(page.getByTestId('workflows-nav-link')).toBeVisible();
			await expect(page.getByTestId('workflows-nav-link')).toHaveAttribute('aria-current', 'page');
			await page.setViewportSize({ width: 390, height: 844 });
			await expect(page.getByTestId('workflows-start-screen')).toBeVisible();
			await expect(page.getByTestId('daily-inspiration-banner')).toBeVisible();
			await expect(page.getByTestId('daily-inspiration-label')).toBeVisible();
			await expect(page.getByTestId('workflow-inspiration-card')).toHaveCount(0);
			await expect(page.getByTestId('workflow-management')).toHaveCount(0);
			await expect(page.getByTestId('workflows-workspace-center')).toContainText('Hey');
			await expect(page.getByTestId('workflows-workspace-center')).toContainText('What do you want to automate next?');
			const mixedRow = page.getByTestId('workflow-mixed-row');
			await expect(mixedRow).toBeVisible();
			await expect(page.getByTestId('recent-workflows')).toHaveCount(0);
			await expect(page.getByText('Continue where you left off', { exact: true })).toHaveCount(0);
			const mixedCards = mixedRow.getByTestId('workflow-landing-card');
			await expect(mixedCards).toHaveCount(6, { timeout: 30000 });
			await expect(mixedCards.first()).toHaveAttribute('data-card-source', 'recent');
			await expect(mixedCards.last()).toHaveAttribute('data-card-source', 'recent');
			await expect(page.getByTestId('workflows-show-all')).toHaveText('Show my workflows');
			await expect(page.getByTestId('workflows-show-templates')).toHaveText('Show templates');
			await expect(page.getByTestId('workflows-show-all')).toBeVisible();
			await expect(page.getByTestId('workflows-search')).toBeVisible();
			await expect(page.getByTestId('workflow-input-composer')).toBeVisible();
			await expect(page.getByTestId('workflow-input-submit')).toHaveCount(0);
			await expect(page.getByTestId('workflow-input-mic')).toBeVisible();
			await expect(page.getByTestId('message-editor')).toHaveCount(0);
			await expect(page.getByTestId('workflow-input-textarea')).toHaveCSS('text-align', 'center');

			const startScreenBox = await page.getByTestId('workflows-start-screen').boundingBox();
			const composerBox = await page.getByTestId('workflow-input-composer').boundingBox();
			const centerBox = await page.getByTestId('workflows-workspace-center').boundingBox();
			if (!startScreenBox || !composerBox || !centerBox) throw new Error('Workflows home sections must be measurable.');
			expect(startScreenBox.height).toBeGreaterThan(700);
			expect(composerBox.y + composerBox.height).toBeGreaterThan(760);
			expect(centerBox.y + centerBox.height).toBeLessThan(composerBox.y);

			await page.getByTestId('workflows-show-all').click();
			await expect(page.getByTestId('workflow-mixed-row')).toHaveCount(0);
			await expect(page.getByTestId('recent-workflows')).toHaveCount(0);
			await expect(page.getByTestId('daily-inspiration-banner')).toHaveCount(0);
			await expect(page.getByTestId('workflows-all-toolbar')).toBeVisible();
			await expect(page.getByTestId('workflows-back-to-recent')).toBeVisible();
			await expect(page.getByTestId('workflows-search')).toBeVisible();
			await expect(page.getByTestId('workflows-search')).toBeEnabled();
			await expect(page.getByTestId('all-workflows-grid')).toBeVisible();
			await expect(page.getByTestId('workflows-sort')).toHaveValue('recent');
			await page.getByTestId('workflows-sort').selectOption('running-next');
			await expect(page.getByTestId('workflows-sort')).toHaveValue('running-next');
			await expect(page.getByTestId('workflow-input-composer')).toBeVisible();
			await expect.poll(async () => page.getByTestId('all-workflows-grid').evaluate((element: HTMLElement) => element.scrollHeight > element.clientHeight), { timeout: 15000 }).toBe(true);
			const allGridBox = await page.getByTestId('all-workflows-grid').boundingBox();
			const allComposerBox = await page.getByTestId('workflow-input-composer').boundingBox();
			if (!allGridBox || !allComposerBox) throw new Error('All workflows grid and composer must be measurable.');
			// Rounded scroll-container borders can extend about one CSS pixel under
			// the fixed composer without hiding a control or card.
			expect(allGridBox.y + allGridBox.height).toBeLessThanOrEqual(allComposerBox.y + 2);

			await page.getByTestId('workflows-back-to-recent').click();
			await expect(page.getByTestId('workflow-mixed-row')).toBeVisible();
			await expect(page.getByTestId('recent-workflows')).toHaveCount(0);
			await expect(page.getByTestId('all-workflows-grid')).toHaveCount(0);

			if (!committedWorkflow) throw new Error('Seed workflow missing');
			const saved = committedWorkflow;
			const preview = { ...saved, title: 'Daily school weather preview', description: 'A proposed weather briefing before school.' };
			const validatedPreviewGraph = { ...(saved.graph as Record<string, unknown>), version: 2 };
			let allowCommit = false;
			await page.route('**/v1/workflows/input/workflow-input-spec', async (route: Route) => {
				await route.fulfill({ status: 200, contentType: 'application/json', headers: { 'access-control-allow-origin': new URL(page.url()).origin, 'access-control-allow-credentials': 'true' }, body: JSON.stringify({ session: allowCommit
					? { session_id: 'workflow-input-spec', status: 'executed', workflow: saved, undo_available: true, assumptions: ['Runs at 09:00 Berlin time.'], mutations: [{ type: 'create_workflow', target_id: saved.id }] }
					: { session_id: 'workflow-input-spec', status: 'queued', message: 'Workflow prepared. Saving now.', preview_workflow: preview }
				}) });
			});
			await page.route('**/v1/workflows/input/stream', async (route: Route) => {
				if (route.request().method() !== 'POST') return route.continue();
				const payload = route.request().postDataJSON();
				expect(payload.text).toBe('Daily school weather');
				expect(payload.timezone).toBeTruthy();
				expect(payload.optimistic_save).toBe(true);
				const validatedPreview = { type: 'preview', provisional: true, validated: true, workflow_index: 0, operation: 'create', graph: validatedPreviewGraph, accepted_node_count: (validatedPreviewGraph.nodes as unknown[]).length, metadata: { title: preview.title, description: preview.description, category: saved.category, icon: saved.icon } };
				await route.fulfill({ status: 200, contentType: 'text/event-stream', headers: { 'access-control-allow-origin': new URL(page.url()).origin, 'access-control-allow-credentials': 'true' }, body: `data: ${JSON.stringify({ type: 'started', session_id: 'workflow-input-spec', status: 'running' })}\n\n` + `data: ${JSON.stringify(validatedPreview)}\n\n` + sseSession({
					session_id: 'workflow-input-spec', status: 'queued', message: 'Workflow prepared. Saving now.', preview_workflow: preview
				}) });
			});
			await page.getByTestId('workflow-input-textarea').focus();
			await expect(page.getByTestId('workflow-input-submit')).toHaveCount(0);
			await page.getByTestId('workflow-input-textarea').fill('Daily school weather');
			await expect(page.getByTestId('workflow-input-submit')).toBeVisible();
			await expect(page.getByTestId('workflow-input-submit')).toBeEnabled();
			await page.getByTestId('workflow-input-submit').click();
			await expect(page.getByTestId('workflow-ai-pending')).toContainText('Saving now');
			await expect(page.getByTestId('workspace-detail-title')).toHaveText('Daily school weather preview');
			await expect(page.getByTestId('workspace-detail-description')).toContainText('proposed weather briefing');
			const provisionalGraph = page.getByTestId('workflow-ai-pending-preview');
			await expect(provisionalGraph).toBeVisible();
			await expect(provisionalGraph.getByTestId('workflow-node-card')).not.toHaveCount(0);
			await expect(page.getByTestId('workflow-ai-processing')).toContainText('Saving now');
			await expect(provisionalGraph).toHaveAttribute('data-disabled', 'true');
			await expect(page.getByTestId('toggle-workflow')).toBeDisabled();
			await expect(provisionalGraph.getByTestId('workflow-node-save')).toHaveCount(0);
			await expect(page.getByTestId('workflow-new-pill')).toHaveCount(0);
			allowCommit = true;
			await expect(page.getByTestId('workflow-ai-pending-preview')).toHaveCount(0);
			const management = page.getByTestId('workflow-management');
			await expect(management).toBeVisible();
			await expect(page.getByTestId('workspace-detail-title')).toHaveText(String(saved.title));
			await management.evaluate(async (element: HTMLElement) => {
				await Promise.all(element.getAnimations().map((animation) => animation.finished));
			});
			const info = page.getByTestId('workflow-authoring-info');
			await expect(info).toContainText('Runs at 09:00 Berlin time.');
			await expect(info).toContainText('Activate this workflow');
			await expect(info.getByTestId('workflow-ai-created-undo')).toBeVisible();
			const infoBox = await info.boundingBox();
			const firstNodeBox = await page.locator('[data-testid="workflow-node-card"][data-node-id="trigger"]').boundingBox();
			if (!infoBox || !firstNodeBox) throw new Error('Workflow info and first node must be measurable.');
			expect(infoBox.y + infoBox.height).toBeLessThan(firstNodeBox.y);
			const editorComposer = page.getByTestId('workflow-ai-editor-composer');
			await expect(editorComposer).toBeVisible();
			await expect(page.getByTestId('workflow-ai-edit-textarea')).toHaveAttribute('placeholder', 'Describe workflow change.');
			const dockSurface = await editorComposer.evaluate((element: HTMLElement) => {
				const style = getComputedStyle(element);
				return { backgroundImage: style.backgroundImage, backgroundColor: style.backgroundColor };
			});
			expect(dockSurface.backgroundImage).toContain('linear-gradient');
			expect(dockSurface.backgroundColor).toBe('rgba(0, 0, 0, 0)');
			const editInput = page.getByTestId('workflow-ai-edit-textarea');
			await expect.poll(() => editInput.evaluate((element: HTMLTextAreaElement) => element.scrollHeight)).toBeLessThanOrEqual(30);
			const [scrollBox, fadeBox] = await Promise.all([management.locator('.management-grid').boundingBox(), editorComposer.boundingBox()]);
			if (!scrollBox || !fadeBox) throw new Error('Scrolling content and composer fade must be measurable.');
			expect(fadeBox.y).toBeLessThan(scrollBox.y + scrollBox.height);
			const dockedBeforeScroll = await editorComposer.boundingBox();
			if (!dockedBeforeScroll) throw new Error('Workflow editor composer must be measurable.');
			expect(844 - dockedBeforeScroll.y - dockedBeforeScroll.height).toBeLessThan(32);
			await management.locator('.management-grid').evaluate((element: HTMLElement) => { element.scrollTop = element.scrollHeight; });
			const dockedAfterScroll = await editorComposer.boundingBox();
			expect(Math.abs((dockedAfterScroll?.y ?? 0) - dockedBeforeScroll.y)).toBeLessThan(2);
			await management.screenshot({ path: test.info().outputPath('workflow-change-composer-fade-phone.png') });
			await page.getByTestId('workflow-detail-back').click();
			await expect(page.getByTestId('workflows-start-screen')).toBeVisible();
			await expect(page.getByTestId('workflow-ai-created-undo')).toHaveCount(0);
			const newCard = page.getByTestId('workflow-mixed-row').getByTestId('workflow-landing-card').filter({ hasText: String(saved.title) });
			await expect(newCard).toBeVisible();
			await expect(page.getByTestId('workflow-new-pill')).toHaveCount(0);
			await expect(page.getByTestId('workflow-management')).toHaveCount(0);

			const shortRequest = `School weather ${Date.now()}`;
			const draftResponse = await page.request.post(`${apiUrl}/v1/workflows`, { data: {
				title: shortRequest,
				graph: { version: 2, trigger_node_id: 'manual', nodes: [{ id: 'manual', type: 'manual_trigger', title: 'Manual start', config: {} }], edges: [] },
				enabled: false
			} });
			expect(draftResponse.ok()).toBe(true);
			const draft = (await draftResponse.json()).workflow;
			createdWorkflowIds.add(draft.id);
			await page.unroute('**/v1/workflows/input/stream');
			await page.route('**/v1/workflows/input/stream', async (route: Route) => {
				if (route.request().method() !== 'POST') return route.continue();
				expect(route.request().postDataJSON().text).toBe(shortRequest);
				await route.fulfill({ status: 200, contentType: 'text/event-stream', headers: { 'access-control-allow-origin': new URL(page.url()).origin, 'access-control-allow-credentials': 'true' }, body: sseSession({
					session_id: 'workflow-draft-spec', status: 'draft', workflow: draft
				}) });
			});
			await page.getByTestId('workflow-input-textarea').fill(shortRequest);
			await page.getByTestId('workflow-input-submit').click();
			await expect(page.getByTestId('workspace-detail-title')).toHaveText(shortRequest);
			await expect(page.getByTestId('workflow-management')).toBeVisible();

			const editedPreview = { ...draft, title: `${shortRequest} revised`, description: 'A validated edit awaiting save.' };
			let failEditorSave = false;
			await page.route('**/v1/workflows/input/workflow-editor-preview-spec', async (route: Route) => {
				await route.fulfill({ status: 200, contentType: 'application/json', headers: { 'access-control-allow-origin': new URL(page.url()).origin, 'access-control-allow-credentials': 'true' }, body: JSON.stringify({ session: failEditorSave
					? { session_id: 'workflow-editor-preview-spec', status: 'failed', error: 'Could not save the workflow.' }
					: { session_id: 'workflow-editor-preview-spec', status: 'queued', message: 'Workflow prepared. Saving now.', preview_workflow: editedPreview }
				}) });
			});
			await page.unroute('**/v1/workflows/input/stream');
			await page.route('**/v1/workflows/input/stream', async (route: Route) => {
				if (route.request().method() !== 'POST') return route.continue();
				const payload = route.request().postDataJSON();
				expect(payload.selected_workflow_id).toBe(draft.id);
				expect(payload.optimistic_save).toBe(true);
				await route.fulfill({ status: 200, contentType: 'text/event-stream', headers: { 'access-control-allow-origin': new URL(page.url()).origin, 'access-control-allow-credentials': 'true' }, body: sseSession({
					session_id: 'workflow-editor-preview-spec', status: 'queued', message: 'Workflow prepared. Saving now.', preview_workflow: editedPreview
				}) });
			});
			await page.getByTestId('workflow-ai-edit-textarea').fill('Revise this workflow');
			await page.getByTestId('workflow-ai-edit-submit').click();
			await expect(page.getByTestId('workflow-ai-pending-preview')).toBeVisible();
			await expect(page.getByTestId('workflow-ai-preview-title')).toHaveText(editedPreview.title);
			await expect(page.getByTestId('workflow-ai-preview-graph')).toBeVisible();
			await expect(page.getByTestId('workflow-ai-preview-graph').getByTestId('workflow-node-card')).not.toHaveCount(0);
			await expect(page.getByTestId('workflow-ai-saving-pill')).toBeVisible();
			failEditorSave = true;
			await expect(page.getByTestId('workflow-ai-pending-preview')).toHaveCount(0);
			await expect(page.getByTestId('workspace-detail-title')).toHaveText(shortRequest);
			await expect(page.getByTestId('workflows-error')).toContainText('Could not save the workflow.');

			const updatedWorkflow = {
				...draft,
				title: `${shortRequest} updated`,
				graph: {
					...draft.graph,
					nodes: [
						{ ...draft.graph.nodes[0], title: 'Manual start revised' },
						{ id: 'summary', type: 'send_chat_message', title: 'Summary delivered', config: { title: 'Summary delivered', message: 'Ready' } }
					],
					edges: [{ from: 'manual', to: 'summary' }]
				}
			};
			const changes = {
				workflow_id: draft.id,
				added_node_ids: ['summary'],
				edited_node_ids: ['manual'],
				removed_nodes: [{ id: 'retired', title: 'Old reminder' }]
			};
			let allowEditCommit = false;
			await page.route('**/v1/workflows/input/workflow-editor-success-spec', async (route: Route) => {
				await route.fulfill({ status: 200, contentType: 'application/json', headers: { 'access-control-allow-origin': new URL(page.url()).origin, 'access-control-allow-credentials': 'true' }, body: JSON.stringify({ session: allowEditCommit
					? { session_id: 'workflow-editor-success-spec', status: 'executed', workflow: updatedWorkflow, changes: [changes], undo_available: true, mutations: [{ type: 'update_workflow', target_id: draft.id, before: { graph: draft.graph }, after: { graph: updatedWorkflow.graph } }] }
					: { session_id: 'workflow-editor-success-spec', status: 'queued', message: 'Workflow prepared. Saving now.', preview_workflow: updatedWorkflow }
				}) });
			});
			let undoConflicts = true;
			await page.route('**/v1/workflows/input/workflow-editor-success-spec/undo', async (route: Route) => {
				await route.fulfill({ status: 200, contentType: 'application/json', headers: { 'access-control-allow-origin': new URL(page.url()).origin, 'access-control-allow-credentials': 'true' }, body: JSON.stringify({ session: undoConflicts
					? { session_id: 'workflow-editor-success-spec', status: 'executed', error_code: 'WORKFLOW_INPUT_UNDO_CONFLICT', error: 'A newer change prevents Undo.' }
					: { session_id: 'workflow-editor-success-spec', status: 'undone' }
				}) });
			});
			await page.unroute('**/v1/workflows/input/stream');
			const multilineEdit = 'Update the steps\nInclude a morning summary\nUse the earlier events';
			await page.route('**/v1/workflows/input/stream', async (route: Route) => {
				if (route.request().method() !== 'POST') return route.continue();
				const payload = route.request().postDataJSON();
				expect(payload.selected_workflow_id).toBe(draft.id);
				expect(payload.optimistic_save).toBe(true);
				expect(payload.text).toBe(multilineEdit);
				await route.fulfill({ status: 200, contentType: 'text/event-stream', headers: { 'access-control-allow-origin': new URL(page.url()).origin, 'access-control-allow-credentials': 'true' }, body: sseSession({
					session_id: 'workflow-editor-success-spec', status: 'queued', message: 'Workflow prepared. Saving now.', preview_workflow: updatedWorkflow
				}) });
			});
			await page.getByTestId('workflow-ai-edit-textarea').fill(multilineEdit);
			await page.getByTestId('workflow-ai-edit-textarea').press('Escape');
			await expect(page.getByTestId('workflow-ai-edit-textarea-preview')).toHaveText('Update the steps…');
			await expect(page.getByTestId('workflow-ai-edit-textarea')).toHaveValue(multilineEdit);
			await page.getByTestId('workflow-ai-edit-textarea').click();
			await page.getByTestId('workflow-ai-edit-textarea-expand').click();
			await expect(page.getByTestId('workflow-ai-edit-textarea-expand')).toHaveAttribute('aria-expanded', 'true');
			await expect(page.getByTestId('workflow-ai-edit-textarea')).toHaveValue(multilineEdit);
			await page.getByTestId('workflow-ai-edit-textarea').press('Escape');
			await page.getByTestId('workflow-ai-edit-submit').click();
			await expect(page.getByTestId('workflow-ai-preview-title')).toHaveText(updatedWorkflow.title);
			await expect(page.getByTestId('workflow-ai-preview-graph')).toBeVisible();
			await expect(page.getByTestId('workflow-ai-undo')).toHaveCount(0);
			allowEditCommit = true;
			await expect(page.getByTestId('workflow-ai-pending-preview')).toHaveCount(0);
			await expect(page.getByTestId('workspace-detail-title')).toHaveText(updatedWorkflow.title);
			await expect(page.getByTestId('workflow-ai-changes')).toContainText('Old reminder');
			await expect(page.locator('[data-testid="workflow-node-card"][data-node-id="manual"]')).toHaveAttribute('data-ai-change', 'edited');
			await expect(page.locator('[data-testid="workflow-node-card"][data-node-id="summary"]')).toHaveAttribute('data-ai-change', 'added');
			await expect(page.getByTestId('workflow-ai-undo')).toBeEnabled();
			await page.getByTestId('workflow-ai-undo').click();
			await expect(page.getByTestId('workflows-error')).toContainText('A newer change prevents Undo.');
			await expect(page.getByTestId('workflow-ai-open-history')).toBeVisible();
			await expect(page.getByTestId('workspace-detail-title')).toHaveText(updatedWorkflow.title);
			undoConflicts = false;
			await page.getByTestId('workflow-ai-undo').click();
			await expect(page.getByTestId('workflow-ai-changes')).toHaveCount(0);
			await expect(page.getByTestId('workspace-detail-title')).toHaveText(shortRequest);

			await page.getByTestId('workspace-detail-title').click();
			const identityInput = page.locator('.workflow-detail-header form input').first();
			await identityInput.fill(`${shortRequest} manual draft`);
			await page.getByTestId('workflow-ai-edit-textarea').fill('Change the schedule');
			await page.getByTestId('workflow-ai-edit-submit').click();
			await expect(page.getByTestId('workflow-unsaved-guard')).toBeVisible();
			await page.getByTestId('workflow-guard-stay').click();
			await expect(identityInput).toHaveValue(`${shortRequest} manual draft`);
			await page.getByTestId('workflow-detail-back').click();
			await expect(page.getByTestId('workflow-unsaved-guard')).toBeVisible();
			await page.getByTestId('workflow-guard-stay').click();
			await expect(identityInput).toHaveValue(`${shortRequest} manual draft`);
			await page.getByTestId('workflow-detail-back').click();
			await page.getByTestId('workflow-guard-discard').click();
			await expect(page.getByTestId('workflows-start-screen')).toBeVisible();
			await page.getByTestId('workflow-mixed-row').getByTestId('workflow-landing-card').filter({ hasText: shortRequest }).click();
			await expect(page.getByTestId('workspace-detail-title')).toHaveText(shortRequest);
			await page.getByTestId('workspace-detail-title').click();
			await page.locator('.workflow-detail-header form input').first().fill(`${shortRequest} manually saved`);
			await page.getByTestId('workflow-detail-back').click();
			await expect(page.getByTestId('workflow-unsaved-guard')).toBeVisible();
			await page.getByTestId('workflow-guard-save').click();
			await expect(page.getByTestId('workflows-start-screen')).toBeVisible();
			await expect(page.getByTestId('workflow-mixed-row').getByTestId('workflow-landing-card').filter({ hasText: `${shortRequest} manually saved` })).toBeVisible();

			const landingEdited = {
				...draft,
				title: `${shortRequest} retimed`,
				graph: { ...draft.graph, nodes: [{ ...draft.graph.nodes[0], title: 'Manual start retimed' }] }
			};
			await page.route(`**/v1/workflows/${draft.id}`, async (route: Route) => {
				if (route.request().method() !== 'GET') return route.continue();
				await route.fulfill({ status: 200, contentType: 'application/json', headers: { 'access-control-allow-origin': new URL(page.url()).origin, 'access-control-allow-credentials': 'true' }, body: JSON.stringify({ workflow: landingEdited }) });
			});
			await page.unroute('**/v1/workflows/input/stream');
			await page.route('**/v1/workflows/input/stream', async (route: Route) => {
				if (route.request().method() !== 'POST') return route.continue();
				expect(route.request().postDataJSON().selected_workflow_id).toBeFalsy();
				await route.fulfill({ status: 200, contentType: 'text/event-stream', headers: { 'access-control-allow-origin': new URL(page.url()).origin, 'access-control-allow-credentials': 'true' }, body: sseSession({
					session_id: 'workflow-landing-edit-spec', status: 'executed', workflow: landingEdited,
					changes: [{ workflow_id: draft.id, added_node_ids: [], edited_node_ids: ['manual'], removed_nodes: [] }],
					mutations: [{ type: 'update_workflow', target_id: draft.id, before: { graph: draft.graph }, after: { graph: landingEdited.graph } }]
				}) });
			});
			await page.getByTestId('workflow-input-textarea').fill(`Move ${shortRequest} to 8:30`);
			await page.getByTestId('workflow-input-submit').click();
			await expect(page.getByTestId('workspace-detail-title')).toHaveText(landingEdited.title);
			await expect(page.locator('[data-testid="workflow-node-card"][data-node-id="manual"]')).toHaveAttribute('data-ai-change', 'edited');
			await page.getByTestId('workflow-detail-back').click();
			await expect(page.getByTestId('workflows-start-screen')).toBeVisible();

		} finally {
			for (const workflowId of createdWorkflowIds) {
				await page.request.delete(`${apiUrl}/v1/workflows/${encodeURIComponent(workflowId)}`).catch(() => null);
			}
		}
	});

	// contract-test: direct surface=gui.web assertions=workflows-ui.mvp.authoring
	test('streams raw workflow voice requests, recovers transcription failures, and clarifies an edit', async ({ page }: { page: Page }) => {
		test.setTimeout(120000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:workflows']);
		// The clarification route can load a new document. Install this before
		// navigation so the handoff is captured in either document without AI calls.
		await page.addInitScript(() => {
			const captured = window as Window & { workflowClarificationPrefills?: Array<{ text: string; autoSend: boolean }> };
			captured.workflowClarificationPrefills = [];
			window.addEventListener('docsMessagePrefill', event => {
				captured.workflowClarificationPrefills?.push((event as CustomEvent<{ text: string; autoSend: boolean }>).detail);
				event.stopImmediatePropagation();
			}, { capture: true });
		});
		let transcriptionFails = false;
		let emptyTranscription = false;
		let clarifyNextSession = false;
		let rawFinalTranscript = 'Weather tomorrow at 08:00';
		let socketConnections = 0;
		await page.routeWebSocket(/\/v1\/apps\/audio\/realtime-transcription(?:\?|$)/, socket => {
			socketConnections += 1;
			expect(new URL(socket.url()).searchParams.get('correction_context')).toBe('workflow');
			let sentPreview = false;
			socket.send(JSON.stringify({ type: 'session.ready', model: 'voxtral-mini-transcribe-realtime-2602', sample_rate: 16000 }));
			socket.onMessage(rawMessage => {
				const message = JSON.parse(String(rawMessage));
				if (message.type === 'input_audio.append' && !sentPreview && !emptyTranscription) {
					sentPreview = true;
					socket.send(JSON.stringify({ type: 'transcription.text.delta', text: 'Weather tomorrow' }));
				}
				if (message.type !== 'input_audio.end') return;
				if (transcriptionFails || emptyTranscription) {
					socket.send(JSON.stringify({ type: 'session.error', message: 'Transcription unavailable' }));
					return;
				}
				socket.send(JSON.stringify({ type: 'transcription.done', transcript: rawFinalTranscript, language: 'en', model: 'voxtral-mini-transcribe-realtime-2602' }));
				socket.send(JSON.stringify({ type: 'correction.skipped', transcript: rawFinalTranscript }));
			});
		});
		const log = (message: string, metadata: Record<string, unknown> = {}) => {
			console.log(`[WORKFLOWS_VOICE_E2E] ${message} ${JSON.stringify(metadata)}`);
		};
		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page, log, async () => {});
		const submittedTexts: string[] = [];
		const selectedWorkflowIds: Array<string | undefined> = [];
		await page.route('**/v1/workflows/input/stream', async (route: Route) => {
			if (route.request().method() !== 'POST') return route.continue();
			submittedTexts.push(route.request().postDataJSON().text);
			selectedWorkflowIds.push(route.request().postDataJSON().selected_workflow_id);
			await route.fulfill({ status: 200, contentType: 'text/event-stream', headers: { 'access-control-allow-origin': new URL(page.url()).origin, 'access-control-allow-credentials': 'true' }, body: sseSession(clarifyNextSession
				? { session_id: 'workflow-voice-spec', status: 'needs_clarification', message: 'Which event topics should I add?' }
				: { session_id: 'workflow-voice-spec', status: 'failed', error: 'Voice request was not saved.' }) });
		});
		await page.goto(getE2EDebugUrl('/workflows'), { waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('workflow-input-mic')).toBeVisible();
		await page.getByTestId('workflow-input-textarea').click();
		await page.getByTestId('workflow-input-textarea-expand').click();
		await expect(page.getByTestId('workflow-input-textarea-expand')).toHaveAttribute('aria-expanded', 'true');
		await page.getByTestId('workflow-input-mic').click();
		await expect(page.getByTestId('workflow-input-composer').getByTestId('record-overlay')).toBeVisible();
		await expect(page.getByTestId('workflow-input-textarea-expand')).toHaveCount(0);
		expect((await page.getByTestId('workflow-input-composer').boundingBox())!.height).toBeLessThanOrEqual(230);
		await expect.poll(() => socketConnections, { timeout: 15000 }).toBeGreaterThan(0);
		await expect(page.getByTestId('workflow-input-composer').getByTestId('recording-live-transcript')).toContainText('Weather tomorrow', { timeout: 15000 });
		await page.getByTestId('workflow-input-composer').getByTestId('record-finish-button').click();
		await expect.poll(() => submittedTexts.length).toBe(1);
		expect(submittedTexts[0]).toBe('Weather tomorrow at 08:00');
		await expect(page.getByTestId('workflow-input-composer').getByTestId('record-overlay')).toHaveCount(0);
		transcriptionFails = true;
		await page.getByTestId('workflow-input-textarea').fill('');
		const priorSocketConnections = socketConnections;
		await page.getByTestId('workflow-input-mic').click();
		await expect.poll(() => socketConnections, { timeout: 15000 }).toBeGreaterThan(priorSocketConnections);
		await page.getByTestId('workflow-input-composer').getByTestId('record-finish-button').click();
		await expect(page.getByTestId('workflow-input-composer').getByTestId('record-overlay')).toHaveCount(0);
		await expect(page.getByTestId('workflow-input-textarea')).toHaveValue('Weather tomorrow');
		expect(submittedTexts).toHaveLength(1);
		transcriptionFails = false;
		emptyTranscription = true;
		await page.getByTestId('workflow-input-textarea').fill('');
		await page.getByTestId('workflow-input-mic').click();
		await expect(page.getByTestId('workflow-input-composer').getByTestId('record-overlay')).toBeVisible();
		await expect(page.getByTestId('workflow-input-composer').getByTestId('timer-pill')).toContainText('00:01');
		await page.getByTestId('workflow-input-composer').getByTestId('record-finish-button').click();
		await expect(page.getByTestId('workflows-error')).toContainText('Could not transcribe this recording. Please record again or type your workflow request.');
		await expect(page.getByTestId('workflow-input-textarea')).toHaveValue('');
		expect(submittedTexts).toHaveLength(1);

		const apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
		const workflowTitle = `Voice edit spec ${Date.now()}`;
		const create = await page.request.post(`${apiUrl}/v1/workflows`, {
			data: { title: workflowTitle, graph: blankWorkflowGraph(7), enabled: false }
		});
		expect(create.ok(), await create.text()).toBe(true);
		const workflowId = (await create.json()).workflow.id as string;
		try {
			transcriptionFails = false;
			emptyTranscription = false;
			clarifyNextSession = true;
			rawFinalTranscript = 'Also search for AI meetups and queer meetups';
			await page.goto(getE2EDebugUrl(`/workflows#workflow-id=${encodeURIComponent(workflowId)}&tab=details`), { waitUntil: 'domcontentloaded' });
			await expect(page.getByTestId('workflow-ai-edit-mic')).toBeVisible();
			await page.getByTestId('workflow-ai-edit-mic').click();
			await expect(page.getByTestId('workflow-ai-edit-composer').getByTestId('record-overlay')).toBeVisible();
			await expect(page.getByTestId('workflow-ai-edit-composer').getByTestId('recording-live-transcript')).toContainText('Weather tomorrow');
			await page.getByTestId('workflow-ai-edit-composer').getByTestId('record-finish-button').click();
			await expect.poll(() => submittedTexts.length).toBe(2);
			expect(submittedTexts[1]).toBe(rawFinalTranscript);
			expect(selectedWorkflowIds[1]).toBe(workflowId);
			await expect.poll(() => page.evaluate(() => (window as Window & { workflowClarificationPrefills?: unknown[] }).workflowClarificationPrefills?.length ?? 0)).toBe(1);
			const [handoff] = await page.evaluate(() => (window as Window & { workflowClarificationPrefills?: Array<{ text: string; autoSend: boolean }> }).workflowClarificationPrefills ?? []);
			expect(handoff.autoSend).toBe(true);
			expect(handoff.text).toBe(`@focus:workflows:clarify_workflows ${rawFinalTranscript}\n\nWorkflow editor context: I was changing my existing workflow ${JSON.stringify(workflowTitle)} (ID ${workflowId}). Keep this workflow as the target. Clarify the change before carrying out any of the workflow's future search or delivery actions.`);
			expect(new URL(page.url()).pathname).toBe('/');
			expect(await page.evaluate(() => ({
				pending: sessionStorage.getItem('workflow_clarification_pending_message'),
				newChat: sessionStorage.getItem('workflow_clarification_new_chat'),
				autoSend: sessionStorage.getItem('docs_auto_send'),
				prefillCount: (window as Window & { workflowClarificationPrefills?: unknown[] }).workflowClarificationPrefills?.length ?? 0
			}))).toEqual({ pending: null, newChat: null, autoSend: null, prefillCount: 1 });
		} finally {
			await page.request.delete(`${apiUrl}/v1/workflows/${encodeURIComponent(workflowId)}`).catch(() => null);
		}
	});
});
