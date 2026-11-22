/**
 * Where a real-inference spec may run (TASK-5616).
 *
 * Real-inference specs (`real-inference-*.spec.ts`, manifest group `real_inference`)
 * run in two places only:
 *   - the isolated per-run CI stack of the protected `real-inference` environment,
 *     which sets OPENMATES_CI_REAL_INFERENCE=1, sends no replay fixtures and serves
 *     the app on localhost;
 *   - a manual check against the dev stack (no CI flag, or the dev proof harness,
 *     which sets OPENMATES_PROOF_REAL_DEV=1), on a `.dev.` host.
 * Any other CI job, a fixture-replay run or any other host is refused.
 *
 * Tests: frontend/apps/web_app/tests/real-inference-*.spec.ts
 */

export {};

/** True when the spec runs in the keyed isolated CI stack. */
function inRealInferenceCi(): boolean {
	return process.env.OPENMATES_CI_REAL_INFERENCE === '1';
}

/**
 * Throw unless this run may send real provider requests for `label`.
 * `baseUrl` is the web app the spec drives.
 */
function requireRealInference(label: string, baseUrl: string): void {
	if (process.env.E2E_USE_MOCKS || process.env.E2E_USE_LIVE_MOCKS) {
		throw new Error(`${label} needs real inference; fixture replay must be off.`);
	}
	const host = new URL(baseUrl).hostname;
	if (inRealInferenceCi()) {
		if (host !== 'localhost' && host !== '127.0.0.1') {
			throw new Error(`${label} in real-inference CI drives only the job's own stack, not ${host}.`);
		}
		return;
	}
	const devHarness = process.env.OPENMATES_PROOF_REAL_DEV === '1';
	if (process.env.GITHUB_ACTIONS || process.env.OPENMATES_CI_ISOLATED === '1' || (process.env.CI && !devHarness)) {
		throw new Error(`${label} runs in CI only in the real-inference group (real-inference-*.spec.ts).`);
	}
	if (!host.includes('.dev.')) {
		throw new Error(`${label} may target only the dev web host for manual checks, not ${host}.`);
	}
}

module.exports = { inRealInferenceCi, requireRealInference };
