/* eslint-disable @typescript-eslint/no-require-imports -- Existing E2E helpers expose CommonJS exports. */
/** Real Team attachment and access checks through paired CLI clients. No AI invocation. */
export {};
import { spawn, execFileSync } from 'node:child_process';
import { createHash, randomUUID } from 'node:crypto';
import { existsSync, rmSync, writeFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import type { Browser, Page, TestInfo } from '@playwright/test';

const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getTestAccount } = require('./signup-flow-helpers');
const { CLI_DIST, runCli } = require('./helpers/cli-test-helpers');
const { installRecorderDeps } = require('./cli-tui-proof-helpers');
const {
  createWorkflowCliHome, loginWorkflowCliViaPair, parseCliJson, removeWorkflowCliHome,
  workflowApiUrl, workflowCliEnv,
} = require('./helpers/workflow-cli-e2e-helpers');

type CliResult = { code: number | null; stdout: string; stderr: string; recording?: Record<string, string> };
const apiUrl = workflowApiUrl();
const allowedRoles = new Set(['user', 'assistant', 'system', 'tool']);

function objectKeys(value: unknown): string[] {
  return value && typeof value === 'object' && !Array.isArray(value) ? Object.keys(value).sort() : [];
}

function messageShape(value: unknown): { count: number; roles: string[]; linkedEmbedCount: number } {
  const messages = Array.isArray(value) ? value : [];
  return {
    count: messages.length,
    roles: [...new Set(messages.map((message) => allowedRoles.has(message?.role) ? message.role as string : 'other'))].sort(),
    linkedEmbedCount: messages.reduce((count, message) => count + (Array.isArray(message?.embedIds) ? message.embedIds.length : 0), 0),
  };
}

async function cliJson(home: string, args: string[], label: string): Promise<any> {
  const result: CliResult = await runCli(apiUrl, [...args, '--json'], 90_000, {
    useApiKey: false, record: false, env: workflowCliEnv(apiUrl, home),
  });
  return parseCliJson(result, label);
}

/** Pair the already authenticated second browser account into its own empty CLI home. */
async function pairCurrentBrowser(page: Page, home: string): Promise<void> {
  const child = spawn('node', [CLI_DIST, 'login'], {
    env: workflowCliEnv(apiUrl, home), stdio: ['pipe', 'pipe', 'pipe'],
  });
  let stdout = '', stderr = '';
  child.stdout.on('data', (chunk: Buffer) => { stdout += String(chunk); });
  child.stderr.on('data', (chunk: Buffer) => { stderr += String(chunk); });
  const exited = new Promise<number | null>((resolve, reject) => {
    const timeout = setTimeout(() => { child.kill('SIGTERM'); reject(new Error('CLI pairing timed out')); }, 50_000);
    child.once('close', (exitCode) => { clearTimeout(timeout); resolve(exitCode); });
  });
  try {
    let token = '';
    await expect.poll(() => {
      token = stdout.match(/pair=([A-Z0-9]{6})/)?.[1] ?? '';
      return token.length;
    }, { timeout: 20_000 }).toBe(6);
    await page.goto(new URL(`/#pair=${token}`, page.url()).toString());
    await page.getByTestId('pair-allow-button').click();
    const pin = (await page.getByTestId('pair-pin-display').innerText()).replace(/\s/g, '');
    expect(/^[A-Z0-9]{6}$/.test(pin), 'Second account pairing PIN must have the expected format').toBe(true);
    await expect.poll(() => (stdout + stderr).includes('Enter 6-char pairing PIN:'), { timeout: 20_000 }).toBe(true);
    child.stdin.write(`${pin}\n`);
    const code = await exited;
    expect(code, 'Second account CLI pairing failed').toBe(0);
    expect((stdout + stderr).includes('Login successful'), 'Second account CLI pairing must complete').toBe(true);
  } finally {
    if (child.exitCode === null) child.kill('SIGTERM');
    await exited.catch(() => undefined);
  }
}

function clearTeamCache(home: string, teamId: string): void {
  const digest = createHash('sha256').update(teamId).digest('hex').slice(0, 32);
  rmSync(join(home, '.openmates', `sync_cache.team.${digest}.json`), { force: true });
}

