/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * frontend/apps/web_app/tests/helpers/cookie-audit.ts
 *
 * Drop-in replacement for `@playwright/test` that auto-captures browser
 * storage at the end of every E2E test — pass or fail.
 *
 * Two separate outputs (split by compliance relevance):
 *   - Cookies → full attributes (domain, path, http_only, secure, same_site,
 *     expires, anonymized example value). Cookies are the only storage type
 *     that actually gates the ePrivacy cookie-banner decision, so we capture
 *     the full attribute set for legal review.
 *   - localStorage / sessionStorage / IndexedDB → KEY NAMES ONLY. No values
 *     are captured or written to disk. This file is an inventory for
 *     "what does this app put on the user's device at all", not a content
 *     dump. The separate browser-storage.yml gives an overview; cookies.yml
 *     is the banner-decision source of truth.
 *
 * Both outputs are merged into YAML by scripts/merge_storage_audits.py after
 * a Playwright suite run and consumed by the twice-weekly legal compliance
 * cronjob (scripts/legal-compliance-scan.sh).
 *
 * Specs use this exactly like @playwright/test:
 *   import { test, expect } from './helpers/cookie-audit';
 *   const { test, expect } = require('./helpers/cookie-audit');
 *
 * The auto-fixture runs without any spec-side opt-in. Failures inside the
 * teardown are swallowed so audit instrumentation can never break a test.
 *
 * Anonymization: cookie values are NEVER captured. Only the value length
 * is recorded (so you can tell "a cookie of 64 chars exists at this name")
 * without exposing the actual content. Local/session storage values are
 * similarly never read — only key names.
 */
export {};

import { test as baseTest, expect } from '@playwright/test';

const fs = require('fs');
const path = require('path');

// Output dir relative to the Playwright cwd (frontend/apps/web_app).
// run_tests.py copies this back to repo-root test-results/ after the run.
const AUDIT_DIR = path.resolve(process.cwd(), 'test-results', 'storage-audits');
const STRICTLY_NECESSARY_THIRD_PARTY_COOKIES = [
	{ name: 'm', domain: 'm.stripe.com' },
	{ name: 'hmt_id', domain: 'api.hcaptcha.com' }
];

interface CookieRecord {
	name: string;
	domain: string;
	path: string;
	expires: number;
	http_only: boolean;
	secure: boolean;
	same_site: string;
	value_length: number;
}

interface StorageSnapshot {
	spec: string;
	test: string;
	status: string;
	captured_at: string;
	url: string | null;
	cookies: CookieRecord[];
	// Key names only — values are intentionally NOT captured. These sections
	// are informational (inventory of what the app stores on-device); only
	// cookies gate the banner-exemption decision.
	local_storage_keys: string[];
	session_storage_keys: string[];
	indexed_db: string[];
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
		local_storage_keys: [],
		session_storage_keys: [],
		indexed_db: []
	};

	// Cookies live on the BrowserContext and survive page closure.
	// We record attributes + value LENGTH only — never the value itself.
	try {
		const cookies = await context.cookies();
		snapshot.cookies = cookies.map((c: any) => ({
			name: c.name,
			domain: c.domain || '',
			path: c.path || '/',
			expires: typeof c.expires === 'number' ? c.expires : -1,
			http_only: !!c.httpOnly,
			secure: !!c.secure,
			same_site: c.sameSite || 'Lax',
			value_length: typeof c.value === 'string' ? c.value.length : 0
		}));
	} catch {
		// context already disposed — leave cookies empty
	}

	// Page-bound storage requires a live page that's still on a same-origin URL.
	// We capture KEY NAMES ONLY — values are never read. This keeps the audit
	// trail lean and avoids any accidental leakage of user state into CI
	// artifacts or the committed browser-storage.yml.
	try {
		if (page && !page.isClosed()) {
			snapshot.url = page.url();
			const webStorage = await page.evaluate(async () => {
				const keys = (s: Storage): string[] => {
					const out: string[] = [];
					for (let i = 0; i < s.length; i++) {
						const k = s.key(i);
						if (k !== null) out.push(k);
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
					local: keys(localStorage),
					session: keys(sessionStorage),
					idb
				};
			});

			snapshot.local_storage_keys = webStorage.local;
			snapshot.session_storage_keys = webStorage.session;
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

/**
 * Inline assertion helper for the `no-third-party-tracking` privacy promise.
 *
 * Reads all cookies from the current BrowserContext and asserts every cookie
 * domain is an OpenMates-owned host (first-party). Any cookie whose domain
 * doesn't match the allowlist is a regression — our privacy policy states
 * explicitly that we do not set third-party tracking cookies.
 *
 * Keep the allowlist narrow — adding a new domain here is a material change
 * to the privacy promise and should be reviewed in shared/docs/privacy_promises.yml.
 */
export async function assertNoThirdPartyCookies(context: any): Promise<void> {
	const FIRST_PARTY_DOMAINS = [
		'openmates.org',
		'openmates.dev',
		'dev.openmates.org',
		'api.dev.openmates.org',
		'localhost',
		'127.0.0.1'
	];
	const cookies: Array<{ name: string; domain: string }> = (await context.cookies()) || [];
	const offenders = cookies.filter((c: any) => {
		const dom = (c.domain || '').replace(/^\./, '').toLowerCase();
		if (!dom) return false;
		if (
			STRICTLY_NECESSARY_THIRD_PARTY_COOKIES.some(
				(ok) => c.name === ok.name && dom === ok.domain
			)
		) {
			return false;
		}
		return !FIRST_PARTY_DOMAINS.some((ok) => dom === ok || dom.endsWith('.' + ok));
	});
	if (offenders.length > 0) {
		const summary = offenders
			.map((c: any) => `${c.name} @ ${c.domain}`)
			.join(', ');
		throw new Error(
			`privacy-promise "no-third-party-tracking" violated: third-party cookie(s) present: ${summary}. ` +
				`Update the allowlist in helpers/cookie-audit.ts only after amending shared/docs/privacy_promises.yml.`
		);
	}
}

export { test, expect };
module.exports = { test, expect, assertNoThirdPartyCookies };
