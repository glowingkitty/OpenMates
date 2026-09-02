/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Shared chat test helpers for Playwright E2E tests.
 *
 * Extracted from web-search-flow.spec.ts (the most robust implementations).
 * Provides login, new chat, send message, and delete chat helpers.
 *
 * Usage:
 *   const { loginToTestAccount, startNewChat, sendMessage, deleteActiveChat } = require('./helpers/chat-test-helpers');
 *
 * Architecture context: docs/architecture/e2e-testing.md
 */
export {};

const { expect } = require('@playwright/test');
const {
	generateTotp,
	getTestAccount,
	getE2EDebugUrl
} = require('../signup-flow-helpers');

/** No-op screenshot function for when screenshots aren't needed */
const noopScreenshot = async (_page: any, _label: string): Promise<void> => {};

/** No-op log function for when logging isn't needed */
const noopLog = (_message: string, _metadata?: Record<string, unknown>): void => {};

const LOGIN_RATE_LIMIT_COOLDOWN_MS = 65_000;
const MAX_LOGIN_RATE_LIMIT_RETRIES = 1;
const PASSWORD_LOGIN_SIGNAL_TIMEOUT_MS = 45_000;
const CHAT_PREFLIGHT_ACK_TIMEOUT_MS = 60_000;
const SEND_ACCEPTED_TIMEOUT_MS = CHAT_PREFLIGHT_ACK_TIMEOUT_MS + 15_000;
const SYNTHETIC_SEND_DRAFT_IDLE_TIMEOUT_MS = 45_000;
const TRAILING_LIVE_TEST_MARKER = /\s*(<<<TEST_LIVE_(?:MOCK|RECORD):[A-Za-z0-9_-]+(?::[A-Za-z0-9_-]+)?>>>)\s*$/;

type LoginResponseDiagnostic = {
	status: number;
	ok: boolean;
	method: string;
	path: string;
	success?: boolean;
	tfaRequired?: boolean;
	message?: string;
	bodyText?: string;
};

type LoginRejectedSignal = {
	type: 'login-rejected';
	diagnostic: LoginResponseDiagnostic;
};

type LastSendState = {
	assistantCount: number;
	assistantMessageIds: string[];
	assistantLastText: string;
};

type TestStateDeclaration = {
	auth: string;
	browserStorage: 'fresh';
	account: string;
	chat: string;
	notifications: string;
	securityReminders: string;
};

type SendMessageOptions = {
	testMockMarker?: string;
	preserveExistingContent?: boolean;
};

const lastSendStateByPage = new WeakMap<object, LastSendState>();

export function declareTestState(declaration: TestStateDeclaration): Readonly<TestStateDeclaration> {
	for (const [field, value] of Object.entries(declaration)) {
		if (!value) throw new Error(`Test state declaration requires ${field}`);
	}
	return Object.freeze({ ...declaration });
}

export async function createIsolatedBrowserContext(
	browser: any,
	declaration: Readonly<TestStateDeclaration>,
	options: Record<string, unknown> = {}
): Promise<any> {
	if (declaration.browserStorage !== 'fresh') {
		throw new Error('Isolated browser contexts require fresh browser storage');
	}
	return browser.newContext({
		...options,
		storageState: { cookies: [], origins: [] }
	});
}

async function locatorCount(locator: any): Promise<number> {
	return locator.count().catch(() => 0);
}

async function locatorMessageIds(locator: any): Promise<string[]> {
	return locator.evaluateAll((elements: Element[]) =>
		elements
			.map((element) => element.getAttribute('data-message-id') ?? '')
			.filter((messageId): messageId is string => messageId.length > 0)
	).catch(() => []);
}

function visibleMessageAnchors(message: string): string[] {
	const normalized = message
		.replace(/<<<TEST_(?:MOCK|RECORD):[^>]+>>>/g, '')
		.replace(/\s+/g, ' ')
		.trim();
	const withoutFirstWord = normalized.split(' ').slice(1).join(' ');
	return [normalized.slice(0, 80), withoutFirstWord.slice(0, 80)]
		.filter((anchor) => anchor.length >= 20);
}

