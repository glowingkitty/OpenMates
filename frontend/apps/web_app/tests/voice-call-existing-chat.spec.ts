/** Voice turns in a chat with existing history, and the first call of a
 * just-signed-up account. External providers are deterministic CI fixtures.
 */
import { randomUUID } from 'node:crypto';
import type { Page } from '@playwright/test';
import { proofAudioLaunchArgs } from './helpers/proof-audio';
import { installNativeVoiceInput } from './helpers/voice-call-test-helpers';
/* eslint-disable @typescript-eslint/no-require-imports -- Existing shared helpers use CommonJS. */
const { expect, test: auditedTest } = require('./helpers/cookie-audit');
const { withProofAudio } = require('./helpers/proof-audio');
// Proof videos carry the call's sound in sync (tests/helpers/proof-audio.ts).
const test = withProofAudio(auditedTest);
const { loginToTestAccount, sendMessage, waitForAssistantMessage } = require('./helpers/chat-test-helpers');
const { withMockMarker } = require('./signup-flow-helpers');
const { expireIsolatedAccessWindow } = require('./helpers/isolated-session-rotation');

test.use({
  actionTimeout: 30_000,
  launchOptions: { args: proofAudioLaunchArgs({ voiceWav: null }) },
  permissions: ['microphone'],
});

test.describe('Voice mode through ordinary chat', () => {
  // Call start diagnostics: attach the controller's console lines to a failed case.
  let callConsole: string[] = [];
  test.beforeEach(async ({page}: {page: Page}) => {
    callConsole = [];
    const relevant=/\[(VoiceCall|CallPermissionPrompt|AssistantSpeech|PermissionDialog|Notifications|E2E)\]/;
    page.on('console', (message) => {
      if (message.type()!=='debug'&&(relevant.test(message.text())||message.type()==='error')) callConsole.push(`${message.type()}: ${message.text()}`.slice(0, 500));
    });
    page.on('pageerror', (error) => { callConsole.push(`pageerror: ${error.message}`.slice(0, 500)); });
  });
  test.afterEach(async ({page: _page}: {page: Page}, testInfo: import('@playwright/test').TestInfo) => {
    if (testInfo.status !== testInfo.expectedStatus && callConsole.length) {
      await testInfo.attach('voice-call-console', {body: callConsole.join('\n'), contentType: 'text/plain'});
    }
  });

  // contract-test: direct surface=gui.web assertions=video-call.audio.single-owner,video-call.chat.typed-input,video-call.chat.transcripts
  test('admits a call turn in an existing chat after the refresh cookie rotates',async({page},testInfo)=>{
    test.setTimeout(120_000);
    await installNativeVoiceInput(page);
    let acceptedCallTurns = 0;
    page.on('websocket', socket => {
      if (new URL(socket.url()).pathname !== '/v1/voice-call') return;
      socket.on('framereceived', ({ payload }) => {
        if (typeof payload === 'string' && JSON.parse(payload).type === 'text_input.accepted') acceptedCallTurns += 1;
      });
    });
    await page.addInitScript(()=>{
      const sockets:string[]=[];
      Object.assign(window,{__voiceSocketPaths:sockets});
      const NativeSocket=window.WebSocket;
      window.WebSocket=new Proxy(NativeSocket,{construct(Target,args){
        const path=new URL(String(args[0]),location.href).pathname;
        if(path==='/v1/voice-call')sockets.push(path);
        return Reflect.construct(Target,args);
      }});
    });
    await loginToTestAccount(page,()=>{},async()=>{});
    await sendMessage(page,withMockMarker('What is the capital of Germany?','chat_flow_capital','fast'),()=>{},async()=>{},'typed-exchange-before-call');
    await waitForAssistantMessage(page,{which:'last',logCheckpoint:()=>{}});
    const chatId=await page.getByTestId('active-chat-container').getAttribute('data-current-chat-id');
    expect(chatId).toBeTruthy();
    const previousReplies = await page.getByTestId('message-assistant').count();

    // The chat socket stays open on its original credential. The newly opened
    // call uses the successor cookie, as after a session refresh in another tab.
    const refreshCookie = async () => (await page.context().cookies())
      .find(cookie => cookie.name === 'auth_refresh_token')?.value;
    const original = await refreshCookie();
    if (!original) throw new Error('Authenticated refresh cookie is missing.');
    const apiUrl = process.env.OPENMATES_E2E_API_URL;
    if (!apiUrl) throw new Error('OPENMATES_E2E_API_URL is required.');
    const sessionId = await page.evaluate(() => sessionStorage.getItem('session_id'));
    expireIsolatedAccessWindow(original);
    const rotated = await page.context().request.post(`${apiUrl}/v1/auth/session`, {
      data: { session_id: sessionId }, headers: { Origin: new URL(page.url()).origin },
    });
    expect(rotated.status()).toBe(200);
    expect((await rotated.json()).success).toBe(true);
    const successor = await refreshCookie();
    expect(Boolean(successor && successor !== original),
      'The refresh publishes a successor cookie.').toBe(true);

    await page.locator('[data-testid="voice-call-start"]:visible').click();
    await expect(page.getByTestId('voice-call-status-text')).toHaveText('Listening · You can speak now',{timeout:45_000});
    expect(await page.evaluate(()=>(window as unknown as {__voiceSocketPaths:string[]}).__voiceSocketPaths)).toHaveLength(1);
    expect(await page.getByTestId('active-chat-container').getAttribute('data-current-chat-id')).toBe(chatId);
    await expect(page.getByTestId('notification').filter({hasText:'Voice calling is unavailable right now'})).toHaveCount(0);
    const question = 'Can you repeat the capital?';
    await page.getByTestId('message-editor').locator('[contenteditable="true"]').click();
    await page.keyboard.insertText(question);
    await page.getByTestId('composer-send-button').click();
    await expect.poll(() => acceptedCallTurns, { message: 'The voice socket must issue the typed turn.' }).toBe(1);
    await expect(page.getByTestId('message-assistant')).toHaveCount(previousReplies + 1, { timeout: 45_000 });
    await expect(page.getByTestId('message-assistant').last()).toContainText(`I received your text: ${question}`, { timeout: 30_000 });
    await page.screenshot({path:testInfo.outputPath('call-after-session-rotation.png')});
    await page.getByTestId('voice-call-hangup').click();
  });
});

