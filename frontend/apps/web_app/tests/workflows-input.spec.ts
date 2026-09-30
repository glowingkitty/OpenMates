/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
import type { Page, Route } from '@playwright/test';
/**
 * Workflows input home coverage.
 *
 * Purpose: verifies the deployed Workflows landing keeps Daily Inspiration,
 * renders one mixed recent/example row, and only marks an AI workflow New
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
	test('opens a committed AI workflow and marks it New on return', async ({ page }: { page: Page }) => {
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
			await expect.poll(async () => await mixedCards.count(), { timeout: 30000 }).toBeGreaterThan(6);
			await expect(mixedCards.first()).toHaveAttribute('data-card-source', 'recent');
			await expect(mixedCards.last()).toHaveAttribute('data-card-source', 'example');
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
				await route.fulfill({ status: 200, contentType: 'text/event-stream', headers: { 'access-control-allow-origin': new URL(page.url()).origin, 'access-control-allow-credentials': 'true' }, body: sseSession({
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
			await expect(page.getByTestId('workflow-ai-pending-preview')).toBeVisible();
			await expect(page.getByTestId('workflow-ai-preview-title')).toHaveText('Daily school weather preview');
			await expect(page.getByTestId('workflow-ai-preview-description')).toContainText('proposed weather briefing');
			await expect(page.getByTestId('workflow-ai-preview-steps').locator('li')).not.toHaveCount(0);
			await expect(page.getByTestId('workflow-ai-saving-pill')).toHaveText('Saving...');
			await expect(page.getByTestId('workflow-ai-pending-preview')).toHaveAttribute('data-disabled', 'true');
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
			const dockedBeforeScroll = await editorComposer.boundingBox();
			if (!dockedBeforeScroll) throw new Error('Workflow editor composer must be measurable.');
			expect(844 - dockedBeforeScroll.y - dockedBeforeScroll.height).toBeLessThan(32);
			await management.locator('.management-grid').evaluate((element: HTMLElement) => { element.scrollTop = element.scrollHeight; });
			const dockedAfterScroll = await editorComposer.boundingBox();
			expect(Math.abs((dockedAfterScroll?.y ?? 0) - dockedBeforeScroll.y)).toBeLessThan(2);
			await page.getByTestId('workflow-detail-back').click();
			await expect(page.getByTestId('workflows-start-screen')).toBeVisible();
			await expect(page.getByTestId('workflow-ai-created-undo')).toHaveCount(0);
			const newCard = page.getByTestId('workflow-mixed-row').getByTestId('workflow-landing-card').filter({ hasText: String(saved.title) });
			await expect(newCard).toBeVisible();
			await expect(newCard.locator('..').getByTestId('workflow-new-pill')).toHaveText('New');
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
			await page.route('**/v1/workflows/input/stream', async (route: Route) => {
				if (route.request().method() !== 'POST') return route.continue();
				const payload = route.request().postDataJSON();
				expect(payload.selected_workflow_id).toBe(draft.id);
				expect(payload.optimistic_save).toBe(true);
				await route.fulfill({ status: 200, contentType: 'text/event-stream', headers: { 'access-control-allow-origin': new URL(page.url()).origin, 'access-control-allow-credentials': 'true' }, body: sseSession({
					session_id: 'workflow-editor-success-spec', status: 'queued', message: 'Workflow prepared. Saving now.', preview_workflow: updatedWorkflow
				}) });
			});
			await page.getByTestId('workflow-ai-edit-textarea').fill('Update the steps');
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
	test('streams a workflow recording and submits only corrected text', async ({ page }: { page: Page }) => {
		test.setTimeout(120000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:workflows']);
		let correctionFails = false;
		let correctedTranscript = 'Weather tomorrow at 08:00';
		let socketConnections = 0;
		await page.routeWebSocket(/\/v1\/apps\/audio\/realtime-transcription(?:\?|$)/, socket => {
			socketConnections += 1;
			expect(new URL(socket.url()).searchParams.get('correction_context')).toBe('workflow');
			let sentPreview = false;
			socket.send(JSON.stringify({ type: 'session.ready', model: 'voxtral-mini-transcribe-realtime-2602', sample_rate: 16000 }));
			socket.onMessage(rawMessage => {
				const message = JSON.parse(String(rawMessage));
				if (message.type === 'input_audio.append' && !sentPreview) {
					sentPreview = true;
					socket.send(JSON.stringify({ type: 'transcription.text.delta', text: 'Weather tomorrow' }));
				}
				if (message.type !== 'input_audio.end') return;
				socket.send(JSON.stringify({ type: 'transcription.done', transcript: 'Weather tomorrow', language: 'en', model: 'voxtral-mini-transcribe-realtime-2602' }));
				socket.send(JSON.stringify({ type: 'correction.started', model: 'openai/gpt-oss-20b' }));
				socket.send(JSON.stringify(correctionFails
					? { type: 'correction.failed' }
					: { type: 'correction.done', transcript: correctedTranscript, correction_model: 'openai/gpt-oss-20b' }));
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
			await route.fulfill({ status: 200, contentType: 'text/event-stream', headers: { 'access-control-allow-origin': new URL(page.url()).origin, 'access-control-allow-credentials': 'true' }, body: sseSession({
				session_id: 'workflow-voice-spec', status: 'failed', error: 'Voice request was not saved.'
			}) });
		});
		await page.goto(getE2EDebugUrl('/workflows'), { waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('workflow-input-mic')).toBeVisible();
		await page.getByTestId('workflow-input-mic').click();
		await expect(page.getByTestId('workflow-input-composer').getByTestId('record-overlay')).toBeVisible();
		await expect.poll(() => socketConnections, { timeout: 15000 }).toBeGreaterThan(0);
		await expect(page.getByTestId('workflow-input-composer').getByTestId('recording-live-transcript')).toContainText('Weather tomorrow', { timeout: 15000 });
		await page.getByTestId('workflow-input-composer').getByTestId('record-finish-button').click();
		await expect.poll(() => submittedTexts.length).toBe(1);
		expect(submittedTexts[0]).toBe('Weather tomorrow at 08:00');
		await expect(page.getByTestId('workflow-input-composer').getByTestId('record-overlay')).toHaveCount(0);
		correctionFails = true;
		await page.getByTestId('workflow-input-textarea').fill('');
		const priorSocketConnections = socketConnections;
		await page.getByTestId('workflow-input-mic').click();
		await expect.poll(() => socketConnections, { timeout: 15000 }).toBeGreaterThan(priorSocketConnections);
		await page.getByTestId('workflow-input-composer').getByTestId('record-finish-button').click();
		await expect(page.getByTestId('workflow-input-composer').getByTestId('record-overlay')).toHaveCount(0);
		await expect(page.getByTestId('workflow-input-textarea')).toHaveValue('Weather tomorrow');
		expect(submittedTexts).toHaveLength(1);

		const apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
		const create = await page.request.post(`${apiUrl}/v1/workflows`, {
			data: { title: `Voice edit spec ${Date.now()}`, graph: blankWorkflowGraph(7), enabled: false }
		});
		expect(create.ok(), await create.text()).toBe(true);
		const workflowId = (await create.json()).workflow.id as string;
		try {
			correctionFails = false;
			correctedTranscript = 'Also search for AI meetups and queer meetups';
			await page.goto(getE2EDebugUrl(`/workflows#workflow-id=${encodeURIComponent(workflowId)}&tab=details`), { waitUntil: 'domcontentloaded' });
			await expect(page.getByTestId('workflow-ai-edit-mic')).toBeVisible();
			await page.getByTestId('workflow-ai-edit-mic').click();
			await expect(page.getByTestId('workflow-ai-edit-composer').getByTestId('record-overlay')).toBeVisible();
			await page.getByTestId('workflow-ai-edit-composer').getByTestId('record-finish-button').click();
			await expect.poll(() => submittedTexts.length).toBe(2);
			expect(submittedTexts[1]).toBe(correctedTranscript);
			expect(selectedWorkflowIds[1]).toBe(workflowId);
		} finally {
			await page.request.delete(`${apiUrl}/v1/workflows/${encodeURIComponent(workflowId)}`).catch(() => null);
		}
	});
});
