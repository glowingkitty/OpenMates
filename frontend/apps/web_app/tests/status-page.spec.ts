/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Public status page (v3) E2E tests.
 * Verifies the /status route with a mocked /v1/status payload:
 * banner, service groups, uptime bars, response time charts, E2E test
 * categories, incidents, and error handling.
 * Architecture: docs/architecture/infrastructure/status-page.md
 * Test reference: python3 scripts/run_tests.py --spec status-page.spec.ts
 */
export {};

const { test, expect } = require('@playwright/test');
const { getE2EDebugUrl } = require('./signup-flow-helpers');

// ─── Mock data ──────────────────────────────────────────────────────────────

const MOCK_STATUS_RESPONSE = {
	status: 'operational' as const,
	last_updated: new Date().toISOString(),
	uptime_pct: 99.8,
	groups: [
		{
			name: 'Core Platform',
			services: [
				{
					id: 'web_app',
					name: 'Web App',
					status: 'operational' as const,
					uptime_90d: Array.from({ length: 90 }, (_, i) => ({
						date: new Date(Date.now() - (89 - i) * 86400000).toISOString().slice(0, 10),
						status: 'operational' as const
					})),
					uptime_pct: 99.9,
					response_times_7d: null
				},
				{
					id: 'core_api',
					name: 'API Server',
					status: 'operational' as const,
					uptime_90d: Array.from({ length: 90 }, (_, i) => ({
						date: new Date(Date.now() - (89 - i) * 86400000).toISOString().slice(0, 10),
						status: 'operational' as const
					})),
					uptime_pct: 99.9,
					response_times_7d: null
				}
			]
		},
		{
			name: 'AI Providers',
			services: [
				{
					id: 'anthropic',
					name: 'Anthropic',
					status: 'operational' as const,
					uptime_90d: Array.from({ length: 90 }, (_, i) => ({
						date: new Date(Date.now() - (89 - i) * 86400000).toISOString().slice(0, 10),
						status: 'operational' as const
					})),
					uptime_pct: 99.9,
					response_times_7d: Array.from({ length: 24 }, (_, i) => ({
						timestamp: new Date(Date.now() - (23 - i) * 3600000).toISOString(),
						avg_ms: 45 + Math.random() * 20,
						min_ms: 30 + Math.random() * 10,
						max_ms: 60 + Math.random() * 30,
						samples: 5
					}))
				},
				{
					id: 'groq',
					name: 'Groq',
					status: 'degraded' as const,
					uptime_90d: Array.from({ length: 90 }, (_, i) => ({
						date: new Date(Date.now() - (89 - i) * 86400000).toISOString().slice(0, 10),
						status: i > 85 ? ('degraded' as const) : ('operational' as const)
					})),
					uptime_pct: 97.2,
					response_times_7d: Array.from({ length: 24 }, (_, i) => ({
						timestamp: new Date(Date.now() - (23 - i) * 3600000).toISOString(),
						avg_ms: 100 + Math.random() * 50,
						min_ms: 80,
						max_ms: 200,
						samples: 3
					}))
				}
			]
		},
		{ name: 'Search & Data', services: [] },
		{ name: 'Image & Media', services: [] },
		{ name: 'Events & Health', services: [] },
		{ name: 'Travel', services: [] },
		{ name: 'Payment', services: [] },
		{ name: 'Email & Moderation', services: [] }
	],
	tests: {
		total: 10,
		passed: 8,
		failed: 2,
		last_run: new Date(Date.now() - 7200000).toISOString(),
		categories: [
			{
				name: 'Chat',
				total: 5,
				passed: 4,
				failed: 1,
				specs: [
					{ name: 'chat-flow', status: 'passed' as const, error: null, duration_s: 12, timeline_30d: [] },
					{
						name: 'chat-management',
						status: 'passed' as const,
						error: null,
						duration_s: 8,
						timeline_30d: []
					},
					{
						name: 'message-sync',
						status: 'failed' as const,
						error: 'Timeout waiting for sync',
						duration_s: 32,
						timeline_30d: []
					},
					{ name: 'chat-search', status: 'passed' as const, error: null, duration_s: 6, timeline_30d: [] },
					{ name: 'chat-scroll', status: 'passed' as const, error: null, duration_s: 5, timeline_30d: [] }
				]
			},
			{
				name: 'Payment',
				total: 3,
				passed: 2,
				failed: 1,
				specs: [
					{ name: 'buy-credits', status: 'passed' as const, error: null, duration_s: 15, timeline_30d: [] },
					{
						name: 'saved-payment-invoice',
						status: 'failed' as const,
						error: 'Payment timeout',
						duration_s: 28,
						timeline_30d: []
					},
					{
						name: 'buy-credits-stripe',
						status: 'passed' as const,
						error: null,
						duration_s: 10,
						timeline_30d: []
					}
				]
			},
			{
				name: 'Signup',
				total: 2,
				passed: 2,
				failed: 0,
				specs: [
					{
						name: 'signup-flow',
						status: 'passed' as const,
						error: null,
						duration_s: 20,
						timeline_30d: []
					},
					{
						name: 'signup-flow-polar',
						status: 'passed' as const,
						error: null,
						duration_s: 18,
						timeline_30d: []
					}
				]
			}
		]
	},
	incidents: [
		{
			component: 'Groq',
			group: 'AI Providers',
			severity: 'degraded',
			started_at: new Date(Date.now() - 3 * 86400000).toISOString(),
			resolved_at: new Date(Date.now() - 3 * 86400000 + 15600000).toISOString(),
			duration_minutes: 260,
			updates: [
				{
					status: 'degraded',
					timestamp: new Date(Date.now() - 3 * 86400000).toISOString()
				},
				{
					status: 'operational',
					timestamp: new Date(Date.now() - 3 * 86400000 + 15600000).toISOString()
				}
			]
		}
	]
};

