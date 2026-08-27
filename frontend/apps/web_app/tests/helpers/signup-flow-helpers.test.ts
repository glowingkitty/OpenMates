/**
 * Source-level tests for shared signup/chat Playwright helpers.
 *
 * signup-flow-helpers.ts is compiled by Playwright and intentionally uses its
 * legacy CommonJS export shape, so these tests guard critical helper wiring
 * without importing the mixed module directly in Node.
 */

// contract-test-file: tooling

/* eslint-disable @typescript-eslint/no-require-imports */

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const helperSource = () => fs.readFileSync(
	path.resolve(__dirname, '../signup-flow-helpers.ts'),
	'utf8'
);

test('exports the E2E server-content override gate helper', () => {
	const source = helperSource();

	assert.match(source, /const E2E_LOG_FORWARDING_SESSION_KEY = 'openmates_e2e_log_forwarding';/);
	assert.match(source, /async function installE2EServerContentOverrideGate\(page: any, scope: string = 'local-e2e'\)/);
	assert.match(source, /sessionStorage\.setItem\(key, JSON\.stringify\(\{ runId, token: 'local-e2e' \}\)\)/);
	assert.match(source, /const gateArgs = \{ key: E2E_LOG_FORWARDING_SESSION_KEY, runId: scope \};/);
	assert.match(source, /page\.addInitScript\(installGate, gateArgs\)/);
	assert.match(source, /page\.evaluate\(installGate, gateArgs\)/);
	assert.match(source, /String\(error\)\.includes\('SecurityError'\)/);
	assert.match(source, /installE2EServerContentOverrideGate,/);
});

test('preserves real E2E debug sessions when installing the local gate', () => {
	const source = helperSource();

	const guardIndex = source.indexOf('if (sessionStorage.getItem(key)) return;');
	const writeIndex = source.indexOf("sessionStorage.setItem(key, JSON.stringify({ runId, token: 'local-e2e' }))");
	assert.notEqual(guardIndex, -1);
	assert.notEqual(writeIndex, -1);
	assert.ok(guardIndex < writeIndex);
});
