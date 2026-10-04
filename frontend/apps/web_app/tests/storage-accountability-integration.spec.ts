/** Isolated Directus write proof for the P-1 operational accountability policy. */
import { test } from '@playwright/test';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import {
	closeSync, constants, lstatSync, openSync, readFileSync, realpathSync, statSync
} from 'node:fs';
import { isAbsolute, join } from 'node:path';

const COLLECTIONS = ['chats', 'messages', 'embeds', 'embed_diffs', 'test_results'];
const CONTAINER_DIR = '/app/ci-accountability';
const PROBE = '/app/backend/scripts/storage_accountability_integration.py';
const SHA_RE = /^[0-9a-f]{40}$/;
const PREFIX_RE = /^ci-accountability\/[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

type Profile = {
	source: string;
	compose: string;
	selectorContainer: string;
	receiptContainer: string;
	privateDir: string;
	selector: { schema: string; source_commit: string; fixture_prefix: string };
};

function readProfile(): Profile {
	if (process.env.E2E_STORAGE_ACCOUNTABILITY !== '1') throw new Error('accountability_profile_missing');
	const source = process.env.E2E_STORAGE_ACCOUNTABILITY_SOURCE_COMMIT || '';
	const compose = process.env.E2E_STORAGE_ACCOUNTABILITY_COMPOSE_FILE || '';
	const selectorContainer = process.env.E2E_STORAGE_ACCOUNTABILITY_SELECTOR_FILE || '';
	const receiptContainer = process.env.E2E_STORAGE_ACCOUNTABILITY_RECEIPT_FILE || '';
	const privateDir = process.env.E2E_STORAGE_ACCOUNTABILITY_PRIVATE_DIR || '';
	if (!SHA_RE.test(source) || !isAbsolute(compose) || !isAbsolute(privateDir)
		|| selectorContainer !== `${CONTAINER_DIR}/selector.json`
		|| receiptContainer !== `${CONTAINER_DIR}/receipt.json`) {
		throw new Error('accountability_profile_paths_invalid');
	}
	const privateInfo = lstatSync(privateDir);
	if (!privateInfo.isDirectory() || privateInfo.isSymbolicLink()
		|| (privateInfo.mode & 0o777) !== 0o700
		|| privateInfo.uid !== process.getuid?.() || privateInfo.gid !== process.getgid?.()) {
		throw new Error('accountability_private_dir_invalid');
	}
	if (!statSync(compose).isFile() || !realpathSync(compose).includes('/ci-private/')) {
		throw new Error('accountability_compose_invalid');
	}
	const selectorPath = join(privateDir, 'selector.json');
	const selectorInfo = lstatSync(selectorPath);
	if (!selectorInfo.isFile() || selectorInfo.isSymbolicLink()
		|| (selectorInfo.mode & 0o777) !== 0o600 || selectorInfo.size > 4096
		|| selectorInfo.uid !== privateInfo.uid || selectorInfo.gid !== privateInfo.gid) {
		throw new Error('accountability_selector_invalid');
	}
	const selector = JSON.parse(readFileSync(selectorPath, 'utf8'));
	if (!selector || typeof selector !== 'object' || Array.isArray(selector)
		|| Object.keys(selector).sort().join(',') !== 'fixture_prefix,schema,source_commit'
		|| selector.schema !== 'storage-accountability-selector-v1'
		|| selector.source_commit !== source || !PREFIX_RE.test(selector.fixture_prefix)) {
		throw new Error('accountability_selector_mismatch');
	}
	return { source, compose, selectorContainer, receiptContainer, privateDir, selector };
}

function requireProfile(): Profile {
	try {
		return readProfile();
	} catch {
		throw new Error('accountability_profile_invalid');
	}
}

function runProbe(profile: Profile, step: 'prove' | 'cleanup'): Record<string, unknown> {
	const outputPath = join(profile.privateDir, `${step}.stdout.log`);
	const errorPath = join(profile.privateDir, `${step}.stderr.log`);
	const flags = constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW;
	let stdout = -1;
	let stderr = -1;
	try {
		stdout = openSync(outputPath, flags, 0o600);
		stderr = openSync(errorPath, flags, 0o600);
		const args = [
			'compose', '-f', profile.compose, 'exec', '-T', 'api', 'python',
			PROBE, step, '--selector-file', profile.selectorContainer
		];
		if (step === 'prove') args.push('--receipt-file', profile.receiptContainer);
		const result = spawnSync('docker', args, {
			stdio: ['ignore', stdout, stderr], timeout: step === 'prove' ? 120_000 : 45_000
		});
		if (result.error || result.status !== 0 || result.signal) {
			throw new Error(`accountability_${step}_subprocess_failed`);
		}
		const info = statSync(outputPath);
		if (info.size > 1024 * 1024) throw new Error(`accountability_${step}_output_unbounded`);
		const lines = readFileSync(outputPath, 'utf8').trim().split(/\r?\n/);
		const parsed = JSON.parse(lines.at(-1) || '');
		if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
			throw new Error(`accountability_${step}_summary_invalid`);
		}
		return parsed;
	} catch {
		throw new Error(`accountability_${step}_failed`);
	} finally {
		if (stdout >= 0) closeSync(stdout);
		if (stderr >= 0) closeSync(stderr);
	}
}