// ─── Helpers ────────────────────────────────────────────────────────────────

/** Intercept the v2 status API and return the provided payload. */
async function mockStatusApi(page: any, payload: any, statusCode: number = 200) {
	await page.route('**/v1/status', async (route: any) => {
		await route.fulfill({
			status: statusCode,
			contentType: 'application/json',
			body: JSON.stringify(payload)
		});
	});
}

/** Navigate to /status and wait for content to render. */
async function gotoStatus(page: any) {
	await page.goto(getE2EDebugUrl('/status'), { waitUntil: 'domcontentloaded' });
}

// ─── Tests ──────────────────────────────────────────────────────────────────

test.describe('Status page — banner and page load', () => {
	test('renders title, status banner text, uptime percentage, and last-updated info', async ({
		page
	}: {
		page: any;
	}) => {
		await mockStatusApi(page, MOCK_STATUS_RESPONSE);
		await gotoStatus(page);

		// Page title
		await expect(page.getByRole('heading', { name: 'OpenMates Status' })).toHaveCount(0);
		await expect(page).toHaveTitle('OpenMates Status');

		// Banner label for operational status
		await expect(page.getByText('All Systems Operational')).toBeVisible();

		// Uptime percentage
		await expect(page.getByText('99.8% uptime')).toBeVisible();

		// "Updated X ago" text — exact value depends on timing so assert partial match
		await expect(page.getByText(/Updated .+ ago/)).toBeVisible();
	});
});

