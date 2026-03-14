/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
/* eslint-disable no-console */
/**
 * Custom Playwright reporter that sends test lifecycle events to OpenObserve
 * via the OpenMates internal API.
 *
 * Pushes three event types to /internal/openobserve/push-test-event:
 *   - suite_start: fired once when the test suite begins (total test count)
 *   - test_end:    fired per-spec with status/duration/error
 *   - suite_end:   fired once when the suite finishes (summary counts)
 *
 * Also sends failure notifications to /internal/e2e-tests/notify-failure
 * (existing behaviour, unchanged).
 *
 * CONFIGURATION:
 * Set these environment variables to enable reporting:
 *   E2E_REPORT_API_URL:   Base URL of the API (e.g., "http://api:8000")
 *   E2E_REPORT_API_TOKEN: Internal service token for authentication
 *   E2E_REPORT_ENVIRONMENT: Environment name ("development" or "production")
 *   E2E_REPORT_ENABLED:   "false" to disable (default: enabled)
 *
 * Reporter is wired in via docker-compose.playwright.yml command:
 *   npx playwright test --reporter=list,./tests/api-reporter.ts
 *
 * Architecture context: docs/architecture/admin-console-log-forwarding.md
 * Tests: None (non-critical observability infrastructure)
 */
export {};

const https = require('https');
const http = require('http');
const { URL } = require('url');

// Configuration from environment variables
const API_URL = process.env.E2E_REPORT_API_URL || '';
const API_TOKEN = process.env.E2E_REPORT_API_TOKEN || '';
const ENVIRONMENT = process.env.E2E_REPORT_ENVIRONMENT || 'development';
const ENABLED = process.env.E2E_REPORT_ENABLED !== 'false'; // Default enabled
const WORKER_SLOT = process.env.PLAYWRIGHT_WORKER_SLOT || '0';

// Git metadata (injected by run-tests-worker.sh or read from env)
const GIT_BRANCH = process.env.GIT_BRANCH || '';
const RUN_ID = process.env.RUN_ID || '';

// Store for collecting test results
interface TestResult {
	testFile: string;
	testName: string;
	status: string;
	duration: number;
	errorMessage?: string;
	consoleLogs?: string;
	networkActivities?: string;
}

const testResults: TestResult[] = [];
const failedTests: TestResult[] = [];

/**
 * Generic HTTP POST helper for internal API calls.
 * Non-blocking: errors are logged but never reject the promise with a throw.
 */
function postToAPI(path: string, body: Record<string, any>): Promise<boolean> {
	if (!API_URL || !API_TOKEN) {
		return Promise.resolve(false);
	}
	if (!ENABLED) {
		return Promise.resolve(false);
	}

	const url = new URL(path, API_URL);
	const payload = JSON.stringify(body);

	return new Promise((resolve) => {
		const protocol = url.protocol === 'https:' ? https : http;
		const options = {
			hostname: url.hostname,
			port: url.port || (url.protocol === 'https:' ? 443 : 80),
			path: url.pathname,
			method: 'POST',
			headers: {
				'Content-Type': 'application/json',
				'Content-Length': Buffer.byteLength(payload),
				'X-Internal-Service-Token': API_TOKEN
			}
		};

		const req = protocol.request(options, (res: any) => {
			let data = '';
			res.on('data', (chunk: any) => (data += chunk));
			res.on('end', () => {
				if (res.statusCode >= 200 && res.statusCode < 300) {
					resolve(true);
				} else {
					console.error(
						`[API-REPORTER] POST ${path} failed: ${res.statusCode} - ${data.slice(0, 200)}`
					);
					resolve(false);
				}
			});
		});

		req.on('error', (error: any) => {
			console.error(`[API-REPORTER] Network error for ${path}: ${error.message}`);
			resolve(false);
		});

		req.setTimeout(10000, () => {
			req.destroy();
			console.error(`[API-REPORTER] Request timeout for ${path}`);
			resolve(false);
		});

		req.write(payload);
		req.end();
	});
}

/**
 * Push a test lifecycle event to OpenObserve via the internal API.
 */
function pushTestEvent(event: Record<string, any>): Promise<boolean> {
	return postToAPI('/internal/openobserve/push-test-event', {
		...event,
		environment: ENVIRONMENT,
		worker_slot: WORKER_SLOT,
		git_branch: GIT_BRANCH,
		run_id: RUN_ID
	});
}

/**
 * Send test failure notification to the existing e2e-tests endpoint.
 */
