/* eslint-disable @typescript-eslint/no-require-imports -- Repository Playwright helpers use CommonJS. */
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import type { Page, TestInfo } from '@playwright/test';
import { installRealVoicePlayback, qualifiedVoiceTiming, type RealVoicePlayback } from './helpers/real-voice-playback';
import { proofAudioLaunchArgs, withProofAudio } from './helpers/proof-audio';

const { test: auditedTest, expect } = require('./helpers/cookie-audit');
const { loginToTestAccount, sendMessage, waitForAssistantMessage, waitForChatReady } = require('./helpers/chat-test-helpers');
const { getTestAccount } = require('./signup-flow-helpers');
const { requireRealInference } = require('./helpers/real-inference-guard');
const test = withProofAudio(auditedTest);

const ROOT = path.resolve(__dirname, '../../../..');
const FIXTURE_HASH = '450d3653febb63b6e3cc6516afc7d000eb631e1426dc3fd821c16265f25dbe90';
const PROFILE = 'codex-real-web-voice';
const MODEL_ID = 'inception/mercury-3';
const MODEL_NAME = 'Mercury 3';
const FOLLOW_UP = 'And Spain?';
const PAID_CALL_LIMIT_MS = 45_000;

function exactVoiceProofRuntime() {
  const app = new URL(process.env.PLAYWRIGHT_TEST_BASE_URL || 'http://localhost:5173');
  const api = new URL(process.env.PLAYWRIGHT_TEST_API_URL || 'http://localhost:8000');
  const commit = process.env.BUILD_COMMIT_SHA;
  requireRealInference('Signed-in web voice proof', app.origin);
  if (process.env.CI !== 'true' || process.env.OPENMATES_CI_ISOLATED !== '1'
    || process.env.OPENMATES_CI_REAL_WEB_VOICE !== '1'
    || !commit || !/^[a-f0-9]{40}$/.test(commit)
    || [app.hostname, api.hostname].some(host => host !== 'localhost' && host !== '127.0.0.1')
    || app.port !== '5173' || api.port !== '8000' || app.protocol !== 'http:' || api.protocol !== 'http:') {
    throw new Error('The exact isolated web voice proof lane is required');
  }
  const receipt = JSON.parse(readFileSync(path.join(ROOT, 'test-results/ci-environment.json'), 'utf8'));
  if (receipt.environment !== 'github-isolated' || receipt.source_commit !== commit
    || receipt.frontend?.source_commit !== commit || receipt.real_inference_profile !== PROFILE
    || receipt.shared_dev_https !== 'rejected' || receipt.provider_egress !== 'real-inference-allowlist'
    || !receipt.services?.api?.running || !receipt.services?.['ai-worker']?.running
    || !receipt.services?.['speech-worker']?.running
    || JSON.stringify(receipt.real_inference_providers) !== JSON.stringify(['elevenlabs', 'inception_labs', 'mistral_ai', 'typesafe'])) {
    throw new Error('The runner did not attest the exact web voice source and providers');
  }
  return { app: app.origin, api: api.origin, commit };
}

function probeSnapshot(page: Page) {
  return page.evaluate(() => (window as unknown as { __omRealVoicePlayback: RealVoicePlayback }).__omRealVoicePlayback.snapshot());
}

async function verifyEncryptedRows(page: Page, api: string, chatId: string, turns: string[]) {
  return page.evaluate(async ({ api, chatId, turns }) => {
    const query = new URLSearchParams({ direction: 'latest', limit: '20', respect_compression_boundary: 'false' });
    const response = await fetch(api + '/v1/chats/' + encodeURIComponent(chatId) + '/messages/window?' + query,
      { credentials: 'include', cache: 'no-store' });
    if (!response.ok) return false;
    const { messages } = await response.json();
    if (!Array.isArray(messages)) return false;
    const roles = ['user', 'assistant', 'user', 'assistant'];
    const rows = messages.filter(row => row.role === 'user' || row.role === 'assistant');
    return rows.length === turns.length && turns.every((id, index) => {
      const row = rows.find(item => item.message_id === id);
      return row?.role === roles[index] && typeof row.encrypted_content === 'string'
        && row.encrypted_content.length > 24 && typeof row.content !== 'string';
    });
  }, { api, chatId, turns });
}

test.describe.configure({ retries: 0 });
test.use({
  permissions: ['microphone'],
  launchOptions: { args: proofAudioLaunchArgs({ voiceWav: null }), ignoreDefaultArgs: ['--mute-audio'] },
});

