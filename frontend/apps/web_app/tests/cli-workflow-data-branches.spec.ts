/* eslint-disable @typescript-eslint/no-require-imports */
/** Deterministic REST and CLI coverage for saved V2 workflow data branches. */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { skipWithoutCredentials, skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getTestAccount } = require('./signup-flow-helpers');
const {
	createWorkflowCliHome,
	deleteWorkflowQuietly,
	loginWorkflowCliViaPair,
	removeWorkflowCliHome,
	runWorkflowCliJson,
	uniqueWorkflowName,
	workflowApiUrl
} = require('./helpers/workflow-cli-e2e-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

test.describe('Saved V2 workflow data branches', () => {
	test.setTimeout(180_000);

	// contract-test: direct surface=rest_api assertions=workflows.composition.earlier-action-reference,workflows.control.check,workflows.surface.semantic-parity,workflows.access.boundaries
	test('updates literal weather decisions and toggles a future schedule', async ({ page }: { page: any }) => {
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
		await skipIfFeaturesDisabled(test, page, ['platform:workflows']);
		const apiUrl = workflowApiUrl();
		const homeDir = createWorkflowCliHome('workflow-v2-branches');
		let workflowId: string | undefined;
		try {
			await loginWorkflowCliViaPair(page, apiUrl, homeDir, 'CLI_WORKFLOW_V2_BRANCHES');
			const graph: any = {
				version: 2, trigger_node_id: 'trigger',
				nodes: [
					{ id: 'trigger', type: 'schedule_trigger', config: { schedule: { type: 'once', at: '2036-01-01T00:00:00Z' } } },
					{ id: 'weather', type: 'app_skill_action', config: { app_id: 'weather', skill_id: 'forecast', input: { location: 'Berlin', start_date: { $date: 'today', format: 'date' }, end_date: { $date: 'today', format: 'date' } } } },
					{ id: 'check', type: 'check', config: { predicate: { left: '$nodes.weather.output.rain_expected', op: 'eq', right: true } } },
					{ id: 'umbrella', type: 'send_chat_message', config: { title: 'Rain', message: 'Bring an umbrella' } },
					{ id: 'dry', type: 'send_chat_message', config: { title: 'Dry', message: 'No umbrella needed' } }
				],
				edges: [
					{ from: 'trigger', to: 'weather' }, { from: 'weather', to: 'check' },
					{ from: 'check', to: 'umbrella', branch: 'yes' }, { from: 'check', to: 'dry', branch: 'no' }
				]
			};
			const created = await page.request.post(`${apiUrl}/v1/workflows`, {
				data: { title: uniqueWorkflowName('Weather decision save'), graph, enabled: false }
			});
			expect(created.ok(), await created.text()).toBeTruthy();
			workflowId = (await created.json()).workflow.id;
			graph.nodes[3].config.message = 'Take an umbrella today';
			graph.nodes[4].config.message = 'Enjoy the dry weather';
			const changed = await page.request.patch(`${apiUrl}/v1/workflows/${workflowId}`, { data: { graph } });
			expect(changed.ok(), await changed.text()).toBeTruthy();
			const saved = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'show', workflowId], 'inspect saved data branches');
			expect(saved.graph.nodes.find((node: any) => node.id === 'check')?.config.predicate.left).toBe('$nodes.weather.output.rain_expected');
			expect(saved.graph.nodes.find((node: any) => node.id === 'umbrella')?.config.message).toBe('Take an umbrella today');
			expect(saved.graph.nodes.find((node: any) => node.id === 'dry')?.config.message).toBe('Enjoy the dry weather');
			expect(saved.graph.edges.filter((edge: any) => edge.from === 'check').map((edge: any) => edge.branch).sort()).toEqual(['no', 'yes']);
			const selected = await runWorkflowCliJson(
				apiUrl, homeDir,
				['apps', 'workflows', 'search', '--input', JSON.stringify({ workflow_id: workflowId }), '--disable-prompt-injection-protection'],
				'inspect selected disabled workflow via app skill'
			);
			expect(selected.success).toBe(true);
			const selectedData = selected.data;
			expect(selectedData.success).toBe(true);
			expect(selectedData.total_count).toBe(1);
			expect(selectedData.workflows).toHaveLength(1);
			expect(selectedData.workflows[0].workflow_id).toBe(workflowId);
			expect(selectedData.workflows[0].enabled).toBe(false);
			expect(selectedData.workflows[0].graph.nodes.find((node: any) => node.id === 'trigger')?.config.schedule.at).toBe('2036-01-01T00:00:00Z');
			expect(selectedData.workflows[0].graph.nodes.find((node: any) => node.id === 'umbrella')?.config.message).toBe('Take an umbrella today');
			expect(selectedData.workflows[0].graph.edges.filter((edge: any) => edge.from === 'check').map((edge: any) => edge.branch).sort()).toEqual(['no', 'yes']);
			const enabled = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'enable', workflowId], 'enable future decision');
			expect(enabled.enabled).toBe(true);
			const disabled = await runWorkflowCliJson(apiUrl, homeDir, ['workflows', 'disable', workflowId], 'disable future decision');
			expect(disabled.enabled).toBe(false);
		} finally {
			await deleteWorkflowQuietly(apiUrl, homeDir, workflowId);
			removeWorkflowCliHome(homeDir);
		}
	});
});