function readReceipt(profile: Profile): void {
	const path = join(profile.privateDir, 'receipt.json');
	const info = lstatSync(path);
	if (!info.isFile() || info.isSymbolicLink() || (info.mode & 0o777) !== 0o600
		|| info.size > 16 * 1024) throw new Error('accountability_receipt_invalid');
	let receipt: any;
	try {
		receipt = JSON.parse(readFileSync(path, 'utf8'));
	} catch {
		throw new Error('accountability_receipt_json_invalid');
	}
	const encodedSelector = '{' + Object.keys(profile.selector).sort()
		.map((key) => `${JSON.stringify(key)}: ${JSON.stringify(profile.selector[key as keyof typeof profile.selector])}`)
		.join(', ') + '}';
	const selectorDigest = createHash('sha256').update(encodedSelector).digest('hex');
	if (receipt.schema !== 'storage-accountability-receipt-v1')
		throw new Error('accountability_receipt_schema_invalid');
	if (receipt.source_commit !== profile.source)
		throw new Error('accountability_receipt_source_invalid');
	if (receipt.selector_digest !== selectorDigest)
		throw new Error('accountability_receipt_selector_digest_invalid');
	if (JSON.stringify(receipt.collections) !== JSON.stringify(COLLECTIONS))
		throw new Error('accountability_receipt_collections_invalid');
	if (!Array.isArray(receipt.fixture_ids) || receipt.fixture_ids.length !== 5
		|| new Set(receipt.fixture_ids).size !== 5)
		throw new Error('accountability_receipt_fixture_count_invalid');
	if (receipt.product_embed_diffs_persisted !== true)
		throw new Error('accountability_receipt_product_diff_invalid');
	if (receipt.cleanup_complete !== true)
		throw new Error('accountability_receipt_cleanup_invalid');
	for (const phase of ['audit_before', 'audit_after', 'audit_after_cleanup']) {
		const counts = receipt[phase];
		if (!counts || Object.keys(counts).sort().join(',') !== [...COLLECTIONS].sort().join(',')
			|| COLLECTIONS.some((collection) => JSON.stringify(counts[collection]) !== '[0,0]')) {
			throw new Error(`accountability_receipt_${phase}_invalid`);
		}
	}
	const comparison = receipt.comparison;
	if (!comparison || comparison.sample !== 'five synthetic create/update pairs per policy'
		|| comparison.audit_bytes_kind !== 'serialized_json_utf8_not_postgres_relation_bytes'
		|| comparison.all_fixture_cleanup_complete !== true
		|| comparison.metadata_restored_to_null !== true) {
		throw new Error('accountability_comparison_contract_failed');
	}
	for (const elapsed of [comparison.null_write_elapsed_ms, comparison.all_write_elapsed_ms]) {
		if (!elapsed || Object.keys(elapsed).sort().join(',') !== [...COLLECTIONS].sort().join(',')) {
			throw new Error('accountability_comparison_elapsed_missing');
		}
		for (const collection of COLLECTIONS) {
			if (!Number.isFinite(elapsed[collection].create) || elapsed[collection].create < 0
				|| !Number.isFinite(elapsed[collection].update) || elapsed[collection].update < 0) {
				throw new Error('accountability_comparison_elapsed_invalid');
			}
		}
	}
	if (!comparison.all_audit
		|| Object.keys(comparison.all_audit).sort().join(',') !== [...COLLECTIONS].sort().join(',')) {
		throw new Error('accountability_comparison_audit_missing');
	}
	if (!comparison.null_audit
		|| Object.keys(comparison.null_audit).sort().join(',') !== [...COLLECTIONS].sort().join(',')) {
		throw new Error('accountability_comparison_null_audit_missing');
	}
	for (const collection of COLLECTIONS) {
		const audit = comparison.all_audit[collection];
		const nullAudit = comparison.null_audit[collection];
		for (const kind of ['activity', 'revisions']) {
			if (nullAudit?.counts?.[kind] !== 0
				|| nullAudit?.serialized_json_bytes?.[kind] !== 0) {
				throw new Error('accountability_comparison_null_audit_invalid');
			}
			if (!Number.isInteger(audit?.counts?.[kind]) || audit.counts[kind] < 1
				|| !Number.isInteger(audit?.serialized_json_bytes?.[kind])
				|| audit.serialized_json_bytes[kind] < 1) {
				throw new Error('accountability_comparison_audit_invalid');
			}
		}
	}
}

function requireReceipt(profile: Profile): void {
	try {
		readReceipt(profile);
	} catch (error) {
		if (error instanceof Error && /^accountability_(receipt|comparison)_[a-z0-9_]+$/.test(error.message)) {
			throw error;
		}
		throw new Error('accountability_receipt_io_failed');
	}
}

test.describe.configure({ retries: 0 });
// contract-test: infrastructure
// eslint-disable-next-line no-empty-pattern -- Playwright requires destructured fixtures; this API-only test creates no browser.
test('isolated Directus writes retain product diffs without generic activity or revisions', async ({}, testInfo) => {
	test.setTimeout(180_000);
	if (testInfo.retry !== 0) throw new Error('accountability_single_attempt_only');
	const profile = requireProfile(); // All guards run before any subprocess or fixture mutation.
	let started = false;
	let failure: Error | null = null;
	try {
		started = true;
		const summary = runProbe(profile, 'prove');
		if (summary.passed !== true || summary.collections !== 5 || summary.audit_rows !== 0
			|| summary.product_embed_diffs_persisted !== true || summary.cleanup_complete !== true
			|| summary.comparison_complete !== true) {
			throw new Error('accountability_proof_summary_failed');
		}
		requireReceipt(profile);
	} catch (error) {
		failure = error instanceof Error ? error : new Error('accountability_proof_failed');
	} finally {
		if (started) {
			try {
				const cleanup = runProbe(profile, 'cleanup');
				if (cleanup.cleanup_complete !== true || cleanup.residual_product_rows !== 0
					|| cleanup.metadata_restored_to_null !== true) {
					failure = new Error('accountability_cleanup_failed');
				}
			} catch {
				failure = new Error('accountability_cleanup_failed');
			}
		}
	}
	if (failure) throw failure;
});