/** Invoke the shipped SDK client so the recipient performs real Team-key/embed decryption. */
function readMemberEmbed(home: string, teamId: string, chatId: string, embedId: string): Record<string, unknown> {
  const modulePath = join(dirname(CLI_DIST), 'index.js');
  const script = [
    "const {pathToFileURL}=require('node:url');",
    "(async()=>{const {OpenMatesClient}=await import(pathToFileURL(process.argv[1]).href);",
    "const client=OpenMatesClient.load({apiUrl:process.env.OPENMATES_API_URL});",
    "const result=await client.getEmbed(process.argv[4],{teamId:process.argv[2],chatId:process.argv[3]});",
    "process.stdout.write(JSON.stringify({embedId:result.embedId,type:result.type,content:result.content}));",
    "})().catch(e=>{process.stderr.write(String(e));process.exit(1)})",
  ].join('');
  let output: string;
  try {
    output = execFileSync('node', ['-e', script, modulePath, teamId, chatId, embedId], {
      env: workflowCliEnv(apiUrl, home), timeout: 90_000, encoding: 'utf8',
    });
  } catch (error) {
    const child = error as { status?: unknown; stderr?: unknown };
    const stderr = String(child.stderr ?? '');
    const kind = /OperationError/.test(stderr) ? 'OperationError'
      : /TypeError/.test(stderr) ? 'TypeError'
        : /(?:HTTP|status(?:Code)?)\s*[:=]?\s*\d{3}/i.test(stderr) ? 'HTTP'
          : /Error/.test(stderr) ? 'Error' : 'other';
    const httpStatus = stderr.match(/(?:HTTP|status(?:Code)?)\s*[:=]?\s*(\d{3})/i)?.[1] ?? 'none';
    const exitStatus = typeof child.status === 'number' ? child.status : 'none';
    throw new Error(`Member SDK embed read failed: exit=${exitStatus}, stderrClass=${kind}, httpStatus=${httpStatus}`);
  }
  try { return JSON.parse(output) as Record<string, unknown>; }
  catch { throw new Error('Member SDK embed read returned invalid JSON'); }
}

async function expectOnlineDenied(page: Page, teamId: string, chatId: string, embedId: string): Promise<void> {
  const paths = [
    { name: 'Team chat messages', path: `/v1/chats/${encodeURIComponent(chatId)}/messages/window?team_id=${encodeURIComponent(teamId)}&limit=30` },
    { name: 'Team encrypted embed', path: `/v1/embeds/chats/${encodeURIComponent(chatId)}/embeds/${encodeURIComponent(embedId)}?team_id=${encodeURIComponent(teamId)}` },
    { name: 'Team usage', path: `/v1/teams/${encodeURIComponent(teamId)}/billing/usage` },
  ];
  for (const { name, path } of paths) {
    const response = await page.request.get(`${apiUrl}${path}`, { headers: { 'Cache-Control': 'no-cache' } });
    expect([403, 404], `Unauthorized online read of ${name} must be denied`).toContain(response.status());
  }
}