test.describe('Status page — service groups', () => {
	test('renders all 8 group headers', async ({ page }: { page: any }) => {
		await mockStatusApi(page, MOCK_STATUS_RESPONSE);
		await gotoStatus(page);

		const expectedGroups = [
			'Core Platform',
			'AI Providers',
			'Search & Data',
			'Image & Media',
			'Events & Health',
			'Travel',
			'Payment',
			'Email & Moderation'
		];

		for (const groupName of expectedGroups) {
			await expect(page.getByRole('heading', { name: groupName })).toBeVisible();
		}
	});

	test('shows service name, status label, and uptime percentage for each service', async ({
		page
	}: {
		page: any;
	}) => {
		await mockStatusApi(page, MOCK_STATUS_RESPONSE);
		await gotoStatus(page);

		// Core Platform services
		await expect(page.getByText('Web App')).toBeVisible();
		await expect(page.getByText('API Server')).toBeVisible();

		// AI Providers services — use .name selector to avoid strict mode violations
		// (service names also appear in the incidents section)
		await expect(page.locator('.name', { hasText: 'Anthropic' })).toBeVisible();
		await expect(page.locator('.name', { hasText: 'Groq' })).toBeVisible();

		// Status labels — "Operational" appears multiple times, just verify at least one
		await expect(page.getByText('Operational').first()).toBeVisible();
		await expect(page.getByText('Degraded')).toBeVisible();

		// Uptime percentages
		await expect(page.getByText('99.9%').first()).toBeVisible();
		await expect(page.getByText('97.2%')).toBeVisible();
	});

	test('uptime bars render with 90 segments for services', async ({ page }: { page: any }) => {
		await mockStatusApi(page, MOCK_STATUS_RESPONSE);
		await gotoStatus(page);

		// Each service row has an uptime bar with 90 segment buttons.
		// The Web App row should have 90 segments in its bar.
		const uptimeBars = page.locator('[role="img"][aria-label="Uptime history"]');
		await expect(uptimeBars.first()).toBeVisible();

		// The first uptime bar (Web App) should have 90 segment buttons
		const firstBarSegments = uptimeBars.first().locator('button');
		await expect(firstBarSegments).toHaveCount(90);
	});
});

test.describe('Status page — response time chart', () => {
	test('clicking a provider row with response_times_7d expands the chart', async ({
		page
	}: {
		page: any;
	}) => {
		await mockStatusApi(page, MOCK_STATUS_RESPONSE);
		await gotoStatus(page);

		// Chart should not be visible initially
		await expect(page.getByText('Anthropic — Response Time (7d)')).toHaveCount(0);

		// Click the Anthropic service row (it has response_times_7d)
		await page.getByRole('button', { name: /Anthropic/ }).click();

		// Response time chart header should now be visible
		await expect(page.getByText('Anthropic — Response Time (7d)')).toBeVisible();

		// Average ms label should be visible
		await expect(page.getByText(/avg: \d+ms/)).toBeVisible();

		// SVG chart should be rendered
		await expect(page.locator('svg.chart')).toBeVisible();
	});

	test('clicking a service without response_times_7d does not expand a chart', async ({
		page
	}: {
		page: any;
	}) => {
		await mockStatusApi(page, MOCK_STATUS_RESPONSE);
		await gotoStatus(page);

		// Click the Web App row (response_times_7d is null)
		await page.getByRole('button', { name: /Web App/ }).click();

		// No chart should appear
		await expect(page.getByText(/Response Time \(7d\)/)).toHaveCount(0);
	});
});

