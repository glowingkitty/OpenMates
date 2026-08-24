/**
 * Tooling-only broker for exact Apple proof credentials.
 * It validates the reserved source slot, streams secrets directly to OpenSSL,
 * and attaches only CMS ciphertext encrypted to the registered Mac.
 * GitHub never receives Mac connectivity and never sends data to the Mac.
 */

// contract-test-file: infrastructure
// proof-video: not_required reason=account_health

import { spawnSync } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import path from 'node:path';

import { expect, test } from '@playwright/test';

const RESERVED_APPLE_PROOF_SLOT = '14';

test('encrypts the reserved Apple proof account for dev-server relay', async ({ browserName: _browserName }, testInfo) => {
	const sourceSlot = process.env.OPENMATES_TEST_ACCOUNT_SOURCE_SLOT;
	expect(sourceSlot).toBe(RESERVED_APPLE_PROOF_SLOT);

	const values = {
		[`OPENMATES_TEST_ACCOUNT_${sourceSlot}_EMAIL`]: process.env.OPENMATES_TEST_ACCOUNT_EMAIL ?? '',
		[`OPENMATES_TEST_ACCOUNT_${sourceSlot}_PASSWORD`]: process.env.OPENMATES_TEST_ACCOUNT_PASSWORD ?? '',
		[`OPENMATES_TEST_ACCOUNT_${sourceSlot}_OTP_KEY`]: process.env.OPENMATES_TEST_ACCOUNT_OTP_KEY ?? ''
	};
	for (const value of Object.values(values)) {
		expect(value.length).toBeGreaterThan(0);
		expect(value).not.toMatch(/[\r\n]/);
	}

	const outputPath = testInfo.outputPath('credentials.cms');
	mkdirSync(path.dirname(outputPath), { recursive: true });
	const certificatePath = path.resolve(
		process.cwd(),
		'../../../deployment/apple-proof-broker-recipient.pem'
	);
	const payload = Buffer.from(
		Object.entries(values)
			.map(([key, value]) => `${key}=${value}\n`)
			.join(''),
		'utf8'
	);
	const encryption = spawnSync(
		'openssl',
		[
			'cms',
			'-encrypt',
			'-binary',
			'-aes256',
			'-outform',
			'DER',
			'-out',
			outputPath,
			certificatePath
		],
		{ input: payload, stdio: ['pipe', 'ignore', 'pipe'] }
	);
	payload.fill(0);
	expect(
		encryption.status,
		`OpenSSL CMS encryption must succeed: ${encryption.stderr?.toString('utf8').trim() ?? 'no stderr'}`
	).toBe(0);
	await testInfo.attach('credentials.cms', {
		path: outputPath,
		contentType: 'application/pkcs7-mime'
	});
});