// contract-test: direct surface=cli assertions=teams.chat.encrypted-until-invoked,teams.membership.role-gated,teams.context.full-switch-local,teams.chat-billing.team-credit-boundary
test('a second Team member decrypts a CLI attachment while outsiders and removed members lose online access', async (
  { page, browser }: { page: Page; browser: Browser }, testInfo: TestInfo,
) => {
  test.setTimeout(420_000);
  const owner = getTestAccount(1), member = getTestAccount(2);
  await skipIfFeaturesDisabled(test, page, ['platform:teams']);
  expect(owner.email && owner.password && owner.otpKey, 'Owner CI account must be provisioned').toBeTruthy();
  expect(member.email && member.password && member.otpKey, 'Second CI account must be provisioned').toBeTruthy();
  expect(member.email !== owner.email, 'Owner and second CI accounts must be distinct').toBe(true);

  const ownerHome = createWorkflowCliHome('team-artifact-owner');
  const memberHome = createWorkflowCliHome('team-artifact-member');
  const artifactMarker = `harbor-${randomUUID().slice(0, 8)}`;
  const artifactPath = join(ownerHome, 'shared-note.md');
  writeFileSync(artifactPath, `# Team note\n\n${artifactMarker}\n`, { mode: 0o600 });
  const ownerVideo = page.video();
  let teamId = '', chatId = '', embedId = '', memberId = '';
  let memberContext: Awaited<ReturnType<Browser['newContext']>> | undefined;
  let memberPage: Page | undefined;
  let runError: unknown;
  let phase = 'owner setup', failedPhase = '';
  const cleanupErrors: Error[] = [];
  const structure: Record<string, unknown> = {};
  try {
    await loginWorkflowCliViaPair(page, apiUrl, ownerHome, 'TEAM_ARTIFACT_OWNER');
    const created = await cliJson(ownerHome, ['teams', 'create', '--name', `Artifact parity ${randomUUID().slice(0, 8)}`], 'create disposable Team');
    teamId = String(created.team?.team_id ?? '');
    expect(teamId, 'Disposable Team creation must return an ID').toBeTruthy();
    expect((await cliJson(ownerHome, ['teams', 'switch', teamId], 'select owner Team')).active_team_id === teamId,
      'Owner CLI must switch to the disposable Team').toBe(true);

    const viewport = page.viewportSize() ?? { width: 1280, height: 720 };
    memberContext = await browser.newContext({ viewport, recordVideo: { dir: testInfo.outputPath('member-video'), size: viewport } });
    memberPage = await memberContext.newPage();
    await loginToTestAccount(memberPage, undefined, undefined, { credentials: member });
    phase = 'outsider authentication and Team exclusion';
    const outsiderTeams = await memberPage.request.get(`${apiUrl}/v1/teams`);
    expect(outsiderTeams.ok(), 'Outsider Team list request must succeed').toBe(true);
    expect((await outsiderTeams.json() as {teams: Array<{team_id: string}>}).teams
      .some((team) => team.team_id === teamId), 'Outsider Team list must exclude the disposable Team').toBe(false);
    const usageBefore = await cliJson(ownerHome, ['teams', 'usage', teamId], 'initial Team usage');
    expect(usageBefore.usage, 'New Team must start with no usage rows').toEqual([]);
    const personalBefore = await page.request.get(`${apiUrl}/v1/settings/delete-account-preview`);
    expect(personalBefore.ok(), 'Owner Personal credit baseline must be readable').toBe(true);
    const personalCreditsBefore = (await personalBefore.json() as {total_credits: number}).total_credits;
    const memberPersonalBefore = await memberPage.request.get(`${apiUrl}/v1/settings/delete-account-preview`);
    expect(memberPersonalBefore.ok(), 'Second account Personal credit baseline must be readable').toBe(true);
    const memberPersonalCreditsBefore = (await memberPersonalBefore.json() as {total_credits: number}).total_credits;

    phase = 'owner ordinary attachment send';
    const sent = await cliJson(ownerHome,
      ['chats', 'new', `Review the attached Team note @${artifactPath}`, '--team', teamId,
        '--no-pii-detection', '--response-timeout-seconds', '5'],
      'send ordinary Team attachment');
    chatId = String(sent.chatId ?? '');
    expect(chatId, 'Ordinary Team attachment send must create a chat').toBeTruthy();
    expect(sent.assistant, 'Ordinary Team attachment send must not invoke an AI response').toBe('');
    phase = 'owner attachment lookup';
    const ownerChat = await cliJson(ownerHome, ['chats', 'show', chatId, '--team', teamId, '--all'], 'show owner Team chat');
    structure.ownerChatKeys = objectKeys(ownerChat);
    structure.ownerChatMatch = ownerChat.chat?.id === chatId;
    structure.ownerMessages = messageShape(ownerChat.messages);
    embedId = String(ownerChat.messages?.find((message: any) => message.role === 'user')?.embedIds?.[0] ?? '');
    expect(embedId, 'Owner chat must link the encrypted attachment').toBeTruthy();
    await expectOnlineDenied(memberPage, teamId, chatId, embedId);

    phase = 'member invite and CLI pairing';
    const invite = (await cliJson(ownerHome, ['teams', 'invite', teamId, '--email', member.email!, '--role', 'member'], 'invite member')).invite;
    expect(/#key=[A-Za-z0-9_-]{43}$/.test(String(invite?.invite_url ?? '')),
      'Member invite must carry encrypted key material').toBe(true);
    await pairCurrentBrowser(memberPage, memberHome);
    const accepted = await cliJson(memberHome, ['teams', 'accept-invite', String(invite.invite_url), '--email', member.email!], 'accept member invite');
    expect(accepted.status, 'Second account must accept Team membership').toBe('accepted');
    memberId = String(accepted.membership?.user_id ?? '');
    expect(memberId, 'Accepted Team membership must identify the member').toBeTruthy();
    expect((await cliJson(memberHome, ['teams', 'switch', teamId], 'select member Team')).active_team_id === teamId,
      'Member CLI must switch to the disposable Team').toBe(true);
    const ownerIdentity = await cliJson(ownerHome, ['whoami'], 'owner identity');
    const memberIdentity = await cliJson(memberHome, ['whoami'], 'member identity');
    expect(String(memberIdentity.id ?? memberIdentity.user_id) === memberId,
      'Member CLI identity must match accepted membership').toBe(true);
    expect(String(ownerIdentity.id ?? ownerIdentity.user_id) !== memberId,
      'Owner and member CLI identities must differ').toBe(true);
    phase = 'member chat hydration';
    clearTeamCache(memberHome, teamId);
    const memberChat = await cliJson(memberHome, ['chats', 'show', chatId, '--team', teamId, '--all'], 'hydrate member Team chat');
    structure.memberChatKeys = objectKeys(memberChat);
    structure.memberChatMatch = memberChat.chat?.id === chatId;
    structure.memberMessages = messageShape(memberChat.messages);
    phase = 'member attachment linkage';
    expect(memberChat.messages?.some((message: any) => message.embedIds?.includes(embedId)),
      'Second Team member must receive the attached embed reference').toBe(true);
    phase = 'member embed decryption';
    const hydrated = readMemberEmbed(memberHome, teamId, chatId, embedId);
    structure.decryptedEmbedKeys = objectKeys(hydrated);
    structure.decryptedType = hydrated.type === 'code-code' ? 'code-code' : 'other';
    structure.contentKeyNames = objectKeys(hydrated.content);
    structure.codeType = typeof (hydrated.content as { code?: unknown } | null)?.code;
    structure.fixtureMarkerPresent = typeof (hydrated.content as { code?: unknown } | null)?.code === 'string'
      && ((hydrated.content as { code: string }).code.includes(artifactMarker));
    phase = 'member embed plaintext assertions';
    expect(hydrated.embedId === embedId, 'Member SDK must return the requested Team embed ID').toBe(true);
    expect(hydrated.type, 'Member SDK must decrypt the attachment type').toBe('code-code');
    expect((hydrated.content as { filename?: string })?.filename,
      'Member SDK must decrypt the attachment filename').toBe('shared-note.md');
    expect(structure.fixtureMarkerPresent, 'Member SDK must decrypt the original attachment text').toBe(true);

    phase = 'member terminal embed opening';
    installRecorderDeps();
    const recorded = await runCli(apiUrl, ['embeds', 'show', embedId], 90_000, {
      useApiKey: false, env: { ...workflowCliEnv(apiUrl, memberHome), OPENMATES_CLI_RECORD_E2E: '1', OPENMATES_E2E_SPEC: 'cli-team-artifacts-parity' },
    }) as CliResult;
    expect(recorded.code, 'Real member attachment opening failed').toBe(0);
    expect(recorded.stdout.includes('shared-note.md'), 'Recorded member terminal must render the attachment filename').toBe(true);
    expect(recorded.stdout.includes(artifactMarker), 'Recorded member terminal must render decrypted attachment text').toBe(true);
    if (!recorded.recording?.videoPath || !existsSync(recorded.recording.videoPath)) throw new Error('Member terminal recording was not captured');
    for (const [name, key, contentType] of [
      ['member-terminal-video', 'videoPath', 'video/mp4'],
      ['member-terminal-manifest', 'manifestPath', 'application/json'],
      ['member-terminal-transcript', 'transcriptPath', 'text/plain'],
    ] as const) {
      const path = recorded.recording[key];
      if (path && existsSync(path)) await testInfo.attach(name, { path, contentType });
    }

    phase = 'Team and Personal usage isolation';
    const usageAfter = await cliJson(ownerHome, ['teams', 'usage', teamId], 'Team usage after ordinary attachment');
    expect(usageAfter.usage, 'Ordinary Team message must not create AI usage rows').toEqual(usageBefore.usage);
    const personalAfter = await page.request.get(`${apiUrl}/v1/settings/delete-account-preview`);
    expect(personalAfter.ok(), 'Owner Personal credits must remain readable after Team send').toBe(true);
    expect((await personalAfter.json() as {total_credits: number}).total_credits,
      'Owner Personal credits must not be charged for ordinary Team send').toBe(personalCreditsBefore);
    const memberPersonalAfter = await memberPage.request.get(`${apiUrl}/v1/settings/delete-account-preview`);
    expect(memberPersonalAfter.ok(), 'Member Personal credits must remain readable after Team send').toBe(true);
    expect((await memberPersonalAfter.json() as {total_credits: number}).total_credits,
      'Member Personal credits must not be charged for ordinary Team send').toBe(memberPersonalCreditsBefore);
    const personalChat = await memberPage.request.get(`${apiUrl}/v1/chats/${encodeURIComponent(chatId)}/messages/window?limit=30`);
    expect(personalChat.status(), 'Team chat must not appear in Personal chat scope').toBe(404);

    phase = 'removed member online denial';
    const removed = await cliJson(ownerHome, ['teams', 'remove-member', teamId, '--user', memberId], 'remove member');
    expect(removed.success, 'Owner must remove second Team member').toBe(true);
    clearTeamCache(memberHome, teamId);
    await expectOnlineDenied(memberPage, teamId, chatId, embedId);
    const staleMemberRead = await runCli(apiUrl, ['chats', 'show', chatId, '--team', teamId, '--all', '--json'], 90_000, {
      useApiKey: false, record: false, env: workflowCliEnv(apiUrl, memberHome),
    }) as CliResult;
    expect(staleMemberRead.code, 'Removed member must not reopen Team chat after cache clear').not.toBe(0);
  } catch (error) {
    runError = error;
    failedPhase = phase;
  } finally {
    if (teamId) {
      try {
        const response = await page.request.delete(`${apiUrl}/v1/teams/${encodeURIComponent(teamId)}`);
        if (!response.ok()) cleanupErrors.push(new Error(`Team cleanup failed with HTTP ${response.status()}`));
        else {
          const absent = await page.request.get(`${apiUrl}/v1/teams/${encodeURIComponent(teamId)}`, {
            headers: { 'Cache-Control': 'no-cache' },
          });
          if (absent.status() !== 404) cleanupErrors.push(new Error(`Deleted Team remains readable (HTTP ${absent.status()})`));
        }
      } catch (error) { cleanupErrors.push(error as Error); }
    }
    if (memberContext) {
      const video = memberPage?.video();
      try { await memberContext.close(); } catch (error) { cleanupErrors.push(error as Error); }
      if (video) {
        try { await testInfo.attach('member-browser-video', { path: await video.path(), contentType: 'video/webm' }); }
        catch (error) { cleanupErrors.push(error as Error); }
      }
    }
    try { await page.close(); } catch (error) { cleanupErrors.push(error as Error); }
    if (ownerVideo) {
      try { await testInfo.attach('owner-browser-video', { path: await ownerVideo.path(), contentType: 'video/webm' }); }
      catch (error) { cleanupErrors.push(error as Error); }
    }
    try {
      await testInfo.attach('team-artifact-structure', {
        body: Buffer.from(JSON.stringify({ phase: failedPhase || phase, ...structure, cleanupErrorCount: cleanupErrors.length })),
        contentType: 'application/json',
      });
    } catch (error) { cleanupErrors.push(error as Error); }
    removeWorkflowCliHome(ownerHome);
    removeWorkflowCliHome(memberHome);
  }
  if (runError || cleanupErrors.length) throw new AggregateError(
    [...(runError ? [runError] : []), ...cleanupErrors],
    `CLI Team artifact failed during ${failedPhase || 'cleanup'} (${runError instanceof Error ? runError.name : 'no primary error'}; ${cleanupErrors.length} cleanup errors)`,
  );
});
