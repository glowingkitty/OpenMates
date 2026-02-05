/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Custom Playwright reporter that sends test failure notifications to the OpenMates API.
 *
 * This reporter:
 * 1. Collects test results as tests complete
 * 2. Sends failure notifications to the internal API endpoint
 * 3. Logs results for visibility in test output
 *
 * CONFIGURATION:
 * Set these environment variables to enable API reporting:
 * - E2E_REPORT_API_URL: Base URL of the API (e.g., "https://api.dev.openmates.org")
 * - E2E_REPORT_API_TOKEN: Internal service token for authentication
 * - E2E_REPORT_ENVIRONMENT: Environment name ("development" or "production")
 *
 * USAGE:
 * Add to playwright.config.ts:
 *   reporter: [['list'], ['./tests/api-reporter.ts']]
 *
 * Or run with:
 *   npx playwright test --reporter=list,./tests/api-reporter.ts
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
 * Send test failure notification to the API.
 */
async function sendFailureNotification(result: TestResult): Promise<boolean> {
	if (!API_URL || !API_TOKEN) {
		console.log('[API-REPORTER] Skipping notification - API_URL or API_TOKEN not configured');
		return false;
	}

	if (!ENABLED) {
		console.log('[API-REPORTER] Skipping notification - reporting disabled');
		return false;
	}

	const url = new URL('/internal/e2e-tests/notify-failure', API_URL);
	const payload = JSON.stringify({
		environment: ENVIRONMENT,
		test_file: result.testFile,
		test_name: result.testName,
		status: result.status,
		timestamp: new Date().toISOString(),
		duration_seconds: result.duration / 1000, // Convert ms to seconds
		error_message: result.errorMessage || null,
		console_logs: result.consoleLogs || null,
		network_activities: result.networkActivities || null
	});

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
					console.log(`[API-REPORTER] Notification sent for: ${result.testName}`);
					resolve(true);
				} else {
					console.error(`[API-REPORTER] Failed to send notification: ${res.statusCode} - ${data}`);
					resolve(false);
				}
			});
		});

		req.on('error', (error: any) => {
			console.error(`[API-REPORTER] Network error: ${error.message}`);
			resolve(false);
		});

		req.setTimeout(10000, () => {
			req.destroy();
			console.error('[API-REPORTER] Request timeout');
			resolve(false);
		});

		req.write(payload);
		req.end();
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
	}
}

module.exports = APIReporter;
