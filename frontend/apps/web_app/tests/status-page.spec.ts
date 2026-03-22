/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Public status page interaction coverage.
 * Verifies the minimal /status route with a mocked public API payload.
 * Covers Proton Mail omission, full timeline rendering, and tap/click details.
 * Architecture: docs/architecture/infrastructure/status-page.md
 * Test reference: python3 scripts/run_tests.py --spec status-page.spec.ts
 */
export {};

const { test, expect } = require('@playwright/test');
const { getE2EDebugUrl } = require('./signup-flow-helpers');

const STATUS_PAYLOAD = {
	overall_status: 'degraded',
	last_updated: '2026-03-22T19:56:34Z',
	is_admin: false,
	overall_timeline_30d: [
		{ date: '2026-03-21', status: 'operational' },
		{ date: '2026-03-22', status: 'degraded' }
	],
	health: {
		groups: [
			{
				group_name: 'ai_providers',
				display_name: 'AI Providers',
				status: 'operational',
				service_count: 1,
				timeline_30d: [
					{ date: '2026-03-21', status: 'operational' },
					{ date: '2026-03-22', status: 'operational' }
				],
				services: [
					{
						id: 'openai',
						name: 'OpenAI',
						status: 'operational',
						timeline_30d: [
							{ date: '2026-03-21', status: 'operational' },
							{ date: '2026-03-22', status: 'operational' }
						]
					}
				]
			}
		]
	},
	tests: {
		overall_status: 'failing',
		latest_run: {
			run_id: '2026-03-22T13:15:25Z',
			timestamp: '2026-03-22T13:15:25Z',
			summary: { total: 2, passed: 1, failed: 1 }
		},
		suites: [
			{
				name: 'playwright',
				status: 'failing',
				total: 2,
				passed: 1,
				failed: 1,
				skipped: 0,
				flaky: 0,
				categories: {
					'Auth & Signup': {
						total: 2,
						passed: 1,
						failed: 1,
						skipped: 0,
						pass_rate: 50,
						history: [
							{
								date: '2026-03-21',
								pass_rate: 0,
								total: 2,
								passed: 0,
								failed: 0,
								not_run: 2,
								has_run: false,
								run_at: null,
								tone: null
							},
							{
								date: '2026-03-22',
								pass_rate: 50,
								total: 2,
								passed: 1,
								failed: 0,
								not_run: 1,
								has_run: true,
								run_at: '2026-03-22T13:15:25Z',
								tone: 75
							}
						],
						tests: [
							{
								name: 'signup-flow.spec.ts',
								file: 'signup-flow.spec.ts',
								suite: 'playwright',
								status: 'passed',
								last_run: '2026-03-22T13:15:25Z',
								history_30d: [
									{ date: '2026-03-21', status: 'not_run', has_run: false, run_at: null },
									{
										date: '2026-03-22',
										status: 'passed',
										has_run: true,
										run_at: '2026-03-22T13:15:25Z'
									}
								]
							}
						]
					}
				},
				timeline_30d: [
					{
						date: '2026-03-21',
						pass_rate: 0,
						total: 0,
						passed: 0,
						failed: 0,
						has_run: false,
						run_at: null
					},
					{
						date: '2026-03-22',
						pass_rate: 50,
						total: 2,
						passed: 1,
						failed: 1,
						has_run: true,
						run_at: '2026-03-22T13:15:25Z'
					}
				]
			}
		],
		trend: [
			{
				date: '2026-03-21',
				total: 0,
				passed: 0,
				failed: 0,
				skipped: 0,
				has_run: false,
				run_at: null
			},
			{
				date: '2026-03-22',
				total: 2,
				passed: 1,
				failed: 1,
				skipped: 0,
				has_run: true,
				run_at: '2026-03-22T13:15:25Z'
			}
		],
		categories: {
			'Auth & Signup': {
				total: 2,
				passed: 1,
				failed: 1,
				skipped: 0,
				pass_rate: 50
			}
		}
	},
	incidents: { total_last_30d: 0 }
};

test.describe('Public status page', () => {
	test('shows tap details for no-run and exact run timestamps without Proton Mail', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(60000);

		await page.route('**/v1/status', async (route: any) => {
			await route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify(STATUS_PAYLOAD)
			});
		});

		await page.goto(getE2EDebugUrl('/status'), { waitUntil: 'domcontentloaded' });
		await expect(page.getByRole('heading', { name: 'OpenMates Status' })).toBeVisible();
		await expect(page.getByText('Protonmail')).toHaveCount(0);

		await page.getByTestId('status-suite-playwright').click();
		await page.getByTestId('status-category-auth-signup').click();

		const categoryTimeline = page.getByTestId('status-timeline-category-auth-signup');
		await categoryTimeline.locator('button').nth(0).click();
		await expect(page.getByTestId('status-timeline-detail')).toContainText('No run');

		await categoryTimeline.locator('button').nth(1).click();
		await expect(page.getByTestId('status-timeline-detail')).toContainText('Mar 22, 2026');
		await expect(page.getByTestId('status-timeline-detail')).toContainText('13:15');
		await expect(page.getByTestId('status-timeline-detail')).toContainText('1 not run');

		const testTimeline = page.getByTestId('status-timeline-test-signup-flow-spec-ts');
		await testTimeline.locator('button').nth(1).click();
		await expect(page.getByTestId('status-timeline-detail')).toContainText('passed');
		await expect(page.getByTestId('status-timeline-detail')).toContainText('13:15');
	});
});