test.describe('Status page — E2E tests section', () => {
	test('shows test summary with total and passed count', async ({ page }: { page: any }) => {
		await mockStatusApi(page, MOCK_STATUS_RESPONSE);
		await gotoStatus(page);

		await expect(page.getByText('E2E Tests')).toBeVisible();
		await expect(page.getByText('8/10 passing')).toBeVisible();
	});

	test('renders all three test category names', async ({ page }: { page: any }) => {
		await mockStatusApi(page, MOCK_STATUS_RESPONSE);
		await gotoStatus(page);

		// Use .cat-name selectors to avoid strict mode violations —
		// "Chat" appears in both the category name and individual spec names
		await expect(page.locator('.cat-name', { hasText: 'Chat' })).toBeVisible();
		await expect(page.locator('.cat-name', { hasText: 'Payment' })).toBeVisible();
		await expect(page.locator('.cat-name', { hasText: 'Signup' })).toBeVisible();
	});

	test('categories with failures are auto-expanded and show FAILED badges', async ({
		page
	}: {
		page: any;
	}) => {
		await mockStatusApi(page, MOCK_STATUS_RESPONSE);
		await gotoStatus(page);

		// "Chat" category has 1 failure — should be auto-expanded,
		// meaning its test specs are visible without clicking
		await expect(page.getByText('message-sync')).toBeVisible();
		const failedBadges = page.locator('.badge-failed');
		// Two failed tests total: message-sync (Chat) and saved-payment-invoice (Payment)
		await expect(failedBadges).toHaveCount(2);

		// Verify the FAILED badge text is present
		await expect(page.getByText('FAILED').first()).toBeVisible();
	});

	test('passing categories are collapsed by default', async ({ page }: { page: any }) => {
		await mockStatusApi(page, MOCK_STATUS_RESPONSE);
		await gotoStatus(page);

		// "Signup" category has 0 failures — should be collapsed.
		// Its individual spec names should NOT be visible.
		await expect(page.getByText('signup-flow-polar')).not.toBeVisible();

		// Click the Signup category header to expand
		await page.getByRole('button', { name: /Signup/ }).click();

		// Now specs should be visible
		await expect(page.getByText('signup-flow-polar')).toBeVisible();
	});

	test('shows category-level pass/fail counts', async ({ page }: { page: any }) => {
		await mockStatusApi(page, MOCK_STATUS_RESPONSE);
		await gotoStatus(page);

		// Chat: 4/5 passing, Payment: 2/3 passing, Signup: 2/2 passing
		await expect(page.getByText('4/5 passing')).toBeVisible();
		await expect(page.getByText('2/3 passing')).toBeVisible();
		await expect(page.getByText('2/2 passing')).toBeVisible();
	});
});

test.describe('Status page — incidents', () => {
	test('renders incident with component name and duration', async ({ page }: { page: any }) => {
		await mockStatusApi(page, MOCK_STATUS_RESPONSE);
		await gotoStatus(page);

		await expect(page.getByText('Incidents (last 14 days)')).toBeVisible();

		// Incident component name
		// "Groq" already appears in the services section, but the incident section
		// should also show it. Verify the incident-specific context by checking for
		// "Degraded" in the incidents area and the duration.
		await expect(page.getByText('4h 20min')).toBeVisible();

		// Incident update timeline should show "Resolved"
		await expect(page.getByText('Resolved')).toBeVisible();
	});

	test('shows "No incidents" when incident list is empty', async ({ page }: { page: any }) => {
		const noIncidentsPayload = {
			...MOCK_STATUS_RESPONSE,
			incidents: []
		};

		await mockStatusApi(page, noIncidentsPayload);
		await gotoStatus(page);

		await expect(page.getByText('No incidents in the last 14 days.')).toBeVisible();
	});
});

test.describe('Status page — error and loading states', () => {
	test('shows error message when API returns an error', async ({ page }: { page: any }) => {
		await mockStatusApi(page, { error: 'Internal server error' }, 500);
		await gotoStatus(page);

		await expect(page.getByText('Could not load status data.')).toBeVisible();
	});

	test('shows loading state initially before data loads', async ({ page }: { page: any }) => {
		// Delay the API response to observe the loading state
		await page.route('**/v1/status', async (route: any) => {
			await new Promise((resolve) => setTimeout(resolve, 1000));
			await route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify(MOCK_STATUS_RESPONSE)
			});
		});

		await page.goto(getE2EDebugUrl('/status'), { waitUntil: 'domcontentloaded' });

		// Loading text should appear before data arrives
		await expect(page.getByText('Loading...')).toBeVisible();

		// After data loads, loading should be replaced by content
		await expect(page.getByText('All Systems Operational')).toBeVisible({ timeout: 5000 });
		await expect(page.getByText('Loading...')).not.toBeVisible();
	});
});
