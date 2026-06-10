/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Provision isolated E2E auth accounts through the OpenMates CLI signup path.
 *
 * This utility spec runs only via manual GitHub Actions dispatch with
 * CREATE_ACCOUNT_SLOT set to 15 or 17. It uses the workflow's existing email
 * polling secrets, writes credential artifacts to the uploaded artifacts
 * directory, and never commits generated credentials to the repository.
 */
export {};

const { spawn } = require('node:child_process');
const path = require('node:path');
const { test, expect } = require('./helpers/cookie-audit');
const {
	createEmailClient,
	getSignupTestDomain,
	buildTestAccountEmail,
	checkEmailQuota
} = require('./signup-flow-helpers');

const SIGNUP_TEST_EMAIL_DOMAINS = process.env.SIGNUP_TEST_EMAIL_DOMAINS;
const CREATE_ACCOUNT_SLOT = process.env.CREATE_ACCOUNT_SLOT;
const DEV_API_URL = 'https://api.dev.openmates.org';

test.describe('CLI E2E auth account provisioning', () => {
	test('creates a reserved account artifact through CLI signup', async () => {
		const slot = parseInt(CREATE_ACCOUNT_SLOT || '', 10);
		test.skip(!CREATE_ACCOUNT_SLOT || ![15, 17].includes(slot), 'CREATE_ACCOUNT_SLOT must be 15 or 17.');
		test.skip(!SIGNUP_TEST_EMAIL_DOMAINS, 'SIGNUP_TEST_EMAIL_DOMAINS is required.');

		const emailClient = createEmailClient();
		test.skip(!emailClient, 'Email credentials required (GMAIL_* or MAILOSAUR_*).');

		const quota = await checkEmailQuota();
		test.skip(!quota.available, `Email quota reached (${quota.current}/${quota.limit}).`);

		test.setTimeout(240000);

		const signupDomain = getSignupTestDomain(SIGNUP_TEST_EMAIL_DOMAINS);
		if (!signupDomain) throw new Error('Missing signup test domain.');

		const accountSlug = `cliprov${slot}${Date.now().toString(36).slice(-6)}`;
		const accountEmail = buildTestAccountEmail(slot, signupDomain, accountSlug);
		const accountUsername = accountSlug;
		const artifactPath = path.resolve(process.cwd(), 'artifacts', `cli-slot-${slot}.env`);
		const cliPath = path.resolve(process.cwd(), '../../packages/openmates-cli/dist/cli.js');
		const emailRequestedAt = new Date().toISOString();

		const child = spawn(
			process.execPath,
			[
				cliPath,
				'--api-url',
				DEV_API_URL,
				'e2e',
				'provision-auth-accounts',
				'--slot',
				String(slot),
				'--artifact',
				artifactPath,
				'--email',
				accountEmail,
				'--username',
				accountUsername,
				'--force'
			],
			{
				cwd: path.resolve(process.cwd(), '../../packages/openmates-cli'),
				env: {
					...process.env,
					NO_COLOR: '1'
				},
				stdio: ['pipe', 'pipe', 'pipe']
			}
		);

		let output = '';
		let promptedForEmailCode = false;
		const waitForPrompt = new Promise<void>((resolve) => {
			const onData = (chunk: Buffer) => {
				output += chunk.toString('utf8');
				if (!promptedForEmailCode && output.includes('Email verification code:')) {
					promptedForEmailCode = true;
					resolve();
				}
			};
			child.stdout.on('data', onData);
			child.stderr.on('data', onData);
		});

		await waitForPrompt;

		const { waitForMailosaurMessage, extractSixDigitCode } = emailClient!;
		const confirmEmail = await waitForMailosaurMessage({
			sentTo: accountEmail,
			receivedAfter: emailRequestedAt
		});
		const emailCode = extractSixDigitCode(confirmEmail);
		expect(emailCode, 'Expected a 6-digit confirmation code.').toBeTruthy();
		child.stdin.write(`${emailCode}\n`);

		const exitCode = await new Promise<number | null>((resolve) => {
			child.on('close', resolve);
		});

		expect(exitCode, output).toBe(0);
		expect(output).toContain('Provisioning artifact written');
	});
});