function normalizeEditorDraftText(text: string | null | undefined): string {
	return (text ?? '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim();
}

export function extractLiveTestMarker(message: string): { message: string; testMockMarker?: string } {
	const match = message.match(TRAILING_LIVE_TEST_MARKER);
	if (!match) return { message };
	return {
		message: message.slice(0, match.index).trimEnd(),
		testMockMarker: match[1]
	};
}

export async function fillMessageEditor(page: any, messageEditor: any, message: string): Promise<void> {
	const expectedText = normalizeEditorDraftText(message);
	const currentText = async (): Promise<string> => normalizeEditorDraftText(
		await messageEditor.evaluate((editor: HTMLElement) => editor.innerText ?? '').catch(() => '')
	);

	await focusMessageEditor(messageEditor);
	await page.keyboard.insertText(message);
	if (await expect.poll(currentText, { timeout: 2500, intervals: [100, 250, 500] })
		.toBe(expectedText)
		.then(() => true)
		.catch(() => false)) {
		return;
	}

	await focusMessageEditor(messageEditor);
	await page.keyboard.press('Control+A');
	await page.keyboard.press('Backspace');
	await page.keyboard.insertText(message);
	await expect.poll(currentText, { timeout: 5000, intervals: [100, 250, 500] }).toBe(expectedText);
}

export async function focusMessageEditor(messageEditor: any): Promise<void> {
	await messageEditor.click({ position: { x: 12, y: 12 }, force: true });
	await expect.poll(
		async () => messageEditor.evaluate((editor: HTMLElement) => {
			const activeElement = document.activeElement;
			return activeElement instanceof HTMLElement
				&& activeElement.isContentEditable
				&& editor.contains(activeElement);
		}),
		{ timeout: 5000, intervals: [100, 250, 500] }
	).toBe(true);
}

async function userMessagePersisted(
	userMessages: any,
	previousCount: number,
	message: string,
	messageEditor?: any,
	assistantMessages?: any,
	previousAssistantCount?: number
): Promise<boolean> {
	const currentCount = await locatorCount(userMessages);
	if (currentCount >= previousCount + 1) {
		return true;
	}

	if (assistantMessages && previousAssistantCount !== undefined) {
		const assistantCount = await locatorCount(assistantMessages);
		if (assistantCount > previousAssistantCount) {
			return true;
		}
	}

	const anchors = visibleMessageAnchors(message);
	if (anchors.length === 0 || currentCount === 0) {
		return false;
	}

	const lastVisibleText = await userMessages.last().textContent({ timeout: 1000 }).catch(() => '');
	const normalizedVisibleText = (lastVisibleText ?? '').replace(/\s+/g, ' ');
	return anchors.some((anchor) => normalizedVisibleText.includes(anchor));
}

async function waitForUserMessageAcceptedByServer(
	page: any,
	userMessages: any,
	assistantMessages: any,
	previousAssistantCount: number,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void
): Promise<void> {
	try {
		await expect
			.poll(
				async () => {
					const assistantCount = await locatorCount(assistantMessages);
					if (assistantCount > previousAssistantCount) {
						return true;
					}

					const userCount = await locatorCount(userMessages);
					if (userCount === 0) {
						return false;
					}

					const lastUserText = await userMessages.last().textContent({ timeout: 1000 }).catch(() => '');
					return !/\b(Sending|Waiting for internet|Waiting for upload)\b/i.test(lastUserText ?? '');
				},
				{ timeout: SEND_ACCEPTED_TIMEOUT_MS }
			)
			.toBeTruthy();
	} catch (error) {
		const lastSendDebug = await page.evaluate(() => (window as any).__lastSendDebug ?? null).catch(() => null);
		const diagnostics = await page.evaluate(() => {
			const input = document.querySelector('[data-action="message-input"]') as HTMLElement | null;
			const lastUser = Array.from(document.querySelectorAll('[data-testid="message-user"]')).at(-1) as HTMLElement | undefined;

			return {
				url: window.location.href,
				inputChatId: input?.getAttribute('data-current-chat-id') ?? null,
				lastUserText: lastUser?.innerText ?? null
			};
		});
		logCheckpoint(`User message stayed pending after send; diagnostics=${JSON.stringify({ diagnostics, lastSendDebug })}`);
		throw error;
	}
}

async function waitForNewChatSendContext(
	page: any,
	startedFromNewChat: boolean,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void
): Promise<void> {
	if (!startedFromNewChat) {
		return;
	}

	await expect(async () => {
		const chatIdFromUrl = page.url().match(/chat-id=([a-zA-Z0-9-]+)/)?.[1] ?? null;
		const messageInput = page.locator('[data-action="message-input"]').last();
		const inputChatId = await messageInput.getAttribute('data-current-chat-id').catch(() => null);
		expect(chatIdFromUrl ?? inputChatId).toBeTruthy();
		expect(chatIdFromUrl ?? inputChatId).not.toBe('new-chat');
	}).toPass({ timeout: 30_000 });

	logCheckpoint('New-chat send rebound to created chat context.', {
		url: page.url()
	});
}

async function refreshStaleAppShellIfPrompted(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void
): Promise<void> {
	const refreshButton = page.getByRole('button', { name: /refresh now/i });
	if (!(await refreshButton.isVisible({ timeout: 1000 }).catch(() => false))) return;

	logCheckpoint('Software update prompt visible after login; refreshing to current deployed app shell.');
	await refreshButton.click();
	await page.waitForLoadState('load');
	await expect(page.getByTestId('message-editor')).toBeVisible({ timeout: 30000 });
}

async function waitForDraftSaveIdleBeforeSyntheticSend(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void
): Promise<void> {
	const readDraftState = async () => page.evaluate(() => {
		const hook = (window as any).__openmatesE2EDraftState;
		return typeof hook === 'function' ? hook() : null;
	}).catch(() => null);

	const initialState = await readDraftState();
	if (!initialState?.isSaveInProgress) return;

	logCheckpoint('Waiting for draft save to become idle before synthetic send.', { draftState: initialState });
	await expect
		.poll(
			async () => {
				const state = await readDraftState();
				return state ? state.isSaveInProgress === false : true;
			},
			{ timeout: SYNTHETIC_SEND_DRAFT_IDLE_TIMEOUT_MS, intervals: [500, 1000, 2000, 5000] }
		)
		.toBe(true);
}

async function waitForAuthenticatedUi(page: any, authSignal: any, timeout = 20000): Promise<boolean> {
	const authDom = authSignal.waitFor({ state: 'visible', timeout })
		.then(() => true)
		.catch(() => false);

	const editorVisible = page.getByTestId('message-editor').waitFor({ state: 'visible', timeout })
		.then(() => true)
		.catch(() => false);

	return Promise.race([authDom, editorVisible]);
}

async function readLoginResponseDiagnostic(response: any): Promise<LoginResponseDiagnostic> {
	const request = response.request();
	const url = new URL(response.url());
	const diagnostic: LoginResponseDiagnostic = {
		status: response.status(),
		ok: response.ok(),
		method: request.method(),
		path: url.pathname
	};

	try {
		const data = await response.json();
		if (typeof data?.success === 'boolean') diagnostic.success = data.success;
		if (typeof data?.tfa_required === 'boolean') diagnostic.tfaRequired = data.tfa_required;
		if (typeof data?.message === 'string') diagnostic.message = data.message;
	} catch {
		try {
			diagnostic.bodyText = (await response.text()).slice(0, 300);
		} catch {
			// Ignore unreadable bodies; status and path still identify the failed request.
		}
	}

	return diagnostic;
}

function isRejectedLoginDiagnostic(diagnostic: LoginResponseDiagnostic): boolean {
	return !diagnostic.ok || diagnostic.success === false;
}

function isLoginRejectedSignal(signal: unknown): signal is LoginRejectedSignal {
	return Boolean(signal && typeof signal === 'object' && (signal as LoginRejectedSignal).type === 'login-rejected');
}

async function waitForRejectedLoginResponse(
	page: any,
	options: { ignoreStatuses?: number[] } = {}
): Promise<LoginRejectedSignal | null> {
	const response = await page.waitForResponse(
		async (candidate: any) => {
			try {
				const request = candidate.request();
				const url = new URL(candidate.url());
				if (request.method() !== 'POST' || !url.pathname.endsWith('/v1/auth/login')) return false;
				const diagnostic = await readLoginResponseDiagnostic(candidate);
				if (options.ignoreStatuses?.includes(diagnostic.status)) return false;
				return isRejectedLoginDiagnostic(diagnostic);
			} catch {
				return false;
			}
		},
		{ timeout: PASSWORD_LOGIN_SIGNAL_TIMEOUT_MS }
	).catch(() => null);

	if (!response) return null;
	return {
		type: 'login-rejected',
		diagnostic: await readLoginResponseDiagnostic(response)
	};
}

async function waitForLoginSuccessAfterSubmit(page: any, authSignal: any): Promise<boolean> {
	const loginResponse = page.waitForResponse(
		(response: any) => response.url().includes('/v1/auth/login') && response.request().method() === 'POST',
		{ timeout: 20000 }
	).catch(() => null);

	const authUi = waitForAuthenticatedUi(page, authSignal).then((success) => success ? 'ui' as const : false as const);
	const firstSignal = await Promise.race([
		loginResponse.then((response) => response ? 'response' as const : false as const),
		authUi
	]);

	if (firstSignal === 'ui') {
		return true;
	}

	if (firstSignal !== 'response') {
		return false;
	}

	const response = await loginResponse;
	if (!response) {
		return false;
	}

	try {
		const data = await response.json();
		if (!response.ok() || data?.success !== true || data?.tfa_required === true) {
			return false;
		}
	} catch {
		return false;
	}

	if (await waitForAuthenticatedUi(page, authSignal, 8000)) {
		return true;
	}

	// The backend may have accepted the OTP and set cookies while the modal missed
	// the client-side auth transition. Reload once and let startup auth initialize.
	await page.goto(getE2EDebugUrl('/'));
	await page.waitForLoadState('load');
	return waitForAuthenticatedUi(page, authSignal, 20000);
}

async function waitForOtpOrAuthenticated(
	page: any,
	otpInput: any,
	authSignal: any,
	timeout = PASSWORD_LOGIN_SIGNAL_TIMEOUT_MS,
	loginRateLimited?: Promise<'rate-limited'>,
	loginRejected?: Promise<LoginRejectedSignal | null>
): Promise<'otp' | 'auth' | 'rate-limited' | LoginRejectedSignal | null> {
	return Promise.race([
		otpInput.waitFor({ state: 'visible', timeout }).then(() => 'otp' as const).catch(() => null),
		authSignal.waitFor({ state: 'visible', timeout }).then(() => 'auth' as const).catch(() => null),
		...(loginRateLimited ? [loginRateLimited] : []),
		...(loginRejected ? [loginRejected] : []),
		page.waitForTimeout(timeout).then(() => null)
	]);
}

function captureLoginResponseDiagnostics(
	page: any,
	loginResponses: LoginResponseDiagnostic[]
): () => void {
	const onResponse = async (response: any) => {
		try {
			const request = response.request();
			const url = new URL(response.url());
			if (request.method() !== 'POST' || !url.pathname.endsWith('/v1/auth/login')) return;
			loginResponses.push(await readLoginResponseDiagnostic(response));
			if (loginResponses.length > 5) loginResponses.shift();
		} catch {
			// Ignore malformed diagnostic events; the login flow itself owns failures.
		}
	};
	page.on('response', onResponse);
	return () => page.off('response', onResponse);
}

async function getLoginSubmitDiagnostics(
	page: any,
	loginResponses: LoginResponseDiagnostic[] = []
): Promise<Record<string, unknown>> {
	return Promise.race([
		page.evaluate(() => ({
			url: window.location.href,
			isAuthenticated: document.querySelector('[data-authenticated="true"]') !== null,
			hasOtpInput: document.querySelector('[data-testid="login-otp-input"]') !== null,
			hasErrorMessage: document.querySelector('[data-testid="error-message"]')?.textContent?.trim() || null,
			modalText: document.querySelector('[data-testid="signup-modal"], [data-testid="login-modal"]')?.textContent?.slice(0, 300) || null,
		})).then((domDiagnostics: Record<string, unknown>) => ({
			...domDiagnostics,
			loginResponses: [...loginResponses],
			lastLoginResponse: loginResponses.at(-1) ?? null
		})),
		new Promise<Record<string, unknown>>((resolve) => {
			setTimeout(() => resolve({ error: 'login diagnostics timed out after 2000ms' }), 2000);
		})
	]).catch((error: Error) => ({ error: error.message }));
}

async function waitForLoginSuccessAfterSubmitWithDiagnostics(
	page: any,
	authSignal: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void,
	loginResponses: LoginResponseDiagnostic[] = []
): Promise<boolean> {
	const timeoutMs = 30_000;
	let timeoutId: ReturnType<typeof setTimeout> | undefined;
	try {
		return await Promise.race([
			waitForLoginSuccessAfterSubmit(page, authSignal),
			new Promise<boolean>((resolve) => {
				timeoutId = setTimeout(() => resolve(false), timeoutMs);
			})
		]);
	} finally {
		if (timeoutId) clearTimeout(timeoutId);
		const diagnostics = await getLoginSubmitDiagnostics(page, loginResponses);
		logCheckpoint('Post-login-submit diagnostics.', diagnostics);
	}
}

async function hasStoredEmailSalt(page: any): Promise<boolean> {
	return page.evaluate(() => {
		return Boolean(
			sessionStorage.getItem('openmates_email_salt') ||
				localStorage.getItem('openmates_email_salt')
		);
	}).catch(() => false);
}

async function waitForEmailLookupReady(page: any): Promise<boolean> {
	const passwordInput = page.getByTestId('login-password-input');
	const passwordVisible = passwordInput.waitFor({ state: 'visible', timeout: 15000 })
		.then(() => true)
		.catch(() => false);
	const saltReady = page.waitForFunction(
		() => Boolean(
			sessionStorage.getItem('openmates_email_salt') ||
				localStorage.getItem('openmates_email_salt')
		),
		undefined,
		{ timeout: 15000 }
	).then(() => true).catch(() => false);

	const [hasPasswordInput, hasSalt] = await Promise.all([passwordVisible, saltReady]);
	return hasPasswordInput && hasSalt;
}

async function clickLoginContinueWhenReady(page: any): Promise<void> {
	const continueButton = page.getByTestId('login-continue-button');
	await expect(continueButton).toBeVisible({ timeout: 10000 });
	await expect(continueButton).toBeEnabled({ timeout: 15000 });
	await continueButton.click();
}

async function ensureStayLoggedInChecked(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void = noopLog
): Promise<void> {
	const stayLoggedInLabel = page.locator(
		'label.toggle[for="stayLoggedIn"], label.toggle:has(#stayLoggedIn)'
	);
	try {
		await stayLoggedInLabel.waitFor({ state: 'visible', timeout: 3000 });
		const checkbox = page.locator('#stayLoggedIn');
		const isChecked = await checkbox.evaluate((el: HTMLInputElement) => el.checked);
		if (!isChecked) {
			await stayLoggedInLabel.click();
			logCheckpoint('Clicked "Stay logged in" toggle.');
		} else {
			logCheckpoint('"Stay logged in" toggle was already on.');
		}
	} catch {
		logCheckpoint('Could not find "Stay logged in" toggle — proceeding without it.');
	}
}

/**
 * Login to the test account with email, password, and 2FA OTP.
 * Checks "Stay logged in" so keys are persisted to IndexedDB.
 * Includes retry logic for OTP timing edge cases and 429 rate limits.
 */
async function loginToTestAccount(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void = noopLog,
	takeStepScreenshot: (page: any, label: string) => Promise<void> = noopScreenshot,
	options: {
		waitForEditor?: boolean;
		credentials?: { email?: string; password?: string; otpKey?: string };
		rateLimitRetryCount?: number;
	} = {}
): Promise<void> {
	const {
		email: TEST_EMAIL,
		password: TEST_PASSWORD,
		otpKey: TEST_OTP_KEY
	} = options.credentials ?? getTestAccount();

	// Monitor the password login endpoint separately so a 429 cannot masquerade as an OTP timeout.
	let hit429 = false;
	let signalLoginRateLimited: (() => void) | undefined;
	const loginRateLimited = new Promise<'rate-limited'>((resolve) => {
		signalLoginRateLimited = () => resolve('rate-limited');
	});
	const on429 = (response: any) => {
		if (response.status() === 429) {
			hit429 = true;
			if (new URL(response.url()).pathname.endsWith('/v1/auth/login')) {
				signalLoginRateLimited?.();
			}
		}
	};
	page.on('response', on429);

	await page.goto(getE2EDebugUrl('/'));
	// Wait for all resources (scripts + hydration) to load before checking buttons.
	await page.waitForLoadState('load');

	// Clear any rate-limit flags from previous test runs that would hide the login form
	await page.evaluate(() => {
		localStorage.removeItem('emailLookupRateLimit');
		localStorage.removeItem('loginRateLimit');
		localStorage.removeItem('passwordTfaRateLimit');
	});

	await takeStepScreenshot(page, 'home');

	// The intro banner on the home page hides the header login button and shows its own.
	await openSignupInterface(page, 30000);
	await takeStepScreenshot(page, 'signup-interface-opened');

	// Click the "Login" tab in the login/signup tab bar to switch to the login form
	const loginTab = page.getByTestId('tab-login');
	await expect(loginTab).toBeVisible({ timeout: 10000 });
	await loginTab.click();
	logCheckpoint('Clicked Login tab to switch from signup to login view.');
	await takeStepScreenshot(page, 'login-dialog');

	const emailInput = page.getByTestId('login-email-input');
	await expect(emailInput).toBeVisible({ timeout: 15000 });
	await emailInput.fill(TEST_EMAIL);

	// Click "Stay logged in" toggle so keys survive any page navigation during the test.
	await ensureStayLoggedInChecked(page, logCheckpoint);

	await clickLoginContinueWhenReady(page);
	logCheckpoint('Entered email and clicked continue.');

	// Retry if lookup fails before password login. 429 shows a rate-limit view,
	// while transient 5xx/CORS failures can leave the password form visible but
	// without the stored email salt required for password hash generation.
	let lookupReady = await waitForEmailLookupReady(page);
	for (let retryCount = 0; retryCount < 3 && (!lookupReady || hit429); retryCount++) {
		const waitSec = hit429 ? 5 + retryCount * 5 : 3 + retryCount * 3;
		const hasSalt = await hasStoredEmailSalt(page);
		logCheckpoint(
			`Email lookup not ready (hit429=${hit429}, hasSalt=${hasSalt}); waiting ${waitSec}s before retry ${retryCount + 1}...`
		);
		hit429 = false;
		await page.waitForTimeout(waitSec * 1000);

		// Clear the client-side rate-limit flag so the form reappears
		await page.evaluate(() => {
			localStorage.removeItem('emailLookupRateLimit');
			localStorage.removeItem('loginRateLimit');
		});

		// Reload the page to reset the EmailLookup component state
		await page.goto(getE2EDebugUrl('/'));
		await page.waitForLoadState('load');
		await openSignupInterface(page, 30000);
		const retryLoginTab = page.getByTestId('tab-login');
		await expect(retryLoginTab).toBeVisible({ timeout: 10000 });
		await retryLoginTab.click();

		const retryEmailInput = page.getByTestId('login-email-input');
		await expect(retryEmailInput).toBeVisible({ timeout: 15000 });
		await retryEmailInput.fill(TEST_EMAIL);
		await ensureStayLoggedInChecked(page, logCheckpoint);
		await clickLoginContinueWhenReady(page);
		logCheckpoint(`Retry ${retryCount + 1}: re-entered email and clicked continue.`);
		lookupReady = await waitForEmailLookupReady(page);
	}

	if (!lookupReady) {
		throw new Error('Login email lookup did not store the email salt or show a usable password step.');
	}

	const passwordInput = page.getByTestId('login-password-input');
	await expect(passwordInput).toBeVisible({ timeout: 15000 });
	await passwordInput.fill(TEST_PASSWORD);
	await takeStepScreenshot(page, 'password-entered');

	// Submit password first — OTP field only appears after backend confirms 2FA is required
	// (anti-enumeration: OTP is never shown upfront, only after first login attempt).
	const submitLoginButton = page.getByTestId('login-submit-button');
	await expect(submitLoginButton).toBeVisible();
	const loginResponses: LoginResponseDiagnostic[] = [];
	const stopCapturingLoginResponses = captureLoginResponseDiagnostics(page, loginResponses);
	try {
		const loginRejected = waitForRejectedLoginResponse(page, { ignoreStatuses: [429] });
		await submitLoginButton.click();
		logCheckpoint('Submitted password — waiting for 2FA prompt or direct login.');

		// Positive auth signal: ActiveChat.svelte sets data-authenticated="true" on the
		// container div when authStore.isAuthenticated becomes true. This is the most
		// reliable login success detector because it's driven directly by the canonical
		// auth state, not by UI visibility heuristics (which can race with animations).
		const authSignal = page.locator('[data-authenticated="true"]');
		const otpInput = page.getByTestId('login-otp-input');

		// Race: either OTP field appears (2FA required) or login succeeds immediately
		// (2FA not configured for this account). Some test accounts may have lost their
		// encrypted_tfa_secret, causing the backend to bypass 2FA entirely.
		const otpOrAuth = await waitForOtpOrAuthenticated(
			page,
			otpInput,
			authSignal,
			PASSWORD_LOGIN_SIGNAL_TIMEOUT_MS,
			loginRateLimited,
			loginRejected
		);
		if (isLoginRejectedSignal(otpOrAuth)) {
			const diagnostics = await getLoginSubmitDiagnostics(page, [
				...loginResponses,
				otpOrAuth.diagnostic
			]);
			logCheckpoint('Password login rejected by backend.', diagnostics);
			throw new Error(`Password login rejected by /v1/auth/login: ${JSON.stringify(otpOrAuth.diagnostic)}`);
		}
		if (otpOrAuth === 'rate-limited') {
			const retryCount = options.rateLimitRetryCount ?? 0;
			if (retryCount >= MAX_LOGIN_RATE_LIMIT_RETRIES) {
				throw new Error('Login remained rate limited after the bounded cooldown retry.');
			}
			logCheckpoint(`Password login rate limited; waiting ${LOGIN_RATE_LIMIT_COOLDOWN_MS / 1000}s before one retry.`);
			await page.waitForTimeout(LOGIN_RATE_LIMIT_COOLDOWN_MS);
			return loginToTestAccount(page, logCheckpoint, takeStepScreenshot, {
				...options,
				rateLimitRetryCount: retryCount + 1
			});
		}
		if (!otpOrAuth) {
			const diagnostics = await getLoginSubmitDiagnostics(page, loginResponses);
			logCheckpoint(
				`Login did not show OTP input or authenticated UI within ${PASSWORD_LOGIN_SIGNAL_TIMEOUT_MS / 1000}s after password submit.`,
				diagnostics
			);
			throw new Error(`Login did not show OTP input or authenticated UI within ${PASSWORD_LOGIN_SIGNAL_TIMEOUT_MS / 1000}s after password submit.`);
		}

		let loginSuccess = false;

		if (otpOrAuth === 'auth') {
			// Login succeeded without 2FA — backend determined tfa_enabled=false
			loginSuccess = true;
			logCheckpoint('Login successful without 2FA — data-authenticated="true" detected.');
		} else {
			// OTP field appeared — proceed with TOTP entry
			logCheckpoint('2FA prompt visible — entering OTP.');

			const errorMessage = page
				.getByTestId('error-message')
				.filter({ hasText: /wrong|invalid|incorrect/i });

			// OTP retry strategy: try current window, then adjacent windows to handle GHA clock drift.
			// GHA runners can have 1-2s clock skew from the server, causing the TOTP code to be
			// rejected. By cycling through window offsets [0, -1, 1, 0, -1] across 5 attempts,
			// we cover the current window and both adjacent windows.
			const MAX_OTP_ATTEMPTS = 5;
			const WINDOW_OFFSETS = [0, -1, 1, 0, -1];

			for (let attempt = 1; attempt <= MAX_OTP_ATTEMPTS && !loginSuccess; attempt++) {
				// Avoid TOTP window boundary race: if we're in the last 5s of a 30s window,
				// wait for the next window so the generated code is valid long enough.
				const nowSec = Math.floor(Date.now() / 1000);
				const secondsIntoWindow = nowSec % 30;
				if (secondsIntoWindow >= 25) {
					const waitMs = (30 - secondsIntoWindow) * 1000 + 2000;
					logCheckpoint(`Near TOTP window boundary (${secondsIntoWindow}s in), waiting ${waitMs}ms...`);
					await page.waitForTimeout(waitMs);
				}

				const windowOffset = WINDOW_OFFSETS[attempt - 1];
				const otpCode = generateTotp(TEST_OTP_KEY, windowOffset);
				await otpInput.fill(otpCode);
				logCheckpoint(`Generated and entered OTP (attempt ${attempt}, window offset ${windowOffset}).`);
				if (attempt === 1) {
					await takeStepScreenshot(page, 'otp-entered');
				}

				await expect(submitLoginButton).toBeVisible();
				const loginSuccessPromise = waitForLoginSuccessAfterSubmitWithDiagnostics(page, authSignal, logCheckpoint, loginResponses);
				await submitLoginButton.click();
				logCheckpoint('Submitted login form.');

				try {
					if (!(await loginSuccessPromise)) {
						throw new Error('Login success signal did not appear after OTP submit');
					}
					loginSuccess = true;
					logCheckpoint('Login successful — OTP login success signal detected.');
				} catch {
					const hasError = await errorMessage.isVisible().catch(() => false);
					if (hasError && attempt < MAX_OTP_ATTEMPTS) {
						logCheckpoint(`OTP attempt ${attempt} failed, retrying with different window offset...`);
						// Wait longer between retries to allow time window to advance.
						await page.waitForTimeout(attempt <= 2 ? 3000 : 5000);
					} else if (attempt === MAX_OTP_ATTEMPTS) {
						throw new Error(`Login failed after ${MAX_OTP_ATTEMPTS} OTP attempts`);
					}
				}
			}
		}

		const { waitForEditor = true } = options;
		if (waitForEditor) {
			logCheckpoint('Waiting for chat interface to load...');
			// Brief settle time for post-auth UI transitions (WebSocket connect, phased sync start).
			// Reduced from 3000ms — the auth state transition is now reliable (see fix in
			// PasswordAndTfaOtp.svelte handleSuccessfulLogin Phase 1/Phase 2 split).
			await page.waitForTimeout(1000);
			const messageEditor = page.getByTestId('message-editor');
			await expect(messageEditor).toBeVisible({ timeout: 20000 });
			await refreshStaleAppShellIfPrompted(page, logCheckpoint);
			logCheckpoint('Chat interface loaded - message editor visible.');
		} else {
			logCheckpoint('Login complete (skipping editor wait).');
			await page.waitForTimeout(1000);
		}
	} finally {
		page.off('response', on429);
		stopCapturingLoginResponses();
	}
}

/**
 * Submit password and handle OTP if required. For use by specs with inline login code.
 *
 * After filling the password input and calling this function, it will:
 * 1. Click the submit button
 * 2. Race: wait for either OTP field or data-authenticated="true"
 * 3. If OTP field appears: fill OTP with TOTP retry logic and submit
 * 4. If auth signal appears: login succeeded without 2FA
 *
 * @param page      - Playwright Page
 * @param otpKey    - TOTP secret key for generating OTP codes
 * @param log       - Optional log function
 */
async function submitPasswordAndHandleOtp(
	page: any,
	otpKey: string,
	log: (msg: string) => void = () => {}
): Promise<void> {
	const loginResponses: LoginResponseDiagnostic[] = [];
	const stopCapturingLoginResponses = captureLoginResponseDiagnostics(page, loginResponses);
	try {
		const submitBtn = page.getByTestId('login-submit-button');
		await expect(submitBtn).toBeVisible();
		const loginRejected = waitForRejectedLoginResponse(page);
		await submitBtn.click();
		log('Submitted password — waiting for 2FA prompt or direct login.');

		const authSignal = page.locator('[data-authenticated="true"]');
		const otpInput = page.getByTestId('login-otp-input');

		const otpOrAuth = await waitForOtpOrAuthenticated(
			page,
			otpInput,
			authSignal,
			PASSWORD_LOGIN_SIGNAL_TIMEOUT_MS,
			undefined,
			loginRejected
		);
		if (isLoginRejectedSignal(otpOrAuth)) {
			const diagnostics = await getLoginSubmitDiagnostics(page, [
				...loginResponses,
				otpOrAuth.diagnostic
			]);
			log(`Password login rejected by backend; diagnostics=${JSON.stringify(diagnostics)}`);
			throw new Error(`Password login rejected by /v1/auth/login: ${JSON.stringify(otpOrAuth.diagnostic)}`);
		}
		if (!otpOrAuth) {
			const diagnostics = await getLoginSubmitDiagnostics(page, loginResponses);
			log(
				`Login did not show OTP input or authenticated UI within ${PASSWORD_LOGIN_SIGNAL_TIMEOUT_MS / 1000}s after password submit; diagnostics=${JSON.stringify(diagnostics)}`
			);
			throw new Error(`Login did not show OTP input or authenticated UI within ${PASSWORD_LOGIN_SIGNAL_TIMEOUT_MS / 1000}s after password submit.`);
		}

		if (otpOrAuth === 'auth') {
			log('Login successful without 2FA.');
			// Brief settle for post-auth navigation (URL change, WebSocket connect).
			// Auth signal fires before the router navigates to the chat view.
			await page.waitForTimeout(2000);
			return;
		}

		log('2FA prompt visible — entering OTP.');
		const MAX_OTP_ATTEMPTS = 5;
		const WINDOW_OFFSETS = [0, -1, 1, 0, -1];

		for (let attempt = 1; attempt <= MAX_OTP_ATTEMPTS; attempt++) {
			const nowSec = Math.floor(Date.now() / 1000);
			const secondsIntoWindow = nowSec % 30;
			if (secondsIntoWindow >= 25) {
				await page.waitForTimeout((30 - secondsIntoWindow) * 1000 + 2000);
			}

			const otpCode = generateTotp(otpKey, WINDOW_OFFSETS[attempt - 1]);
			await otpInput.fill(otpCode);
			log(`OTP attempt ${attempt}, offset ${WINDOW_OFFSETS[attempt - 1]}.`);

			await expect(submitBtn).toBeVisible();
			const loginSuccessPromise = waitForLoginSuccessAfterSubmit(page, authSignal);
			await submitBtn.click();

			try {
				if (!(await loginSuccessPromise)) {
					throw new Error('Login success signal did not appear after OTP submit');
				}
				log('Login successful — OTP login success signal detected.');
				return;
			} catch {
				if (attempt === MAX_OTP_ATTEMPTS) {
					throw new Error(`Login failed after ${MAX_OTP_ATTEMPTS} OTP attempts`);
				}
				log(`OTP attempt ${attempt} failed, retrying...`);
				await page.waitForTimeout(attempt <= 2 ? 3000 : 5000);
			}
		}
	} finally {
		stopCapturingLoginResponses();
	}
}

/**
 * Start a new chat session by clicking the new chat button.
 * Uses data-testid and data-action for stable selectors.
 */
async function startNewChat(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void = noopLog
): Promise<void> {
	await page.waitForTimeout(1000);

	const currentUrl = page.url();
	const previousChatId = currentUrl.match(/chat-id=([a-zA-Z0-9-]+)/)?.[1] ?? null;
	const messageInput = page.locator('[data-action="message-input"]').last();
	const previousInputChatId = await messageInput.getAttribute('data-current-chat-id').catch(() => null);
	const previousContextId = previousChatId ?? previousInputChatId;
	logCheckpoint(`Current URL before starting new chat: ${currentUrl}`);

	// If the editor has focus, the adjacent new-chat CTA is intentionally hidden.
	// Blur before probing selectors so we do not create fake draft state just to
	// reveal the button.
	await page.keyboard.press('Escape').catch(() => undefined);
	await page.locator('body').click({ position: { x: 1, y: 1 }, timeout: 1000 }).catch(() => undefined);
	await page.waitForTimeout(300);

	// Try stable selectors in priority order. Use locator(...).last() instead of
	// getByTestId() so duplicate mobile/desktop/new-chat CTAs don't trigger strict
	// mode once one visible instance exists.
	const newChatButton = page.locator('[data-testid="new-chat-button"]').last();
	let clicked = false;

	if (await newChatButton.isVisible({ timeout: 3000 }).catch(() => false)) {
		logCheckpoint('Found New Chat button via data-testid');
		await newChatButton.click();
		clicked = true;
		await page.waitForTimeout(2000);
	}

	if (!clicked) {
		// Fallback: try data-action attribute
		const actionButton = page.locator('[data-action="new-chat"]').first();
		if (await actionButton.isVisible({ timeout: 3000 }).catch(() => false)) {
			logCheckpoint('Found New Chat button via data-action');
			await actionButton.click();
			clicked = true;
			await page.waitForTimeout(2000);
		}
	}

	if (!clicked) {
		// Fallback: try aria-label
		const ariaButton = page.locator('button[aria-label*="New"], button[aria-label*="new"]').first();
		if (await ariaButton.isVisible({ timeout: 3000 }).catch(() => false)) {
			logCheckpoint('Found New Chat button via aria-label');
			await ariaButton.click();
			clicked = true;
			await page.waitForTimeout(2000);
		}
	}

	if (!clicked) {
		const attachedNewChatButton = page.locator('[data-testid="new-chat-button"], [data-action="new-chat"]').first();
		if (await attachedNewChatButton.count().catch(() => 0)) {
			const clickedAttached = await attachedNewChatButton.evaluate((button: HTMLElement) => {
				button.click();
				return true;
			}).catch(() => false);
			if (clickedAttached) {
				logCheckpoint('Triggered attached New Chat button via DOM fallback.');
				clicked = true;
				await page.waitForTimeout(2000);
			}
		}
	}

	if (!clicked) {
		const messageEditor = page.getByTestId('message-editor');
		if (await messageEditor.isVisible({ timeout: 3000 }).catch(() => false)) {
			await expect(async () => {
				expect(page.url()).not.toMatch(/chat-id=/);
				expect(await messageInput.getAttribute('data-current-chat-id')).toBeTruthy();
			}).toPass({ timeout: 10000 });
			logCheckpoint('New Chat button not visible; editor is stably bound to new chat.');
		} else {
			logCheckpoint('WARNING: Could not find New Chat button or ready message editor.');
		}
	}

	const newUrl = page.url();
	await expect(async () => {
		expect(page.url()).not.toMatch(/chat-id=/);
		const contextId = await messageInput.getAttribute('data-current-chat-id');
		expect(contextId).toBeTruthy();
		if (clicked && previousContextId) {
			expect(contextId).not.toBe(previousContextId);
		}
	}).toPass({ timeout: 10000 });

	const stableContextId = await messageInput.getAttribute('data-current-chat-id');
	await page.waitForTimeout(2000);
	await expect(async () => {
		expect(page.url()).not.toMatch(/chat-id=/);
		expect(await messageInput.getAttribute('data-current-chat-id')).toBe(stableContextId);
	}).toPass({ timeout: 10000 });
	logCheckpoint('Message input is stable in new chat context.');
	logCheckpoint(`URL after attempting to start new chat: ${newUrl}`);
}

/**
 * Send a message in the chat editor and wait for the send to complete.
 * Uses data-testid and data-action for stable selectors.
 */
async function sendMessage(
	page: any,
	message: string,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void = noopLog,
	takeStepScreenshot: (page: any, label: string) => Promise<void> = noopScreenshot,
	stepLabel: string = 'msg',
	options: SendMessageOptions = {}
): Promise<void> {
	const extractedMessage = extractLiveTestMarker(message);
	message = extractedMessage.message;
	const testMockMarker = options.testMockMarker ?? extractedMessage.testMockMarker;
	const currentChatId = page.url().match(/chat-id=([a-zA-Z0-9-]+)/)?.[1] ?? null;
	const startedFromNewChat = !currentChatId;
	const currentChatInput = currentChatId
		? page.locator(`[data-action="message-input"][data-current-chat-id="${currentChatId}"]`).last()
		: null;
	const inputScope = currentChatInput && await currentChatInput.isVisible({ timeout: 1000 }).catch(() => false)
		? currentChatInput
		: page;
	const messageField = inputScope.getByTestId('message-field').last();
	const messageEditor = messageField.getByTestId('message-editor');
	await expect(messageEditor).toBeVisible();
	const userMessages = page.getByTestId('message-user');
	const assistantMessages = page.getByTestId('message-assistant');
	const userCountBeforeSend = await locatorCount(userMessages);
	const assistantCountBeforeSend = await locatorCount(assistantMessages);
	const assistantMessageIdsBeforeSend = await locatorMessageIds(assistantMessages);
	const assistantLastTextBeforeSend = assistantCountBeforeSend > 0
		? ((await assistantMessages.last()
			.textContent({ timeout: 1000 })
			.catch(() => '')) ?? '').trim()
		: '';
	const expectedEditorText = normalizeEditorDraftText(message);
	const currentEditorText = async (): Promise<string> => normalizeEditorDraftText(
		await messageEditor
			.evaluate((editor: HTMLElement) => editor.innerText ?? '')
			.catch(() => '')
	);
	const waitForEditorMessage = async (timeout = 2500): Promise<boolean> => expect
		.poll(async () => {
			const editorText = await currentEditorText();
			return options.preserveExistingContent
				? editorText.includes(expectedEditorText)
				: editorText === expectedEditorText;
		}, { timeout, intervals: [100, 250, 500] })
		.toBe(true)
		.then(() => true)
		.catch(() => false);
	const retypeEditorMessage = async (reason: string): Promise<void> => {
		await messageEditor.click();
		await page.keyboard.press('Control+A');
		await page.keyboard.press('Backspace');
		await page.keyboard.insertText(message);
		if (!(await waitForEditorMessage(5000))) {
			logCheckpoint(`Editor did not retain message after retype; diagnostics=${JSON.stringify({
				reason,
				expectedEditorText,
				actualEditorText: await currentEditorText()
			})}`);
			throw new Error(`Message editor did not retain typed message after ${reason}`);
		}
		logCheckpoint(reason);
	};
	const ensureEditorMessage = async (): Promise<void> => {
		if (await waitForEditorMessage()) return;

		logCheckpoint(`Editor did not retain initial typed message; retyping before send. diagnostics=${JSON.stringify({
			expectedEditorText,
			actualEditorText: await currentEditorText()
		})}`);
		await retypeEditorMessage('Retyped message after editor did not retain initial input.');
	};

	await messageEditor.click();
	await page.keyboard.insertText(message);
	logCheckpoint(`Typed message: "${message}"`);
	await ensureEditorMessage();
	await takeStepScreenshot(page, `${stepLabel}-message-typed`);

	const sendButton = messageField.locator('[data-action="send-message"]');
	const captureSendDiagnostics = async () => {
		return messageField.evaluate((field: HTMLElement) => {
			const wrapper = field.closest('[data-action="message-input"]') as HTMLElement | null;
			const editor = field.querySelector('[data-testid="message-editor"]') as HTMLElement | null;
			const button = field.querySelector('[data-action="send-message"]') as HTMLButtonElement | null;
			const buttonRect = button?.getBoundingClientRect();
			const fieldRect = field.getBoundingClientRect();

			return {
				wrapperChatId: wrapper?.getAttribute('data-current-chat-id') ?? null,
				editorText: editor?.innerText ?? null,
				editorHtml: editor?.innerHTML?.slice(0, 500) ?? null,
				editorConnected: editor?.isConnected ?? false,
				buttonConnected: button?.isConnected ?? false,
				buttonDisabled: button?.disabled ?? null,
				buttonText: button?.textContent?.trim() ?? null,
				buttonRect: buttonRect
					? { x: buttonRect.x, y: buttonRect.y, width: buttonRect.width, height: buttonRect.height }
					: null,
				fieldRect: { x: fieldRect.x, y: fieldRect.y, width: fieldRect.width, height: fieldRect.height }
			};
		});
	};
	const readLastSendDebug = async () => {
		return page.evaluate(() => {
			return (window as Window & { __openmatesLastSendDebug?: unknown }).__openmatesLastSendDebug ?? null;
		});
	};
	const dispatchSyntheticSend = async (reason: string) => {
		await waitForDraftSaveIdleBeforeSyntheticSend(page, logCheckpoint);
		const syntheticDispatchResult = await messageEditor.evaluate((editor: HTMLElement, marker?: string) => {
			return editor.dispatchEvent(new CustomEvent('custom-send-message', {
				bubbles: true,
				cancelable: true,
				detail: marker ? { testMockMarker: marker } : undefined
			}));
		}, testMockMarker);
		logCheckpoint(`Dispatched synthetic custom-send-message ${reason}; diagnostics=${JSON.stringify({
			syntheticDispatchResult,
			lastSendDebug: await readLastSendDebug(),
			diagnostics: await captureSendDiagnostics()
		})}`);
	};
	const sendAlreadyInProgress = async () => {
		const stopButtonVisible = await page
			.getByTestId('stop-processing-button')
			.isVisible({ timeout: 500 })
			.catch(() => false);
		if (stopButtonVisible) return true;

		const lastSendDebug = await readLastSendDebug();
		const debug = typeof lastSendDebug === 'object' && lastSendDebug !== null
			? lastSendDebug as { step?: unknown; timestamp?: unknown }
			: null;
		const step = debug?.step;
		const timestamp = typeof debug?.timestamp === 'string' ? Date.parse(debug.timestamp) : 0;
		const isFreshDebugStep = timestamp > 0 && Date.now() - timestamp < 10_000;
		return typeof step === 'string' && [
			'send_invoked',
			'send_guard_acquired',
			'local_message_dispatch_started'
		].includes(step) && isFreshDebugStep;
	};
	const waitForSendAlreadyStarted = async () => {
		return expect
			.poll(
				async () => {
					if (await sendAlreadyInProgress()) return true;
					return userMessagePersisted(
						userMessages,
						userCountBeforeSend,
						message,
						messageEditor,
						assistantMessages,
						assistantCountBeforeSend
					);
				},
				{ timeout: 10_000, intervals: [500, 1000, 2000] }
			)
			.toBeTruthy()
			.then(() => true)
			.catch(() => false);
	};
	try {
		await expect(sendButton).toBeVisible({ timeout: 5000 });
		if (testMockMarker) {
			await dispatchSyntheticSend('with E2E server content override');
		} else {
			await sendButton.click({ timeout: 5000 });
			logCheckpoint('Clicked send button.');
		}
	} catch (clickError) {
		const diagnosticsBeforeFallback = await captureSendDiagnostics();
		const lastSendDebugAfterClickAttempt = await readLastSendDebug();
		logCheckpoint(`Send button click did not complete; diagnostics=${JSON.stringify({
			clickError: clickError instanceof Error ? clickError.message : String(clickError),
			lastSendDebug: lastSendDebugAfterClickAttempt,
			diagnostics: diagnosticsBeforeFallback
		})}`);
		if (await waitForSendAlreadyStarted()) {
			logCheckpoint('Send appears to be in progress; skipping duplicate fallback dispatch.');
		} else if ((diagnosticsBeforeFallback.editorText ?? '').trim() === '') {
			await retypeEditorMessage('Retyped message after editor reset before send button was available.');
			await takeStepScreenshot(page, `${stepLabel}-message-retyped`);
			await dispatchSyntheticSend('after retype');
		} else {
			await dispatchSyntheticSend('after send button click failed');
		}
	}
	try {
		await expect
			.poll(
				async () =>
					await userMessagePersisted(
						userMessages,
						userCountBeforeSend,
						message,
						messageEditor,
						assistantMessages,
						assistantCountBeforeSend
					),
				{ timeout: 60000, intervals: [1000, 2000, 5000] }
			)
			.toBeTruthy();
	} catch (error) {
		const diagnosticsBeforeSynthetic = await captureSendDiagnostics();
		const lastSendDebugAfterClick = await readLastSendDebug();
		logCheckpoint(`Send did not persist user message after click; diagnostics=${JSON.stringify({
			userCountBeforeSend,
			userCountAfterClick: await locatorCount(userMessages),
			lastSendDebug: lastSendDebugAfterClick,
			diagnostics: diagnosticsBeforeSynthetic
		})}`);
		if (await sendAlreadyInProgress()) {
			logCheckpoint('Send is still in progress after initial persistence wait; waiting without synthetic dispatch.');
			await expect
				.poll(
					async () =>
						await userMessagePersisted(
							userMessages,
							userCountBeforeSend,
							message,
							messageEditor,
							assistantMessages,
							assistantCountBeforeSend
						),
					{ timeout: 90000, intervals: [1000, 2000, 5000] }
				)
				.toBeTruthy();
		} else {
			if ((diagnosticsBeforeSynthetic.editorText ?? '').trim() === '') {
				await retypeEditorMessage('Retyped message before synthetic persistence fallback.');
			}

			await dispatchSyntheticSend('after persistence timeout');
			await expect
				.poll(
					async () =>
						await userMessagePersisted(
							userMessages,
							userCountBeforeSend,
							message,
							messageEditor,
							assistantMessages,
							assistantCountBeforeSend
						),
					{ timeout: 30000, intervals: [1000, 2000, 5000] }
				)
				.toBeTruthy()
				.catch(() => undefined);
			const userCountAfterSynthetic = await locatorCount(userMessages);
			logCheckpoint(`Synthetic custom-send-message diagnostic completed; diagnostics=${JSON.stringify({
				userCountAfterSynthetic,
				lastSendDebug: await readLastSendDebug(),
				diagnostics: await captureSendDiagnostics()
			})}`);
		}
		if (
			await userMessagePersisted(
				userMessages,
				userCountBeforeSend,
				message,
				messageEditor,
				assistantMessages,
				assistantCountBeforeSend
			)
		) {
			await waitForUserMessageAcceptedByServer(
				page,
				userMessages,
				assistantMessages,
				assistantCountBeforeSend,
				logCheckpoint
			);
			await waitForNewChatSendContext(page, startedFromNewChat, logCheckpoint);
			lastSendStateByPage.set(page, {
				assistantCount: assistantCountBeforeSend,
				assistantMessageIds: assistantMessageIdsBeforeSend,
				assistantLastText: assistantLastTextBeforeSend
			});
			logCheckpoint('Message send accepted after synthetic send fallback.', {
				assistantCountBeforeSend
			});
			return;
		}
		throw error;
	}
	await waitForUserMessageAcceptedByServer(
		page,
		userMessages,
		assistantMessages,
		assistantCountBeforeSend,
		logCheckpoint
	);
	await waitForNewChatSendContext(page, startedFromNewChat, logCheckpoint);
	lastSendStateByPage.set(page, {
		assistantCount: assistantCountBeforeSend,
		assistantMessageIds: assistantMessageIdsBeforeSend,
		assistantLastText: assistantLastTextBeforeSend
	});
	logCheckpoint('Message send accepted after send.', {
		assistantCountBeforeSend
	});
}

/**
 * Delete the active chat via context menu (best-effort cleanup).
 * Does not fail the test if cleanup is not possible.
 */
async function deleteActiveChat(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void = noopLog,
	takeStepScreenshot: (page: any, label: string) => Promise<void> = noopScreenshot,
	stepLabel: string = 'cleanup'
): Promise<void> {
	logCheckpoint('Attempting to delete the chat (best-effort cleanup)...');

	try {
		const sidebarToggle = page.getByTestId('sidebar-toggle');
		if (await sidebarToggle.isVisible({ timeout: 1000 }).catch(() => false)) {
			await sidebarToggle.click({ timeout: 3000 });
			await page.waitForTimeout(500);
		}

		const activeChatItem = page.locator('[data-testid="chat-item-wrapper"].active');

		if (!(await activeChatItem.isVisible({ timeout: 5000 }).catch(() => false))) {
			logCheckpoint('No active chat item visible - skipping cleanup.');
			return;
		}

		// Identify demo / legal chats by their chat_id prefix (see
		// frontend/packages/ui/src/demo_chats/convertToChat.ts:isDemoChat /
		// isLegalChat). Title-based detection used to false-match any legitimate
		// chat whose title happened to contain "OpenMates" (e.g. "Search OpenMates
		// AI assistant" from skill-web-search.spec.ts), which made the cleanup
		// return early and triggered a cascade console-monitor assertion failure.
		// The chat-item-wrapper carries data-chat-id — use that as the canonical
		// identity source.
		try {
			const chatId = await activeChatItem.getAttribute('data-chat-id');
			const chatTitle = await activeChatItem
				.getByTestId('chat-title')
				.textContent({ timeout: 1000 })
				.catch(() => null);
			logCheckpoint(
				`Active chat: id="${chatId ?? 'unknown'}" title="${chatTitle ?? 'unknown'}"`
			);

			if (chatId && (chatId.startsWith('demo-') || chatId.startsWith('legal-'))) {
				logCheckpoint(`Skipping deletion - ${chatId} is a demo/legal chat.`);
				return;
			}
		} catch {
			logCheckpoint('Could not read active chat identity.');
		}

		await activeChatItem.click({ button: 'right', timeout: 5000 });
		await takeStepScreenshot(page, `${stepLabel}-context-menu-open`);
		logCheckpoint('Opened chat context menu.');

		await page.waitForTimeout(300);
		const deleteButton = page.getByTestId('chat-context-delete');

		if (!(await deleteButton.isVisible({ timeout: 3000 }).catch(() => false))) {
			logCheckpoint('Delete button not visible in context menu - skipping cleanup.');
			await page.keyboard.press('Escape');
			return;
		}

		// Bound every click with an explicit 5s timeout. Without these, a flaky
		// context-menu render (button briefly obscured, overlay intercepts, etc.)
		// would cause .click() to wait up to the entire test timeout (240s+)
		// before throwing, eating all remaining budget and marking an otherwise-
		// successful test as timedOut during this non-fatal cleanup.
		await deleteButton.click({ timeout: 5000 });
		await takeStepScreenshot(page, `${stepLabel}-delete-confirm-mode`);
		logCheckpoint('Clicked delete, now in confirm mode.');

		await deleteButton.click({ timeout: 5000 });
		logCheckpoint('Confirmed chat deletion.');

		await expect(activeChatItem).not.toBeVisible({ timeout: 10000 });
		await takeStepScreenshot(page, `${stepLabel}-chat-deleted`);
		logCheckpoint('Verified chat deletion successfully.');
	} catch (error) {
		// Best-effort cleanup — never let a cleanup hang eat the test timeout.
		// Try to dismiss any stuck context menu so subsequent tests see a
		// clean state.
		logCheckpoint(`Cleanup failed (non-fatal): ${error}`);
		try {
			await page.keyboard.press('Escape');
		} catch {
			/* noop */
		}
	}
}

/**
 * Wait for an assistant message to appear in the chat.
 */
async function waitForAssistantResponse(page: any, timeout = 60000): Promise<any> {
	const assistantMessage = page.getByTestId('message-assistant');
	await expect(assistantMessage.first()).toBeVisible({ timeout });
	return assistantMessage;
}

/**
 * Wait for the chat UI to be ready for sending a message after login.
 *
 * Addresses a common flake: specs that send a message immediately after
 * `loginToTestAccount` occasionally race the initial WebSocket connect /
 * phased sync, causing the message to be sent before chatSyncService has
 * finished its startup handshake. The symptom downstream is that the
 * assistant response element never renders (or renders into a chat that
 * is then rehydrated and lost).
 *
 * Preconditions checked:
 *  1. `data-authenticated="true"` marker is present (set by ActiveChat.svelte
 *     when authStore.isAuthenticated flips to true).
 *  2. `message-editor` is visible.
 *  3. Dev-only E2E hook reports the browser online and chat WebSocket ready.
 *
 * The send button is intentionally absent while the composer is empty, so it is
 * not a reliable readiness signal for specs that only need post-login UI access.
 */
async function waitForChatReady(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void = noopLog,
	timeout = 30000
): Promise<void> {
	const start = Date.now();
	const budget = () => Math.max(1000, timeout - (Date.now() - start));

	await expect(page.locator('[data-authenticated="true"]')).toBeVisible({ timeout: budget() });
	await expect(page.getByTestId('message-editor')).toBeVisible({ timeout: budget() });
	await expect(page.locator('[data-hash-router-ready="true"]')).toBeVisible({ timeout: budget() });

	let lastConnectionState: Record<string, unknown> | null = null;
	try {
		await expect.poll(async () => {
			lastConnectionState = await page.evaluate(async () => {
				const testWindow = window as unknown as {
					__openmatesE2EChatConnectionState?: () => Promise<{
						online: boolean;
						websocketConnected: boolean;
						cachePrimed: boolean;
					}>;
				};
				if (typeof testWindow.__openmatesE2EChatConnectionState !== 'function') {
					return { hookAvailable: false, online: window.navigator.onLine };
				}
				const state = await testWindow.__openmatesE2EChatConnectionState();
				return { hookAvailable: true, ...state };
			}).catch((error: unknown) => ({ hookAvailable: false, error: String(error) }));

			return Boolean(
				lastConnectionState.hookAvailable &&
				lastConnectionState.online &&
				lastConnectionState.websocketConnected &&
				lastConnectionState.cachePrimed
			);
		}, {
			timeout: budget(),
			intervals: [250, 500, 1000]
		})
		.toBe(true);
	} catch (error) {
		throw new Error(`Chat transport not ready: ${JSON.stringify(lastConnectionState)}. Original: ${error}`);
	}

	logCheckpoint('Chat UI ready: authenticated + editor + hash router + transport ready.', lastConnectionState ?? undefined);
}

async function dismissSecurityReminderIfPresent(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void = noopLog
): Promise<void> {
	const reminder = page.getByTestId('notification').filter({ hasText: 'Security Reminder' });
	if (!(await reminder.isVisible({ timeout: 2000 }).catch(() => false))) return;

	// The animated stack wrapper can intercept its own visible dismiss button.
	await reminder.getByTestId('notification-dismiss').click({ timeout: 5000, force: true });
	await expect(reminder).not.toBeVisible({ timeout: 10000 });
	logCheckpoint('Dismissed security reminder.');
}

/**
 * Robust wait for an assistant message. Replaces the fragile pattern
 *   `await expect(page.getByTestId('message-assistant').last()).toBeVisible({ timeout: 45000 })`
 * which was failing ~9 nightly specs whenever CI AI latency exceeded the hard-coded
 * timeout or when multiple messages were being rendered.
 *
 * Lifecycle modelled here:
 *  1. Stream-started gate: wait for either a `typing-indicator` or a new
 *     `message-assistant` element to appear (max 30s).
 *  2. Visibility: wait for the targeted `message-assistant.{first|last|nth}` to be visible.
 *  3. Optional text anchor (`contains`) — same mechanism `chat-flow.spec.ts` uses
 *     (await expect(msg).toContainText('Berlin', { timeout })).
 *
 * Defaults to a generous 120s total timeout to cover slow GitHub Actions AI latency
 * while remaining well under the 6-minute Playwright default.
 *
 * @param opts.which  'first' | 'last' (default 'last')
 * @param opts.nth    Zero-based index; overrides `which` when provided.
 * @param opts.contains  Text that must appear in the message body.
 * @param opts.timeout  Total budget in ms (default 120000).
 * @returns The Playwright Locator for the matched assistant message.
 */
async function waitForAssistantMessage(
	page: any,
	opts: {
		which?: 'first' | 'last';
		nth?: number;
		contains?: string | RegExp;
		timeout?: number;
		logCheckpoint?: (message: string, metadata?: Record<string, unknown>) => void;
	} = {}
): Promise<any> {
	const {
		which = 'last',
		nth,
		contains,
		timeout = 120000,
		logCheckpoint = noopLog
	} = opts;

	const start = Date.now();
	const budget = () => Math.max(1000, timeout - (Date.now() - start));
	const lastSendState = lastSendStateByPage.get(page);
	const assistantMessages = page.getByTestId('message-assistant');

	const shouldWaitForNewAssistant = lastSendState && (which !== 'first' || lastSendState.assistantCount === 0);
	if (shouldWaitForNewAssistant) {
		const currentAssistantCount = await locatorCount(assistantMessages);
		const minimumAssistantCount =
			typeof nth === 'number'
				? Math.max(nth + 1, lastSendState.assistantCount + 1)
				: Math.min(lastSendState.assistantCount + 1, currentAssistantCount + 1);
		const previousAssistantMessageIds = new Set(lastSendState.assistantMessageIds);
		await expect
			.poll(async () => {
				const assistantCount = await locatorCount(assistantMessages);
				if (assistantCount >= minimumAssistantCount) return true;

				// New-chat sends can replace old chat bubbles with a shorter fresh history.
				// Detect that response by ID instead of requiring the old count to grow.
				if (previousAssistantMessageIds.size > 0 && assistantCount > 0) {
					const assistantMessageIds = await locatorMessageIds(assistantMessages);
					if (assistantMessageIds.some((messageId) => !previousAssistantMessageIds.has(messageId))) {
						return true;
					}
				}

				// ChatHistory merges adjacent assistant continuations into one bubble.
				// In that case the count stays stable, but the last assistant text expands.
				if (assistantCount > 0 && lastSendState.assistantLastText) {
					const lastText = ((await assistantMessages.last()
						.textContent({ timeout: 1000 })
						.catch(() => '')) ?? '').trim();
					return lastText.length > lastSendState.assistantLastText.length
						&& lastText !== lastSendState.assistantLastText;
				}

				return false;
			}, { timeout: budget() })
			.toBeTruthy();
		logCheckpoint(`Assistant response attached or merged (target count>=${minimumAssistantCount}).`);
	}

	// Stage 1 — stream-started gate.
	// Wait for any evidence that the AI pipeline has accepted the message.
	// Either the typing-indicator appears, or an assistant message begins rendering.
	const streamStartGate = page.locator(
		'[data-testid="typing-indicator"], [data-testid="message-assistant"]'
	);
	const gateTimeout = Math.min(60000, budget());
	try {
		await expect(streamStartGate.first()).toBeVisible({ timeout: gateTimeout });
		logCheckpoint('Assistant stream started (typing indicator or message bubble appeared).');
	} catch (err) {
		throw new Error(
			`waitForAssistantMessage: stream never started within ${gateTimeout}ms ` +
				`(neither typing-indicator nor message-assistant appeared). Original: ${err}`
		);
	}

	// Stage 2 — target the specific assistant message and wait for it to render.
	const target =
		typeof nth === 'number'
			? assistantMessages.nth(nth)
			: which === 'first'
				? assistantMessages.first()
				: assistantMessages.last();

	await expect(target).toBeVisible({ timeout: budget() });
	logCheckpoint(`Assistant message visible (${nth !== undefined ? `nth=${nth}` : which}).`);

	// Stage 3 — optional text anchor.
	if (contains !== undefined) {
		await expect(target).toContainText(contains, { timeout: budget() });
		logCheckpoint(`Assistant message contains expected text: ${String(contains)}`);
	}

	return target;
}

/**
 * Returns true if the header login/signup button is visible.
 */
async function isSignupInterfaceVisible(page: any, timeout = 5000): Promise<boolean> {
	const headerBtn = page.getByTestId('header-login-signup-btn');
	return headerBtn.isVisible({ timeout }).catch(() => false);
}

/**
 * Open the login/signup dialog.
 *
 * Clicks the intro banner signup button when present, otherwise the header
 * login/signup button. Includes a reload-retry on first failure to handle
 * Svelte hydration or locale-loading races.
 */
async function openSignupInterface(page: any, timeout = 15000): Promise<void> {
	for (let attempt = 0; attempt < 2; attempt++) {
		const bannerBtn = page.getByTestId('banner-signup-button');
		const headerBtn = page.getByTestId('header-login-signup-btn');
		try {
			if (await bannerBtn.isVisible({ timeout: Math.min(timeout, 8000) }).catch(() => false)) {
				await bannerBtn.click({ timeout });
				return;
			}
			await headerBtn.waitFor({ state: 'visible', timeout });
			await headerBtn.click({ timeout });
			return;
		} catch (e) {
			if (attempt === 0) {
				await page.reload();
				await page.waitForLoadState('load');
				continue;
			}
			throw e;
		}
	}
}

module.exports = {
	declareTestState,
	createIsolatedBrowserContext,
	fillMessageEditor,
	focusMessageEditor,
	extractLiveTestMarker,
	loginToTestAccount,
	submitPasswordAndHandleOtp,
	openSignupInterface,
	isSignupInterfaceVisible,
	startNewChat,
	sendMessage,
	deleteActiveChat,
	waitForAssistantResponse,
	waitForChatReady,
	dismissSecurityReminderIfPresent,
	waitForAssistantMessage
};