// contract-test: supporting surface=gui.web assertions=video-call.chat.transcripts,video-call.audio.spoken-rich-response,video-call.audio.complete-turn-admission
test('a real signed-in web voice turn plays audible speech and keeps its encrypted chat for the typed follow-up',
  async ({ page }: { page: Page }, testInfo: TestInfo) => {
    test.setTimeout(150_000);
    const { app, api, commit } = exactVoiceProofRuntime();
    if (!getTestAccount().email) throw new Error('The isolated browser test account is required');
    const fixture = readFileSync(path.join(ROOT, 'scripts/fixtures/voice-call-capital.flac'));
    if (createHash('sha256').update(fixture).digest('hex') !== FIXTURE_HASH) {
      throw new Error('The approved synthetic microphone fixture changed');
    }
    const version = await page.request.get(app + '/_app/version.json');
    expect(version.ok()).toBe(true);
    expect((await version.json()).version).toBe(commit);

    await installRealVoicePlayback(page, fixture);
    await page.goto(app + '/', { waitUntil: 'domcontentloaded' });
    await loginToTestAccount(page);
    const modelSaved = await page.evaluate(async ({ api, model }) => {
      const response = await fetch(api + '/v1/settings/ai-model-defaults', {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          default_ai_model_simple: model,
          default_ai_model_complex: model,
          default_ai_model_most_demanding: model,
        }),
      });
      return response.ok;
    }, { api, model: MODEL_ID });
    expect(modelSaved).toBe(true);

    const active = page.getByTestId('voice-call-hangup');
    const hangup = async () => {
      if (await active.isVisible()) await active.click({ timeout: 4_000 });
    };
    await page.locator('[data-testid="voice-call-start"]:visible').click();
    const deadline = Date.now() + PAID_CALL_LIMIT_MS;
    let callOpen = true;
    let callDeadlineExpired = false;
    const forceHangup = setTimeout(() => {
      callDeadlineExpired = true;
      void hangup().catch(() => {}).finally(() => {
        if (callOpen && !page.isClosed()) void page.close().catch(() => {});
      });
    }, PAID_CALL_LIMIT_MS);
    const budget = () => {
      const left = deadline - Date.now();
      if (left <= 0 || callDeadlineExpired) throw new Error('The paid web voice call deadline expired');
      return left;
    };
    try {
      const listening = page.getByTestId('voice-call-status-text').filter({ hasText: /Listening/ });
      const privacy = page.getByTestId('notification').filter({ hasText: 'Before your first voice call' });
      await expect(listening.or(privacy).first()).toBeVisible({ timeout: budget() });
      if (await privacy.isVisible()) await privacy.getByRole('button', { name: 'Continue', exact: true }).click();
      await expect(listening).toBeVisible({ timeout: budget() });
      await page.evaluate(() => (window as unknown as {
        __omRealVoicePlayback: RealVoicePlayback;
      }).__omRealVoicePlayback.playQuestion());

      const heard = page.getByTestId('message-user').filter({ hasText: /capital of France/i });
      const reply = page.getByTestId('message-assistant').filter({ hasText: /Paris/i });
      await expect(heard).toHaveCount(1, { timeout: budget() });
      await expect(reply).toHaveCount(1, { timeout: budget() });
      await expect(reply.getByTestId('generated-by')).toContainText(MODEL_NAME, { timeout: budget() });
      const voiceId = await heard.getAttribute('data-message-id');
      const replyId = await reply.getAttribute('data-message-id');
      const chatId = new URL(page.url()).hash.match(/(?:^#|&)chat-id=([a-zA-Z0-9_-]+)/)?.[1];
      if (!voiceId || !replyId || !chatId) throw new Error('The spoken answer did not establish canonical chat identity');
      const first = await probeSnapshot(page);
      expect(first.stt).toHaveLength(1);
      expect(first.stt[0]).toMatchObject({ provider: 'mistral', model: 'voxtral-mini-transcribe-realtime-3-0' });
      const callId = first.stt[0].callId;
      expect(first.turns).toEqual([{ callId, messageId: voiceId }]);

      let timings: ReturnType<typeof qualifiedVoiceTiming> = null;
      await expect.poll(async () => {
        timings = qualifiedVoiceTiming(await probeSnapshot(page), { callId, chatId, messageId: replyId });
        return timings !== null;
      }, { timeout: budget(), message: 'Only non-silent playback of the owned prose stream qualifies' }).toBe(true);
      const timing = timings as ReturnType<typeof qualifiedVoiceTiming>;
      if (!timing) throw new Error('Owned non-silent speech was not measured');
      if (timing.cueMs !== null) expect(timing.cueMs).toBeLessThanOrEqual(timing.substantiveMs);
      budget();
      await hangup();
      callOpen = false;
      clearTimeout(forceHangup);
      await expect(active).toHaveCount(0);

      await sendMessage(page, FOLLOW_UP);
      const typed = page.getByTestId('message-user').filter({ hasText: /^And Spain\?$/ });
      const typedReply = await waitForAssistantMessage(page, { contains: /Madrid/i, timeout: 35_000 });
      await expect(typed).toHaveCount(1);
      await expect(typedReply.getByTestId('generated-by')).toContainText(MODEL_NAME);
      expect(new URL(page.url()).hash).toContain('chat-id=' + chatId);
      const typedId = await typed.getAttribute('data-message-id');
      const typedReplyId = await typedReply.getAttribute('data-message-id');
      if (!typedId || !typedReplyId) throw new Error('The typed follow-up did not establish canonical message identity');
      const identities = [voiceId, replyId, typedId, typedReplyId];
      expect(new Set(identities).size).toBe(4);
      await expect.poll(() => verifyEncryptedRows(page, api, chatId, identities), { timeout: 20_000 }).toBe(true);
      await page.reload();
      await waitForChatReady(page);
      for (const id of identities) await expect(page.locator('[data-message-id="' + id + '"]')).toHaveCount(1);
      await expect(heard).toContainText(/capital of France/i);
      await expect(reply).toContainText(/Paris/i);
      await expect(typed).toContainText(FOLLOW_UP);
      await expect(page.locator('[data-message-id="' + typedReplyId + '"]')).toContainText(/Madrid/i);

      const artifact = testInfo.outputPath('real-web-voice-timing.json');
      writeFileSync(artifact, JSON.stringify({ sourceCommit: commit, lastVoicedToCueMs: timing.cueMs,
        lastVoicedToSubstantiveMs: timing.substantiveMs, sampleRate: timing.sampleRate, sameEncryptedChat: true }));
      await testInfo.attach('real-web-voice-timing', { path: artifact, contentType: 'application/json' });
    } finally {
      clearTimeout(forceHangup);
      if (callOpen) await hangup().catch(() => {});
    }
  });