function sendFailureNotification(result: TestResult): Promise<boolean> {
	return postToAPI('/internal/e2e-tests/notify-failure', {
		environment: ENVIRONMENT,
		test_file: result.testFile,
		test_name: result.testName,
		status: result.status,
		timestamp: new Date().toISOString(),
		duration_seconds: result.duration / 1000,
		error_message: result.errorMessage || null,
		console_logs: result.consoleLogs || null,
		network_activities: result.networkActivities || null
	});
}

/**
 * Playwright Reporter class implementation.
 * See: https://playwright.dev/docs/test-reporters#custom-reporters
 */
class APIReporter {
	private startTime: number = 0;

	onBegin(_config: any, suite: any): void {
		this.startTime = Date.now();
		const testCount = suite.allTests().length;
		console.log(`\n[API-REPORTER] Starting ${testCount} test(s) for ${ENVIRONMENT} environment`);

		if (!API_URL || !API_TOKEN) {
			console.log('[API-REPORTER] Warning: API reporting not configured');
			console.log('  Set E2E_REPORT_API_URL and E2E_REPORT_API_TOKEN to enable notifications');
		}

		// Push suite_start event to OpenObserve
		pushTestEvent({
			event_type: 'suite_start',
			status: 'running',
			test_name: `${testCount} test(s)`,
			test_file: '',
			duration_ms: 0
		}).catch(() => {});
	}

	onTestEnd(test: any, result: any): void {
		const testFile = test.location?.file?.split('/').pop() || 'unknown';
		const testName = test.title;
		const status = result.status; // 'passed', 'failed', 'timedOut', 'skipped'
		const duration = result.duration;

		// Extract error message if available
		let errorMessage: string | undefined;
		if (result.error) {
			errorMessage = result.error.message || '';
			if (result.error.stack) {
				errorMessage += '\n' + result.error.stack;
			}
		}

		const testResult: TestResult = {
			testFile,
			testName,
			status,
			duration,
			errorMessage
		};

		testResults.push(testResult);

		// Push test_end event to OpenObserve
		pushTestEvent({
			event_type: 'test_end',
			status,
			test_file: testFile,
			test_name: testName,
			duration_ms: duration,
			error_message: errorMessage ? errorMessage.slice(0, 800) : ''
		}).catch(() => {});

		// Track failed tests for summary
		if (status === 'failed' || status === 'timedOut') {
			failedTests.push(testResult);

			// Send notification immediately for failures
			console.log(`[API-REPORTER] Test ${status}: ${testName} (${testFile})`);
			sendFailureNotification(testResult).catch((err) => {
				console.error('[API-REPORTER] Error sending notification:', err);
			});
		} else if (status === 'passed') {
			console.log(`[API-REPORTER] Test passed: ${testName} (${testFile})`);
		} else if (status === 'skipped') {
			console.log(`[API-REPORTER] Test skipped: ${testName} (${testFile})`);
		}
	}

	async onEnd(result: any): Promise<void> {
		const totalDuration = Date.now() - this.startTime;
		const passed = testResults.filter((r) => r.status === 'passed').length;
		const failed = testResults.filter(
			(r) => r.status === 'failed' || r.status === 'timedOut'
		).length;
		const skipped = testResults.filter((r) => r.status === 'skipped').length;

		console.log('\n[API-REPORTER] ========== Test Run Summary ==========');
		console.log(`  Environment: ${ENVIRONMENT}`);
		console.log(`  Total Duration: ${(totalDuration / 1000).toFixed(2)}s`);
		console.log(
			`  Tests: ${testResults.length} total, ${passed} passed, ${failed} failed, ${skipped} skipped`
		);
		console.log(`  Overall Status: ${result.status}`);

		if (failed > 0) {
			console.log('\n[API-REPORTER] Failed Tests:');
			for (const test of failedTests) {
				console.log(`  - ${test.testName} (${test.testFile})`);
				if (test.errorMessage) {
					// Show first 200 chars of error
					const shortError = test.errorMessage.slice(0, 200);
					console.log(`    Error: ${shortError}${test.errorMessage.length > 200 ? '...' : ''}`);
				}
			}
		}

		console.log('[API-REPORTER] =====================================\n');

		// Push suite_end summary event to OpenObserve
		await pushTestEvent({
			event_type: 'suite_end',
			status: result.status,
			test_name: '',
			test_file: '',
			duration_ms: totalDuration,
			total: testResults.length,
			passed,
			failed,
			skipped
		}).catch(() => {});
	}
}

module.exports = APIReporter;
