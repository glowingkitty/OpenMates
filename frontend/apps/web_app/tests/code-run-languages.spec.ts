/* eslint-disable @typescript-eslint/no-require-imports */
export {};

const { test, expect, attachConsoleListeners, attachNetworkListeners } = require('./console-monitor');
const { getTestAccount, withMockMarker, createSignupLogger, createStepScreenshotter } = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat, sendMessage, deleteActiveChat } = require('./helpers/chat-test-helpers');
const { openFullscreen, closeFullscreen } = require('./helpers/embed-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

for (const [language, extension] of [
 ['Python', 'py'], ['JavaScript', 'js'], ['TypeScript', 'ts'], ['shell', 'sh'],
 ['C', 'c'], ['C++', 'cpp'], ['Rust', 'rs'], ['Go', 'go']
]) {
 // contract-test: supporting surface=gui.web assertions=code-run.execution.e2b-only,code-run.request.validated,code-run.execution.stream-status-visible
test(`generated ${language} program executes in an isolated E2B sandbox`, async ({ page }: { page: any }) => {
  test.setTimeout(240_000);
  attachConsoleListeners(page);
  attachNetworkListeners(page);
  const { email, password, otpKey } = getTestAccount();
  skipWithoutCredentials(test, email, password, otpKey);
  const log = createSignupLogger(`code-run-${extension}`);
  const screenshot = createStepScreenshotter(log, { filenamePrefix: `code-run-${extension}` });
  await loginToTestAccount(page, log, screenshot, { credentials: { email, password, otpKey } });
  await startNewChat(page, log);
  await sendMessage(page, withMockMarker(
   'Write self-contained programs in Python, JavaScript, TypeScript, shell, C, C++, Rust and Go that print exactly openmates-code-run-ok.',
   'code_run_e2b_languages'
  ), log, screenshot, 'language-programs');
  const target = page.locator('[data-testid="embed-preview"][data-app-id="code"][data-status="finished"]')
   .filter({ hasText: `code_run_smoke.${extension}` }).first();
  await expect(target).toBeVisible({ timeout: 60_000 });
  const overlay = await openFullscreen(page, target);
  await overlay.getByTestId('embed-run-button').click();
  const selection = overlay.getByTestId('code-run-file-selection');
  await expect(selection).toBeVisible({ timeout: 15_000 });
  await expect(selection).toContainText(`code_run_smoke.${extension}`);
  await selection.getByTestId('code-run-continue').click();
  const terminal = overlay.getByTestId('code-run-terminal');
  await expect(terminal).toContainText('openmates-code-run-ok', { timeout: 120_000 });
  await expect(terminal).toContainText(/finished|Exited (?:at .* )?with code 0/i, { timeout: 30_000 });
  await expect(terminal).not.toContainText('execution is not available');
  await screenshot(page, `${extension}-execution-success`);
  await closeFullscreen(page, overlay);
  await deleteActiveChat(page, log, screenshot, 'language-cleanup');
 });
}
