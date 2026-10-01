/* eslint-disable @typescript-eslint/no-require-imports */
/** Real credential-free domain searches through the CLI Workflow adapter. */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { runCli, deriveApiUrl } = require('./helpers/cli-test-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { openFullscreen, closeFullscreen } = require('./helpers/embed-test-helpers');
const {
	createWorkflowCliHome, removeWorkflowCliHome, writeWorkflowYaml
} = require('./helpers/workflow-cli-e2e-helpers');

const apiUrl = process.env.PLAYWRIGHT_TEST_API_URL || deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
const cliOptions = { useApiKey: false, record: false, env: { OPENMATES_API_KEY: undefined } };

async function cli(args: string[], label: string, timeoutMs = 90_000): Promise<any> {
	// The isolated CI coordinator supplies a fresh owner session. No shared dev login is used.
	const result = await runCli(apiUrl, [...args, '--json'], timeoutMs, cliOptions);
	const failureDetail = result.code === 0 ? '' : (result.stderr || result.stdout).slice(-2_000);
	expect(result.code, `${label} exited with ${result.code}: ${failureDetail}`).toBe(0);
	return JSON.parse(result.stdout);
}

function assertSelectedGroups(output: any): void {
	expect(output.app_id).toBe('hosting');
	expect(output.skill_id).toBe('search_domains');
	expect(output.result_count).toBe(2);
	expect(output.results.map((item: any) => item.domain_ascii)).toEqual(['example.com', 'example.net']);
	expect(output.raw.results.map((group: any) => group.id)).toEqual(['com', 'net']);
	expect(output.raw.success).toBe(true);
	for (const item of output.results) {
		expect(item.availability).toBe('unavailable');
		expect(item.provider).toBe('Gandi');
		expect(item.currency).toBe('EUR');
		expect(item.country).toBe('DE');
		expect(item.canonical_url).toMatch(/^https:\/\/shop\.gandi\.net\//);
		expect(item.source_id).toBe(item.canonical_url);
		expect(Array.isArray(item.registration_tiers)).toBe(true);
		expect(Array.isArray(item.renewal_tiers)).toBe(true);
	}
	for (const group of output.raw.results) {
		expect(group.checked_results).toHaveLength(1);
		expect(group.results).toHaveLength(1);
		expect(group.checked_at).toEqual(expect.any(String));
	}
}

test.describe('Hosting / Search domains in Workflows', () => {
	test.setTimeout(300_000);

	// contract-test: direct surface=cli assertions=hosting-domains.request.validated,hosting-domains.availability.selection,hosting-domains.quotes.truthful,hosting-domains.surface-parity
	test('step-tests and runs grouped searches with typed downstream output and checked evidence', async () => {
		const folder = createWorkflowCliHome('hosting-workflow');
		let workflowId: string | undefined;
		try {
			const capabilities = await cli(['workflows', 'capabilities'], 'Hosting capability discovery');
			const hosting = capabilities.find((capability: any) => capability.id === 'hosting.search_domains');
			expect(hosting?.enabled).toBe(true);
			expect(hosting.metadata.workflow.execution_mode).toBe('sync');
			expect(hosting.metadata.workflow.effect).toBe('read');
			expect(hosting.metadata.workflow.approval).toBe('never');
			expect(hosting.metadata.workflow.test_allowed).toBe(true);
			expect(hosting.metadata.output_schema.properties.results.type).toBe('array');

			const yaml = writeWorkflowYaml(folder, 'hosting.yml', `
title: Hosting domain fixture ${Date.now()}
start_when:
  manual: {}
steps:
  - id: domains
    use_app_skill: hosting.search_domains
    input:
      requests:
        - id: com
          query: example.com
          max_results: 1
        - id: net
          query: example.net
          max_results: 1
  - id: count
    check:
      left: $nodes.domains.output.result_count
      op: eq
      right: 2
  - id: only
    use_app_skill: hosting.search_domains
    input:
      requests:
        - query: example.com
          availability: available_only
          max_results: 1
  - id: empty
    check:
      left: $nodes.only.output.result_count
      op: eq
      right: 0
  - id: report
    send_chat_message:
      title: Hosting search fixture
      message: "Checked {{steps.domains.result_count}} selected domains."
`);
			const created = await cli(['workflows', 'create', '--file', yaml], 'Hosting Workflow creation');
			workflowId = created.workflow.id;
			expect(created.workflow.enabled).toBe(false);
			expect(created.validation.enable_ready).toBe(true);

			const stepTest = await cli(['workflows', 'step-test', workflowId!, 'domains', '--yes'], 'Hosting step test');
			expect(stepTest.status).toBe('completed');
			expect(stepTest.trigger_type).toBe('step_test');
			assertSelectedGroups(stepTest.node_runs.find((node: any) => node.node_id === 'domains').output_summary);

			const accepted = await cli(['workflows', 'run', workflowId!, '--idempotency-key', `${workflowId}-hosting`], 'Hosting Workflow run');
			const deadline = Date.now() + 120_000;
			let completed: any;
			while (Date.now() < deadline) {
				completed = await cli(['workflows', 'run-show', workflowId!, accepted.id], 'Hosting run status', 30_000);
				if (['completed', 'failed', 'cancelled'].includes(completed.status)) break;
				await new Promise((resolve) => setTimeout(resolve, 1_000));
			}
			expect(completed?.status).toBe('completed');
			assertSelectedGroups(completed.node_runs.find((node: any) => node.node_id === 'domains').output_summary);
			expect(completed.node_runs.find((node: any) => node.node_id === 'count').output_summary.matched).toBe(true);
			const only = completed.node_runs.find((node: any) => node.node_id === 'only').output_summary;
			expect(only.results).toEqual([]);
			expect(only.result_count).toBe(0);
			expect(only.raw.results[0].checked_results[0].domain_ascii).toBe('example.com');
			expect(only.raw.results[0].checked_results[0].availability).toBe('unavailable');
			expect(only.raw.results[0].warnings.length).toBeGreaterThan(0);
			expect(completed.node_runs.find((node: any) => node.node_id === 'empty').output_summary.matched).toBe(true);
			const report = completed.node_runs.find((node: any) => node.node_id === 'report');
			expect(report.status).toBe('completed');
			expect(report.output_summary.type).toBe('send_chat_message');
			expect(report.output_summary.delivery_id).toEqual(expect.any(String));
			expect(report.output_summary.chat_id).toEqual(expect.any(String));
		} finally {
			if (workflowId) await runCli(apiUrl, ['workflows', 'delete', workflowId, '--yes', '--json'], 30_000, cliOptions);
			removeWorkflowCliHome(folder);
		}
	});

	// contract-test: direct surface=gui.web assertions=hosting-domains.embeds.parent-child,hosting-domains.quotes.truthful,hosting-domains.surface-parity
	test('renders selected Workflow domains in an encrypted owner chat and reopens saved details on phone and laptop', async ({ page }, testInfo) => {
		const folder = createWorkflowCliHome('hosting-web-workflow');
		let workflowId: string | undefined;
		let chatId: string | undefined;
		const deliveryDiagnostics: string[] = [];
		const wireEvents: Record<string, number> = {};
		page.on('console', (entry: any) => {
			if (entry.type() === 'error' || /WorkflowDelivery/.test(entry.text())) {
				deliveryDiagnostics.push(entry.text().slice(0, 800).replace(/[a-f0-9]{8}-[a-f0-9-]{27,}/gi, '[id]').replace(/[A-Za-z0-9+/=_-]{80,}/g, '[redacted]'));
			}
		});
		page.on('pageerror', (error: Error) => deliveryDiagnostics.push(error.message.slice(0, 800)));
		page.on('websocket', (socket: any) => socket.on('framereceived', (frame: any) => {
			try {
				const event = JSON.parse(String(frame.payload));
				if (typeof event.type === 'string' && /workflow_chat_delivery/.test(event.type)) wireEvents[event.type] = (wireEvents[event.type] || 0) + 1;
			} catch { /* Binary and unrelated frames have no diagnostic value. */ }
		}));
		try {
			// An online owner client claims the encrypted pending delivery and persists its normal chat/embeds.
			await loginToTestAccount(page);
			const yaml = writeWorkflowYaml(folder, 'hosting-web.yml', `
title: Hosting saved embeds ${Date.now()}
start_when:
  manual: {}
steps:
  - id: domains
    use_app_skill: hosting.search_domains
    input:
      requests:
        - id: com
          query: example.com
          max_results: 1
        - id: net
          query: example.net
          max_results: 1
  - id: report
    send_chat_message:
      title: Hosting selected domains
      message: "Checked domains: {{steps.domains.results}}"
`);
			const created = await cli(['workflows', 'create', '--file', yaml], 'Hosting web Workflow creation');
			workflowId = created.workflow.id;
			const accepted = await cli(['workflows', 'run', workflowId!, '--idempotency-key', `${workflowId}-web`], 'Hosting web Workflow run');
			let completed: any;
			await expect(async () => {
				completed = await cli(['workflows', 'run-show', workflowId!, accepted.id], 'Hosting web run status', 30_000);
				expect(completed.status).toBe('completed');
			}).toPass({ timeout: 120_000, intervals: [1_000, 2_000, 5_000] });
			assertSelectedGroups(completed.node_runs.find((node: any) => node.node_id === 'domains').output_summary);
			const report = completed.node_runs.find((node: any) => node.node_id === 'report').output_summary;
			expect(report.selected_count).toBe(2);
			expect(report.embed_ids).toHaveLength(2);
			chatId = report.chat_id;
			expect(chatId).toEqual(expect.any(String));
			const sidebar = page.getByTestId('activity-history-wrapper');
			if (!await sidebar.isVisible()) await page.getByTestId('sidebar-toggle').click();
			await expect(sidebar).toBeVisible();
			const deliveredChat = page.locator(`[data-testid="chat-item-wrapper"][data-chat-id="${chatId}"]`);
			await expect(deliveredChat).toBeVisible({ timeout: 60_000 });
			await deliveredChat.click({ timeout: 15_000 });
			await expect(page).toHaveURL(new RegExp(`#chat-id=${chatId}$`), { timeout: 15_000 });
			// Desktop chat selection retains the sidebar; its launcher is hidden while open.
			if (await sidebar.isVisible()) {
				const closeSidebar = sidebar.getByRole('button', { name: 'Close', exact: true });
				await expect(closeSidebar).toBeVisible();
				await closeSidebar.click({ timeout: 15_000 });
			}
			await expect(sidebar).not.toBeVisible();
			const cards = page.getByTestId('embed-preview').filter({ has: page.getByTestId('hosting-domain-preview') });
			// Chat metadata reaches the sidebar before incoming delivery finishes encryption and storage.
			// Prove initial delivery before checking persistence across a full page reload.
			await expect(cards).toHaveCount(2, { timeout: 60_000 });
			for (const domain of ['example.com', 'example.net']) {
				await expect(cards.filter({ hasText: domain })).toHaveCount(1);
			}

			for (const [viewport, size] of [
				['phone', { width: 390, height: 844 }],
				['laptop', { width: 1440, height: 1000 }]
			] as const) {
				await page.setViewportSize(size);
				// Reload exercises encrypted IndexedDB/server hydration, rather than the delivery's in-memory payload.
				await page.reload({ waitUntil: 'domcontentloaded' });
				await expect(cards).toHaveCount(2, { timeout: 60_000 });
				for (const domain of ['example.com', 'example.net']) {
					const card = cards.filter({ hasText: domain });
					await expect(card).toHaveCount(1);
					await card.scrollIntoViewIfNeeded();
					await expect(card.locator('[data-app-icon="hosting"]').first()).toBeVisible();
					await expect(card.locator('.icon_rounded.hosting').first()).toBeVisible();
					await expect(card.getByTestId('hosting-domain-preview').locator('.topline > span').first()).toHaveText('In use');
					await expect(card.getByTestId('hosting-domain-registration')).toHaveText('Price unavailable');
					await expect(card).toContainText('Gandi');
					await testInfo.attach(`hosting-saved-${domain}-${viewport}-preview`, { body: await card.screenshot(), contentType: 'image/png' });
					const overlay = await openFullscreen(page, card);
					await expect(overlay.getByTestId('hosting-domain-ascii')).toHaveText(domain);
					await expect(overlay.getByTestId('embed-header-subtitle')).toContainText('In use');
					await expect(overlay.getByRole('link', { name: /Gandi/ })).toHaveAttribute('href', /^https:\/\/shop\.gandi\.net\//);
					await expect(overlay.getByTestId('hosting-domain-registration')).toContainText('Price unavailable');
					await expect(overlay.getByTestId('hosting-domain-renewal')).toContainText('Price unavailable');
					const bounds = await overlay.getByTestId('hosting-domain-details').boundingBox();
					expect(bounds).toBeTruthy();
					expect(bounds.x).toBeGreaterThanOrEqual(-1);
					expect(bounds.x + bounds.width).toBeLessThanOrEqual(size.width + 1);
					await testInfo.attach(`hosting-saved-${domain}-${viewport}-detail`, { body: await page.screenshot(), contentType: 'image/png' });
					await closeFullscreen(page, overlay);
				}
			}
		} finally {
			const state = await page.evaluate(async (targetId: string | undefined) => {
				const active = document.querySelector('[data-testid="active-chat-container"]');
				const result: Record<string, unknown> = {
					selectedUrl: Boolean(targetId && location.hash === `#chat-id=${targetId}`),
					activeMatches: Boolean(targetId && active?.getAttribute('data-current-chat-id') === targetId),
					messageCount: active?.getAttribute('data-current-message-count'),
					loadState: active?.getAttribute('data-chat-load-state')
				};
				await new Promise<void>((resolve) => {
					const request = indexedDB.open('chats_db');
					request.onerror = () => resolve();
					request.onsuccess = () => {
						const db = request.result;
						const stores = ['chats', 'messages', 'embeds'].filter((name) => db.objectStoreNames.contains(name));
						if (!stores.length) { db.close(); resolve(); return; }
						const transaction = db.transaction(stores, 'readonly');
						for (const name of stores) {
							const rows = transaction.objectStore(name).getAll();
							rows.onsuccess = () => {
								result[`${name}Count`] = rows.result.length;
								if (name === 'messages') result.targetMessages = rows.result.filter((row: any) => row.chat_id === targetId).length;
								if (name === 'chats') result.targetMessagesVersion = rows.result.find((row: any) => row.chat_id === targetId)?.messages_v;
							};
						}
						transaction.oncomplete = transaction.onabort = () => { db.close(); resolve(); };
					};
				});
				return result;
			}, chatId).catch(() => ({ unavailable: true }));
			await testInfo.attach('hosting-delivery-diagnostics', { body: JSON.stringify({ state, wireEvents, errors: deliveryDiagnostics.slice(-40) }, null, 2), contentType: 'application/json' });
			if (chatId) await runCli(apiUrl, ['chats', 'delete', chatId, '--yes', '--json'], 30_000, cliOptions);
			if (workflowId) await runCli(apiUrl, ['workflows', 'delete', workflowId, '--yes', '--json'], 30_000, cliOptions);
			removeWorkflowCliHome(folder);
		}
	});
});
