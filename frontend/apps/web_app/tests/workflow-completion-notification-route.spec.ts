/* eslint-disable @typescript-eslint/no-require-imports -- Shared Playwright helpers expose CommonJS exports. */
import type { Browser, Page } from '@playwright/test';
export {};

const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

function apiUrl(): string {
	const host = new URL(process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org');
	return host.hostname === 'localhost' ? 'http://localhost:8000' : `${host.protocol}//api.${host.hostname.replace(/^app\./, '')}`;
}

function completionUrl(workflowId: string, runId: string, delivery?: { chat_id: string; message_id: string; delivery_id: string }): string {
	const run = `/#workflow-id=${encodeURIComponent(workflowId)}&workflow-tab=runs&run-id=${encodeURIComponent(runId)}&workflow-completion=1`;
	return delivery
		? `${run}&chat-id=${encodeURIComponent(delivery.chat_id)}&message-id=${encodeURIComponent(delivery.message_id)}&delivery-id=${encodeURIComponent(delivery.delivery_id)}`
		: run;
}

async function createAndRun(page: Page, graph: Record<string, unknown>, title: string) {
	const created = await page.request.post(`${apiUrl()}/v1/workflows`, { data: { title, enabled: false, graph } });
	expect(created.ok(), await created.text()).toBe(true);
	const workflowId = (await created.json()).workflow.id as string;
	const accepted = await page.request.post(`${apiUrl()}/v1/workflows/${workflowId}/run`, {
		data: { mode: 'manual', input: {} },
		headers: { 'Idempotency-Key': `completion-route-${workflowId}` }
	});
	expect(accepted.ok(), await accepted.text()).toBe(true);
	const runId = (await accepted.json()).run.id as string;
	return { workflowId, runId };
}

async function getRun(page: Page, workflowId: string, runId: string) {
	const response = await page.request.get(`${apiUrl()}/v1/workflows/${workflowId}/runs/${runId}`);
	expect(response.ok(), await response.text()).toBe(true);
	return (await response.json()).run;
}

async function createAndSelectTeam(page: Page, name: string): Promise<string> {
	await page.getByTestId('profile-container').click();
	await page.getByTestId('settings-teams-item').click();
	await expect(page.getByTestId('teams-settings-page')).toBeVisible({ timeout: 30_000 });
	await page.getByTestId('team-create-open').click();
	await page.getByTestId('team-name-input').fill(name);
	await page.getByTestId('team-create-continue').click();
	await expect(page.getByTestId('team-avatar-preview')).toBeVisible({ timeout: 30_000 });
	const created = page.waitForResponse((response) => response.request().method() === 'POST' &&
		new URL(response.url()).pathname === '/v1/teams');
	await page.getByTestId('team-create-submit').click();
	const response = await created;
	expect(response.ok(), await response.text()).toBe(true);
	const teamId = String((await response.json()).team?.team_id ?? '');
	expect(teamId).toBeTruthy();
	await expect(page.getByTestId('teams-settings-detail')).toBeVisible({ timeout: 30_000 });
	await page.getByTestId('banner-back-button').click();
	await expect(page.getByTestId('teams-settings-page')).toBeVisible({ timeout: 30_000 });
	await page.getByTestId('banner-back-button').click();
	await expect(page.getByTestId('team-context-dropdown')).toBeVisible({ timeout: 30_000 });
	await page.getByTestId('team-context-dropdown').click();
	const option = page.getByTestId(`team-context-option-${teamId}`);
	if (!(await option.isVisible().catch(() => false))) await page.getByTestId('team-context-show-more').click();
	await option.click();
	await expect(page.getByTestId('team-context-dropdown')).toContainText(name);
	await page.getByTestId('icon-button-close').click();
	return teamId;
}

test.describe('Workflow completion notification links', () => {
	// contract-test: direct surface=gui.web assertions=notifications.workflow-run.chat-target,notifications.workflow-run.run-target,notifications.workflow-run.completed-delivery
	test('cold open switches from Team to Personal, waits for the exact pending message, and rejects stale targets', async ({ page }: { page: Page }) => {
		test.setTimeout(180_000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:workflows', 'platform:teams']);
		const associationResponse = await page.request.get(new URL('/.well-known/apple-app-site-association',
			process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org').toString());
		expect(associationResponse.ok(), await associationResponse.text()).toBe(true);
		const association = await associationResponse.json() as {
			applinks?: { details?: Array<{ appIDs?: string[]; components?: Array<Record<string, string>> }> }
		};
		const app = association.applinks?.details?.find((detail) => detail.appIDs?.includes('Z9B2YFKN2X.org.openmates.app'));
		const rootRules = app?.components?.filter((component) => component['/'] === '/') ?? [];
		expect(rootRules).toHaveLength(2);
		const matchesFragment = (pattern: string, fragment: string) => {
			const parts = pattern.split('?*').map((part) => part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
			return new RegExp(`^${parts.join('.+')}$`).test(fragment);
		};
		const advertised = (fragment: string) => rootRules.some((rule) =>
			typeof rule['#'] === 'string' && matchesFragment(rule['#'], fragment));
		const testWorkflow = '11111111-1111-4111-8111-111111111111';
		const testRun = '22222222-2222-4222-8222-222222222222';
		const noChatFragment = completionUrl(testWorkflow, testRun).split('#')[1];
		const chatFragment = completionUrl(testWorkflow, testRun, {
			chat_id: '33333333-3333-4333-8333-333333333333',
			message_id: '44444444-4444-4444-8444-444444444444',
			delivery_id: '55555555-5555-4555-8555-555555555555'
		}).split('#')[1];
		expect(advertised(noChatFragment)).toBe(true);
		expect(advertised(chatFragment)).toBe(true);
		expect(advertised(`chat-id=${testWorkflow}`)).toBe(false);
		expect(advertised(`workflow-id=${testWorkflow}&workflow-tab=runs&run-id=${testRun}`)).toBe(false);
		// Keep the first device from claiming the delivery. A fresh page must
		// complete owner-device encryption after the notification link opens.
		await page.addInitScript(() => {
			const nativeSend = WebSocket.prototype.send;
			WebSocket.prototype.send = function (data) {
				if (typeof data === 'string') {
					try { if (JSON.parse(data).type === 'workflow_chat_delivery_claim') return; }
					catch { /* Other frames use the normal transport. */ }
				}
				nativeSend.call(this, data);
			};
		});
		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page);
		const title = `Completion route ${Date.now()}`;
		const chatTitle = `Completion chat ${Date.now()}`;
		const graph = { version: 2, trigger_node_id: 'trigger', nodes: [
			{ id: 'trigger', type: 'manual_trigger', title: 'Start', config: {} },
			{ id: 'send', type: 'send_chat_message', title: 'Send message', config: { title: chatTitle, message: 'The scheduled result is ready' } }
		], edges: [{ from: 'trigger', to: 'send' }] };
		const { workflowId, runId } = await createAndRun(page, graph, title);
		let reopened: Page | null = null;
		let teamId: string | null = null;
		try {
			let delivery: { chat_id: string; message_id: string; delivery_id: string } | null = null;
			await expect.poll(async () => {
				const run = await getRun(page, workflowId, runId);
				const node = run.node_runs?.find((item: { node_type: string }) => item.node_type === 'send_chat_message');
				if (run.status !== 'completed' || node?.output_summary?.status !== 'delivery_pending') return false;
				delivery = node.output_summary;
				return !!(delivery?.chat_id && delivery?.message_id && delivery?.delivery_id);
			}, { timeout: 45_000 }).toBe(true);
			expect(delivery).toBeTruthy();
			teamId = await createAndSelectTeam(page, `Completion route Team ${Date.now()}`);
			const context = page.context();
			await page.close();
			reopened = await context.newPage();
			const runDetailScopes: Array<string | null> = [];
			reopened.on('request', (request) => {
				const url = new URL(request.url());
				if (request.method() === 'GET' && url.pathname === `/v1/workflows/${workflowId}/runs/${runId}`) {
					runDetailScopes.push(url.searchParams.get('team_id'));
				}
			});
			await reopened.goto(getE2EDebugUrl(completionUrl(workflowId, runId, delivery!)), { waitUntil: 'domcontentloaded' });
			await expect(reopened).toHaveURL(new RegExp(`#chat-id=${delivery!.chat_id}&message-id=${delivery!.message_id}`), { timeout: 45_000 });
			expect(runDetailScopes).toContain(null);
			await expect(reopened.getByText('The scheduled result is ready', { exact: false }).first()).toBeVisible();

			await reopened.goto(getE2EDebugUrl(completionUrl(workflowId, runId, { ...delivery!, message_id: 'other-message' })), { waitUntil: 'domcontentloaded' });
			await expect(reopened.getByTestId('workflow-completion-chat-unavailable')).toBeVisible({ timeout: 30_000 });
			await expect(reopened).toHaveURL(new RegExp(`workflow-id=${workflowId}.*run-id=${runId}`));
			await reopened.getByTestId('workflow-runs-back-to-editor').click();
			await expect(reopened).not.toHaveURL(/delivery-id=|message-id=|workflow-completion=/);
			await expect(reopened.getByTestId('workflow-completion-chat-unavailable')).toHaveCount(0);

			const deleted = await reopened.request.delete(`${apiUrl()}/v1/workflows/${workflowId}`);
			expect(deleted.ok(), await deleted.text()).toBe(true);
			await reopened.goto(getE2EDebugUrl(completionUrl(workflowId, runId, delivery!)), { waitUntil: 'domcontentloaded' });
			await expect(reopened.getByTestId('workflow-completion-chat-unavailable')).toBeVisible({ timeout: 30_000 });
			await expect(reopened).toHaveURL(new RegExp(`workflow-id=${workflowId}.*run-id=${runId}`));
		} finally {
			await (reopened ?? page).request.delete(`${apiUrl()}/v1/workflows/${workflowId}`).catch(() => null);
			if (teamId) {
				const removed = await (reopened ?? page).request.delete(`${apiUrl()}/v1/teams/${teamId}`);
				expect(removed.ok(), await removed.text()).toBe(true);
			}
		}
	});

	// contract-test: direct surface=gui.web assertions=notifications.workflow-run.chat-target,notifications.workflow-run.completed-delivery
	test('signed-out completion link survives login and opens the exact pending chat message', async ({ page, browser }: { page: Page; browser: Browser }) => {
		test.setTimeout(210_000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:workflows']);
		const creatorContext = await browser.newContext({ baseURL: process.env.PLAYWRIGHT_TEST_BASE_URL });
		const creatorPage = await creatorContext.newPage();
		let workflowId: string | null = null;
		try {
			await creatorPage.addInitScript(() => {
				const nativeSend = WebSocket.prototype.send;
				WebSocket.prototype.send = function (data) {
					if (typeof data === 'string') {
						try { if (JSON.parse(data).type === 'workflow_chat_delivery_claim') return; }
						catch { /* Other frames use the normal transport. */ }
					}
					nativeSend.call(this, data);
				};
			});
			await creatorPage.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
			await loginToTestAccount(creatorPage);
			const message = `Signed-out completion ${Date.now()}`;
			const graph = { version: 2, trigger_node_id: 'trigger', nodes: [
				{ id: 'trigger', type: 'manual_trigger', config: {} },
				{ id: 'send', type: 'send_chat_message', config: { title: `Signed-out route ${Date.now()}`, message } }
			], edges: [{ from: 'trigger', to: 'send' }] };
			const created = await createAndRun(creatorPage, graph, `Signed-out completion ${Date.now()}`);
			workflowId = created.workflowId;
			const runId = created.runId;
			let delivery: { chat_id: string; message_id: string; delivery_id: string } | null = null;
			await expect.poll(async () => {
				const run = await getRun(creatorPage, workflowId!, runId);
				const node = run.node_runs?.find((item: { node_type: string }) => item.node_type === 'send_chat_message');
				if (run.status !== 'completed' || node?.output_summary?.status !== 'delivery_pending') return false;
				delivery = node.output_summary;
				return !!(delivery?.chat_id && delivery?.message_id && delivery?.delivery_id);
			}, { timeout: 45_000 }).toBe(true);
			expect(delivery).toBeTruthy();
			await creatorPage.close();
			const link = completionUrl(workflowId, runId, delivery!);
			await page.goto(getE2EDebugUrl(link), { waitUntil: 'domcontentloaded' });
			await expect(page.getByTestId('workflows-auth-required')).toBeVisible({ timeout: 30_000 });
			await expect(page).toHaveURL(new RegExp(`workflow-id=${workflowId}.*run-id=${runId}.*chat-id=${delivery!.chat_id}.*message-id=${delivery!.message_id}.*delivery-id=${delivery!.delivery_id}`));
			await loginToTestAccount(page, undefined, undefined, { preserveCurrentUrl: true, waitForEditor: false });
			await expect(page).toHaveURL(new RegExp(`#chat-id=${delivery!.chat_id}&message-id=${delivery!.message_id}`), { timeout: 45_000 });
			await expect(page.getByText(message, { exact: false }).first()).toBeVisible();
		} finally {
			if (workflowId) await creatorContext.request.delete(`${apiUrl()}/v1/workflows/${workflowId}`).catch(() => null);
			await creatorContext.close();
		}
	});

	// contract-test: direct surface=gui.web assertions=notifications.workflow-run.chat-target,notifications.workflow-run.completed-delivery
	test('cold open targets a new message in the existing chat, not its seed message', async ({ page }: { page: Page }) => {
		test.setTimeout(210_000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:workflows']);
		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page);
		const context = page.context();
		const seedText = `Seed completion ${Date.now()}`;
		const responseText = `Existing chat completion ${Date.now()}`;
		const seedGraph = { version: 2, trigger_node_id: 'trigger', nodes: [
			{ id: 'trigger', type: 'manual_trigger', config: {} },
			{ id: 'send', type: 'send_chat_message', config: { title: `Existing chat route ${Date.now()}`, message: seedText } }
		], edges: [{ from: 'trigger', to: 'send' }] };
		let seedWorkflowId: string | null = null;
		let responseWorkflowId: string | null = null;
		let reopened: Page | null = null;
		try {
			const seed = await createAndRun(page, seedGraph, `Seed chat ${Date.now()}`);
			seedWorkflowId = seed.workflowId;
			let seedDelivery: { chat_id: string; message_id: string; delivery_id: string } | null = null;
			await expect.poll(async () => {
				const run = await getRun(page, seed.workflowId, seed.runId);
				const node = run.node_runs?.find((item: { node_type: string }) => item.node_type === 'send_chat_message');
				if (run.status !== 'completed' || !['delivery_pending', 'claimed', 'acknowledged'].includes(node?.output_summary?.status)) return false;
				seedDelivery = node.output_summary;
				return !!(seedDelivery?.chat_id && seedDelivery?.message_id && seedDelivery?.delivery_id);
			}, { timeout: 45_000 }).toBe(true);
			expect(seedDelivery).toBeTruthy();
			await page.goto(getE2EDebugUrl(completionUrl(seed.workflowId, seed.runId, seedDelivery!)), { waitUntil: 'domcontentloaded' });
			await expect(page).toHaveURL(new RegExp(`#chat-id=${seedDelivery!.chat_id}&message-id=${seedDelivery!.message_id}`), { timeout: 45_000 });
			await expect(page.getByText(seedText, { exact: false }).first()).toBeVisible();
			await expect.poll(async () => {
				const run = await getRun(page, seed.workflowId, seed.runId);
				return run.output_summary?.deliveries?.send?.status;
			}, { timeout: 45_000 }).toBe('acknowledged');

			// Preserve the second delivery for a fresh owner page to encrypt and persist.
			await page.addInitScript(() => {
				const nativeSend = WebSocket.prototype.send;
				WebSocket.prototype.send = function (data) {
					if (typeof data === 'string') {
						try { if (JSON.parse(data).type === 'workflow_chat_delivery_claim') return; }
						catch { /* Other frames use the normal transport. */ }
					}
					nativeSend.call(this, data);
				};
			});
			await page.reload({ waitUntil: 'domcontentloaded' });
			const responseGraph = { version: 2, trigger_node_id: 'trigger', nodes: [
				{ id: 'trigger', type: 'manual_trigger', config: {} },
				{ id: 'send', type: 'send_chat_message', config: { chat_id: seedDelivery!.chat_id, message: responseText } }
			], edges: [{ from: 'trigger', to: 'send' }] };
			const response = await createAndRun(page, responseGraph, `Existing chat response ${Date.now()}`);
			responseWorkflowId = response.workflowId;
			let responseDelivery: { chat_id: string; message_id: string; delivery_id: string } | null = null;
			await expect.poll(async () => {
				const run = await getRun(page, response.workflowId, response.runId);
				const node = run.node_runs?.find((item: { node_type: string }) => item.node_type === 'send_chat_message');
				if (run.status !== 'completed' || node?.output_summary?.status !== 'delivery_pending') return false;
				responseDelivery = node.output_summary;
				return !!(responseDelivery?.chat_id && responseDelivery?.message_id && responseDelivery?.delivery_id);
			}, { timeout: 45_000 }).toBe(true);
			expect(responseDelivery).toBeTruthy();
			expect(responseDelivery!.chat_id).toBe(seedDelivery!.chat_id);
			expect(responseDelivery!.message_id).not.toBe(seedDelivery!.message_id);
			await page.close();
			reopened = await context.newPage();
			await reopened.goto(getE2EDebugUrl(completionUrl(response.workflowId, response.runId, responseDelivery!)), { waitUntil: 'domcontentloaded' });
			await expect(reopened).toHaveURL(new RegExp(`#chat-id=${seedDelivery!.chat_id}&message-id=${responseDelivery!.message_id}`), { timeout: 45_000 });
			await expect(reopened.getByText(responseText, { exact: false }).first()).toBeVisible();
		} finally {
			for (const workflowId of [responseWorkflowId, seedWorkflowId]) {
				if (workflowId) await context.request.delete(`${apiUrl()}/v1/workflows/${workflowId}`).catch(() => null);
			}
		}
	});

	// contract-test: direct surface=gui.web assertions=notifications.workflow-run.run-target
	test('a completed Check-false run opens the exact run and never a chat', async ({ page }: { page: Page }) => {
		test.setTimeout(120_000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:workflows']);
		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page);
		const graph = { version: 2, trigger_node_id: 'trigger', nodes: [
			{ id: 'trigger', type: 'manual_trigger', config: {} },
			{ id: 'check', type: 'check', config: { mode: 'exact', predicate: { left: 1, op: 'eq', right: 2 } } },
			{ id: 'send', type: 'send_chat_message', config: { title: 'Skipped message', message: 'Do not send' } },
			{ id: 'end', type: 'end', config: {} }
		], edges: [
			{ from: 'trigger', to: 'check' },
			{ from: 'check', to: 'send', branch: 'yes' },
			{ from: 'check', to: 'end', branch: 'no' }
		] };
		const { workflowId, runId } = await createAndRun(page, graph, `Skipped completion ${Date.now()}`);
		try {
			await expect.poll(async () => (await getRun(page, workflowId, runId)).status, { timeout: 45_000 }).toBe('completed');
			const run = await getRun(page, workflowId, runId);
			expect(run.node_runs?.some((node: { node_type: string; status: string }) => node.node_type === 'send_chat_message' && node.status === 'completed')).toBe(false);
			await page.goto(getE2EDebugUrl(completionUrl(workflowId, runId)), { waitUntil: 'domcontentloaded' });
			await expect(page.locator(`[data-testid="workflow-run-marker"][data-run-id="${runId}"]`)).toBeVisible({ timeout: 30_000 });
			await expect(page.locator(`[data-testid="workflow-run-marker"][data-run-id="${runId}"]`)).toHaveAttribute('aria-pressed', 'true');
			await expect(page.getByTestId('workflow-completion-chat-loading')).toHaveCount(0);
			await expect(page).toHaveURL(new RegExp(`workflow-id=${workflowId}.*run-id=${runId}`));
			const missingRunId = `${runId}-missing`;
			await page.goto(getE2EDebugUrl(completionUrl(workflowId, missingRunId)), { waitUntil: 'domcontentloaded' });
			await expect(page.getByTestId('workflow-run-unavailable')).toBeVisible({ timeout: 30_000 });
			await expect(page.locator('[data-testid="workflow-run-marker"][aria-pressed="true"]')).toHaveCount(0);
			await expect(page).toHaveURL(new RegExp(`run-id=${missingRunId}`));
		} finally {
			await page.request.delete(`${apiUrl()}/v1/workflows/${workflowId}`).catch(() => null);
		}
	});
});
