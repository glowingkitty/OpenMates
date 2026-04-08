/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * frontend/apps/web_app/tests/helpers/cookie-audit.ts
 *
 * Drop-in replacement for `@playwright/test` that auto-captures storage
 * (cookies, localStorage, sessionStorage, IndexedDB DB names) at the end of
 * every E2E test — pass or fail.
 *
 * Why this exists:
 *   The legal/compliance cronjob (scripts/legal-compliance-scan.sh) needs
 *   runtime evidence — not just static acknowledgments — that the app does
 *   not set non-essential cookies. Per-test snapshots are merged by
 *   scripts/merge_storage_audits.py into
 *   docs/architecture/compliance/cookies.yml, which the auditor agent
 *   reviews against ePrivacy Art. 5(3) / TTDSG §25 strict-necessity rules.
 *
 * Specs use this exactly like @playwright/test:
 *   import { test, expect } from './helpers/cookie-audit';
 *   const { test, expect } = require('./helpers/cookie-audit');
 *
 * The auto-fixture runs without any spec-side opt-in. Failures inside the
 * teardown are swallowed so audit instrumentation can never break a test.
 *
 * Anonymization is mandatory: this is an open-source repo, so values are
 * truncated and high-entropy / sensitive keys are redacted entirely. Real
 * tokens must never be committed.
 */
export {};

import { test as baseTest, expect } from '@playwright/test';

const fs = require('fs');
const path = require('path');

// Keys whose values are sensitive — store length only, never the value.
const SENSITIVE_KEY_RE =
	/(token|refresh|secret|key|auth|session|csrf|jwt|otp|password|stripe|code$|^code|bearer)/i;

// Output dir relative to the Playwright cwd (frontend/apps/web_app).
// run_tests.py copies this back to repo-root test-results/ after the run.
const AUDIT_DIR = path.resolve(process.cwd(), 'test-results', 'storage-audits');

interface CookieRecord {
	name: string;
	domain: string;
	path: string;
	expires: number;
	http_only: boolean;
	secure: boolean;
	same_site: string;
	example_value: string;
	value_length: number;
}

interface StorageEntry {
	key: string;
	example_value: string;
	value_length: number;
}

interface StorageSnapshot {
	spec: string;
	test: string;
	status: string;
	captured_at: string;
	url: string | null;
	cookies: CookieRecord[];
	local_storage: StorageEntry[];
	session_storage: StorageEntry[];
	indexed_db: string[];
}

function anonymizeValue(key: string, value: unknown): { example_value: string; value_length: number } {
	const str = typeof value === 'string' ? value : JSON.stringify(value ?? '');
	const len = str.length;
	if (SENSITIVE_KEY_RE.test(key)) {
		return { example_value: '<redacted>', value_length: len };
	}
	if (len <= 8) {
		return { example_value: str, value_length: len };
	}
	return { example_value: `${str.slice(0, 4)}…<${len}>`, value_length: len };
}

function sanitizeFilename(s: string): string {
	return s.replace(/[^a-zA-Z0-9._-]+/g, '_').slice(0, 120);
}

async function captureStorage(
	page: any,
	context: any,
	testInfo: any
): Promise<void> {
	const snapshot: StorageSnapshot = {
		spec: path.basename(testInfo.file || 'unknown.spec.ts'),
		test: testInfo.title,
		status: testInfo.status || 'unknown',
		captured_at: new Date().toISOString(),
		url: null,
		cookies: [],
		local_storage: [],
		session_storage: [],
		indexed_db: []
	};

	// Cookies live on the BrowserContext and survive page closure.
	try {
		const cookies = await context.cookies();
		snapshot.cookies = cookies.map((c: any) => {
			const anon = anonymizeValue(c.name, c.value);
			return {
				name: c.name,
				domain: c.domain || '',
				path: c.path || '/',
				expires: typeof c.expires === 'number' ? c.expires : -1,
				http_only: !!c.httpOnly,
				secure: !!c.secure,
				same_site: c.sameSite || 'Lax',
				example_value: anon.example_value,
				value_length: anon.value_length
			};
		});
	} catch {
		// context already disposed — leave cookies empty
	}

	// Page-bound storage requires a live page that's still on a same-origin URL.
	try {
		if (page && !page.isClosed()) {
			snapshot.url = page.url();
			const webStorage = await page.evaluate(async () => {
				const entries = (s: Storage): Array<[string, string]> => {
					const out: Array<[string, string]> = [];
					for (let i = 0; i < s.length; i++) {
						const k = s.key(i);
						if (k !== null) out.push([k, s.getItem(k) ?? '']);
					}
					return out;
				};
				let idb: string[] = [];
				try {
					if ((indexedDB as any).databases) {
						const dbs = await (indexedDB as any).databases();
						idb = dbs.map((d: any) => d?.name).filter(Boolean);
					}
				} catch {
					// older browsers — ignore
				}
				return {
					local: entries(localStorage),
					session: entries(sessionStorage),
					idb
				};
			});

			snapshot.local_storage = webStorage.local.map(([k, v]: [string, string]) => ({
				key: k,
				...anonymizeValue(k, v)
			}));
			snapshot.session_storage = webStorage.session.map(([k, v]: [string, string]) => ({
				key: k,
				...anonymizeValue(k, v)
			}));
			snapshot.indexed_db = webStorage.idb;
		}
	} catch {
		// page navigated away, crashed, or has no document — keep partial snapshot
	}

	try {
		fs.mkdirSync(AUDIT_DIR, { recursive: true });
		const fname = `${sanitizeFilename(snapshot.spec)}__${sanitizeFilename(snapshot.test)}__r${testInfo.retry ?? 0}.json`;
		fs.writeFileSync(path.join(AUDIT_DIR, fname), JSON.stringify(snapshot, null, 2), 'utf8');
	} catch (err) {
		// Last-resort: never break the test because of audit IO.
		console.warn('[cookie-audit] failed to write snapshot:', (err as Error)?.message);
	}
}

/**
 * Extended `test` with an auto fixture that snapshots storage at teardown.
 * The fixture has no body before `await use()` so it adds zero overhead to
 * test setup; everything happens after the test finishes.
 */
const test = baseTest.extend<{ _storageAudit: void }>({
	_storageAudit: [
		async ({ page, context }, use, testInfo) => {
			await use();
			await captureStorage(page, context, testInfo);
		},
		{ auto: true }
	]
});

export { test, expect };
module.exports = { test, expect };