test.describe('First voice call of a just-signed-up account', () => {
  const {
    buildSignupEmail, cleanupFailedSignupAccount, configureCloudSignupUiForCi, createSignupEmailClient,
    checkSignupEmailQuota, getE2EDebugUrl, getSignupTestDomain, setToggleChecked, validateSignupInviteIfRequired,
  } = require('./signup-flow-helpers');
  const { openSignupInterface } = require('./helpers/chat-test-helpers');

  // contract-test: direct surface=gui.web assertions=video-call.audio.single-owner
  test('starts the first voice call right after password signup without reload', async ({ page, context }, testInfo) => {
    test.setTimeout(480_000);
    const signupDomain = getSignupTestDomain(process.env.SIGNUP_TEST_EMAIL_DOMAINS);
    test.skip(!signupDomain, 'SIGNUP_TEST_EMAIL_DOMAINS must include a test domain.');
    const emailClient = createSignupEmailClient();
    test.skip(!emailClient, 'A signup test inbox is required.');
    const giftedInvite = process.env.E2E_SIGNUP_GIFTED_INVITE_CODE;
    test.skip(!giftedInvite, 'E2E_SIGNUP_GIFTED_INVITE_CODE is seeded by the isolated CI runner.');
    const quota = await checkSignupEmailQuota();
    test.skip(!quota.available, `Email quota reached (${quota.current}/${quota.limit}).`);
    const { waitForMessage, extractSixDigitCode } = emailClient;

    await installNativeVoiceInput(page);
    // Call and core warnings name the refusal reason when the call does not connect.
    const callConsole: string[] = [];
    page.on('console', (message) => {
      const line = message.text();
      if (/\[(VoiceCall|RustCore)\]/.test(line) && callConsole.length < 200) callConsole.push(`${Math.round(performance.now())} ${message.type()}: ${line.slice(0, 300)}`);
    });
    await page.addInitScript(() => {
      const sockets: string[] = [];
      Object.assign(window, { __voiceSocketPaths: sockets });
      const NativeSocket = window.WebSocket;
      window.WebSocket = new Proxy(NativeSocket, { construct(Target, args) {
        const path = new URL(String(args[0]), location.href).pathname;
        if (path === '/v1/voice-call') sockets.push(path);
        return Reflect.construct(Target, args);
      } });
    });
    await context.grantPermissions(['clipboard-read', 'clipboard-write']);

    const signupEmail = buildSignupEmail(signupDomain);
    const emailLocal = signupEmail.split('@')[0];
    const signupUsername = emailLocal.includes('+') ? emailLocal.split('+')[1] : emailLocal;
    const signupPassword = `Aa1!${randomUUID()}`;
    // This signup uses the single-use invite that carries gifted credits.
    const sharedInvite = process.env.E2E_SIGNUP_INVITE_CODE;
    process.env.E2E_SIGNUP_INVITE_CODE = giftedInvite;
    try {
      await configureCloudSignupUiForCi(page);
      // The invite carries gifted credits, so the new account can pay for the
      // call and the call itself must connect (TASK-950).
      await page.goto(getE2EDebugUrl('/'));
      await openSignupInterface(page);
      const loginTabs = page.getByTestId('login-tabs');
      await expect(loginTabs).toBeVisible();
      await loginTabs.getByRole('button', { name: /sign up/i }).click();
      // Isolated CI signup requires an invite. The shared helper skips the
      // step when the field is not rendered yet, so wait for it first.
      await expect(page.getByTestId('signup-invite-code-input')).toBeVisible({ timeout: 15_000 });
      await validateSignupInviteIfRequired(page, () => undefined);
      await page.locator('input[type="email"][autocomplete="email"]').fill(signupEmail);
      await page.locator('input[autocomplete="username"]').fill(signupUsername);
      await setToggleChecked(page.locator('#terms-agreed-toggle'), true);
      await setToggleChecked(page.locator('#privacy-agreed-toggle'), true);
      const emailRequestedAt = new Date().toISOString();
      await page.getByRole('button', { name: /create new account/i }).click();
      await expect(page.getByRole('link', { name: /open mail app/i })).toBeVisible({ timeout: 10_000 });
      const message = await waitForMessage({ sentTo: signupEmail, receivedAfter: emailRequestedAt });
      const emailCode = extractSixDigitCode(message);
      expect(emailCode, 'Expected a 6-digit email confirmation code.').toBeTruthy();
      await page.locator('input[inputmode="numeric"][maxlength="6"]').fill(emailCode);
      await expect(page.locator('#signup-password-option')).toBeVisible({ timeout: 10_000 });
      await page.locator('#signup-password-option').click();
      const passwordInputs = page.locator('input[autocomplete="new-password"]');
      await expect(passwordInputs).toHaveCount(2);
      await passwordInputs.nth(0).fill(signupPassword);
      await passwordInputs.nth(1).fill(signupPassword);
      await page.locator('#signup-password-continue').click();
      // No reload from here on: the signup profile still has user_id null.
      await expect(page.getByTestId('message-editor')).toBeVisible({ timeout: 30_000 });
      // Accept the invite's gift as the web gift button does (same endpoint, the
      // session's own cookies); the page is not reloaded.
      const gift = await page.evaluate(async (apiUrl: string) => {
        const response = await fetch(`${apiUrl}/v1/auth/accept-gift`, {
          method: 'POST', credentials: 'include', headers: { Accept: 'application/json' },
        });
        const body = await response.json().catch(() => ({}));
        return { status: response.status, success: body.success === true, credits: body.current_credits };
      }, process.env.PLAYWRIGHT_TEST_API_URL!);
      expect(gift, 'the invite gift must be accepted before the call').toMatchObject({ status: 200, success: true });

      // TASK-6308: the call starts in the SAME chat that already holds a typed
      // exchange, as the stalled dev report did (no /v1/voice-call socket).
      await sendMessage(page, withMockMarker('What is the capital of Germany?', 'chat_flow_capital', 'fast'), () => {}, async () => {}, 'signup-typed-exchange');
      await waitForAssistantMessage(page, { which: 'last', logCheckpoint: () => {} });
      const typedChatId = await page.getByTestId('active-chat-container').getAttribute('data-current-chat-id');
      expect(typedChatId, 'the typed exchange must have created a chat').toBeTruthy();

      await page.evaluate(() => {
        const seen: string[] = [];
        Object.assign(window, { __voiceUnavailableSeen: seen });
        setInterval(() => {
          for (const node of document.querySelectorAll('[data-testid="notification"]')) {
            if (node.textContent?.includes('Voice calling is unavailable right now')) seen.push(node.textContent);
          }
        }, 50);
      });
      // Isolated CI acknowledges voice processing by fixture, so no privacy
      // notice appears here; the notice itself is covered by its own case.
      await page.locator('[data-testid="voice-call-start"]:visible').click();
      await expect(page.getByTestId('voice-call-status-text')).toHaveText('Listening · You can speak now', { timeout: 45_000 });
      await page.screenshot({ path: testInfo.outputPath('first-call-after-signup-listening.png') });

      expect(await page.evaluate(() => (window as unknown as { __voiceUnavailableSeen: string[] }).__voiceUnavailableSeen)).toEqual([]);
      await expect(page.getByTestId('notification').filter({ hasText: 'Voice calling is unavailable right now' })).toHaveCount(0);
      expect(await page.evaluate(() => (window as unknown as { __voiceSocketPaths: string[] }).__voiceSocketPaths)).toHaveLength(1);
      expect(await page.getByTestId('active-chat-container').getAttribute('data-current-chat-id'), 'the call stays in the typed chat').toBe(typedChatId);
      // The core admission runs while the call connects (only turns wait for
      // it), so read its final outcome, not the stage shown at Listening. A
      // refused admission ends the call, which the checks below also catch.
      await expect.poll(() => page.evaluate(() => document.documentElement.dataset.rustCoreAdmit), {
        timeout: 45_000, message: 'the call chat must be admitted into the core',
      }).toBe('ok');
      await expect(page.getByTestId('voice-call-status-text')).toHaveText('Listening · You can speak now');
      await expect(page.getByTestId('notification').filter({ hasText: 'Voice calling is unavailable right now' })).toHaveCount(0);
      await page.getByTestId('voice-call-hangup').click();
    } finally {
      const stages = await page.evaluate(() => performance.getEntriesByType('mark')
        .filter(mark => mark.name.startsWith('openmates:rust:'))
        .map(mark => `${Math.round(mark.startTime)} ${mark.name.slice(15)}`)).catch(() => [] as string[]);
      await testInfo.attach('first-call-console.txt', { body: [...callConsole, '--- core stages', ...stages].join('\n'), contentType: 'text/plain' });
      process.env.E2E_SIGNUP_INVITE_CODE = sharedInvite;
      await cleanupFailedSignupAccount(signupEmail, console.log, { testFile: testInfo.file || 'voice-call-existing-chat.spec.ts' });
    }
  });
});
