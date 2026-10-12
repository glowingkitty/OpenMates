#!/usr/bin/env node
/** Real-AI, ordinary personal-chat web latency probe. Dry unless explicitly leased. */
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawnSync } = require('node:child_process');

const CASES = [
  { id: 'capital', prompt: 'What’s the capital of Spain?' },
  { id: 'events', prompt: 'Find AI events in Berlin' },
];
const APP_ORIGIN = 'https://app.dev.openmates.org';
const API_ORIGIN = 'https://api.dev.openmates.org';
const MAX_TURN_MS = 120000;
const argv = process.argv.slice(2);
const option = (name) => { const i = argv.indexOf(name); return i < 0 ? null : argv[i + 1]; };
const execute = argv.includes('--execute');
const plan = CASES.flatMap(({ id }) => ['cold', 'warm-1', 'warm-2'].map(sample => ({ id, sample })));
if (!execute) {
  process.stdout.write(JSON.stringify({ mode: 'dry', app_origin: APP_ORIGIN, api_origin: API_ORIGIN,
    samples: plan, requires: ['--execute', '--lease-id', '--api-origin', '--output'] }) + '\n');
  process.exit(0);
}
if (option('--api-origin') !== API_ORIGIN || !option('--lease-id') ||
    !/^[A-Za-z0-9._:-]{8,100}$/.test(option('--lease-id')) ||
    !option('--output') || option('--app-origin') && option('--app-origin') !== APP_ORIGIN) {
  throw new Error('Execution requires --lease-id, --api-origin https://api.dev.openmates.org, --output, and fixed dev app origin');
}
const output = path.resolve(option('--output'));
if (fs.existsSync(output) && fs.readdirSync(output).length) throw new Error('Output directory must be new or empty');
fs.mkdirSync(output, { recursive: true, mode: 0o700 });
fs.chmodSync(output, 0o700);

function readAccount() {
  const slot = option('--account-slot') || '4';
  if (!/^\d{1,2}$/.test(slot)) throw new Error('Invalid numbered dev test account slot');
  const env = Object.fromEntries(fs.readFileSync(path.resolve(__dirname, '../.env'), 'utf8')
    .split(/\r?\n/).filter(x => x.includes('=') && !/^\s*#/.test(x)).map(x => {
      const i = x.indexOf('='); let v = x.slice(i + 1).trim();
      if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) v = v.slice(1, -1);
      return [x.slice(0, i).trim(), v];
    }));
  const prefix = `OPENMATES_TEST_ACCOUNT_${slot}_`;
  const account = { email: env[prefix + 'EMAIL'], password: env[prefix + 'PASSWORD'], otpKey: env[prefix + 'OTP_KEY'] };
  if (!account.email || !account.password) throw new Error('Numbered dev test account credentials missing');
  return account;
}
function totp(secret) {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
  let bits = '', bytes = [];
  for (const c of secret.toUpperCase().replace(/[^A-Z2-7]/g, '')) {
    bits += alphabet.indexOf(c).toString(2).padStart(5, '0');
    while (bits.length >= 8) { bytes.push(parseInt(bits.slice(0, 8), 2)); bits = bits.slice(8); }
  }
  const counter = Buffer.alloc(8); counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30000)));
  const digest = crypto.createHmac('sha1', Buffer.from(bytes)).update(counter).digest();
  const offset = digest[19] & 15;
  return String((digest.readUInt32BE(offset) & 0x7fffffff) % 1000000).padStart(6, '0');
}
function wireObserver(wire) {
  return socket => socket.on('framereceived', frame => {
    try {
      const data = JSON.parse(String(frame.payload));
      const payload = data.payload || {};
      if (!/^[a-z_]{1,60}$/.test(data.type)) return;
      if (!['new_chat_message', 'ai_typing_started', 'ai_message_update', 'ai_message_ready',
        'ai_thinking_update', 'ai_thinking_started', 'ai_thinking_completed', 'ai_skill_execution_started',
        'ai_skill_execution_completed', 'ai_tool_call', 'ai_tool_result', 'ai_processing_status'].includes(data.type)) return;
      wire.push({ at: Date.now(), type: data.type, chat_id: payload.chat_id, message_id: payload.message_id,
        task_id: payload.task_id, user_message_id: payload.user_message_id,
        sequence: payload.sequence, final: payload.is_final_chunk === true,
        continuation: payload.awaiting_async_skill_continuation === true,
        model: payload.model_name || payload.model || null, category: payload.category || null });
      if (wire.length > 3000) wire.shift();
    } catch { /* Ignore encrypted/non-JSON frames. */ }
  });
}
async function login(page, account) {
  await page.goto(APP_ORIGIN + '/', { waitUntil: 'domcontentloaded' });
  await page.getByTestId('header-login-signup-btn').click();
  await page.getByTestId('tab-login').click();
  await page.getByTestId('login-email-input').fill(account.email);
  await page.getByTestId('login-continue-button').click();
  await page.getByTestId('login-password-input').fill(account.password);
  await page.getByTestId('login-submit-button').click();
  const otp = page.getByTestId('login-otp-input');
  const auth = page.locator('[data-authenticated="true"]');
  await Promise.race([otp.waitFor({ state: 'visible', timeout: 30000 }), auth.waitFor({ state: 'visible', timeout: 30000 })]);
  if (await otp.isVisible()) {
    if (!account.otpKey) throw new Error('Numbered dev test account OTP key missing');
    await otp.fill(totp(account.otpKey));
    if (await page.getByTestId('login-submit-button').isVisible()) await page.getByTestId('login-submit-button').click();
  }
  await auth.waitFor({ state: 'visible', timeout: 30000 });
  await page.getByTestId('message-editor').waitFor({ state: 'visible', timeout: 30000 });
}
async function installPaintProbe(page) {
  await page.evaluate(() => {
    if (window.__ordinaryLatencyProbe?.stop) window.__ordinaryLatencyProbe.stop();
    const probe = { clickAt: null, mateAt: null, answerAt: null, answerMessageId: null, mateClasses: null,
      initialAssistantIds: new Set([...document.querySelectorAll('[data-testid="message-assistant"]')]
        .map(e => e.closest('[data-message-id]')?.getAttribute('data-message-id')).filter(Boolean)),
      stopped: false, stop() { this.stopped = true; document.removeEventListener('click', onClick, true); } };
    window.__ordinaryLatencyProbe = probe;
    function visible(element) {
      if (!element?.isConnected || !element.getBoundingClientRect().width || !element.getBoundingClientRect().height) return false;
      for (let e = element; e instanceof Element; e = e.parentElement) {
        const s = getComputedStyle(e);
        if (s.display === 'none' || s.visibility !== 'visible' || Number(s.opacity) < 0.95) return false;
      }
      return true;
    }
    function hasVisibleAuthoredText(root) {
      if (!visible(root)) return false;
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      for (let node = walker.nextNode(); node; node = walker.nextNode()) {
        if (!node.textContent?.trim()) continue;
        const parent = node.parentElement;
        if (parent?.closest('[data-testid="assistant-activity-group"], [data-testid="assistant-response-thinking"], [data-testid="thinking-section"]')) continue;
        // Streaming text can exist in the ProseMirror DOM while every newly
        // inserted .stream-fade-chunk still has opacity zero. Inspect the text
        // node's own styled ancestors, not merely the message body.
        if (!visible(parent)) continue;
        const range = document.createRange();
        range.selectNodeContents(node);
        if ([...range.getClientRects()].some(rect => rect.width > 0 && rect.height > 0)) return true;
      }
      return false;
    }
    function onClick(event) {
      if (event.target.closest('[data-testid="composer-send-button"]')) probe.clickAt = Date.now();
    }
    document.addEventListener('click', onClick, true);
    function frame() {
      if (probe.stopped) return;
      if (probe.clickAt) {
        // The pending assistant response is the stage-1 Mate header. Its name
        // is painted before a portrait image need finish loading.
        const pending = document.querySelector('[data-testid="pending-assistant-response"]');
        const identity = pending?.querySelector('[data-testid="assistant-identity-row"].transient');
        const name = identity?.querySelector('[data-testid="chat-mate-name"]');
        const profile = pending?.querySelector('[data-testid="mate-profile"]');
        const classes = profile ? [...profile.classList] : [];
        if (!probe.mateAt && name?.textContent?.trim() && name.textContent.trim() !== 'Assistant' &&
            identity?.querySelector('[data-testid="assistant-transient-thinking"]') &&
            classes.length && visible(identity) && visible(name)) {
          probe.mateAt = Date.now(); probe.mateClasses = classes;
        }
        if (!probe.answerAt) for (const assistant of document.querySelectorAll('[data-testid="message-assistant"]')) {
          const wrapper = assistant.closest('[data-message-id]');
          const id = wrapper?.getAttribute('data-message-id');
          if (!id || probe.initialAssistantIds.has(id)) continue;
          const bodies = assistant.querySelectorAll('.chat-message-body [data-testid="message-content"] .ProseMirror, .chat-message-body [data-testid="message-content"]');
          if ([...bodies].some(body => !body.closest('[data-testid="assistant-activity-group"], [data-testid="assistant-response-thinking"], [data-testid="thinking-section"]') &&
              hasVisibleAuthoredText(body))) { probe.answerAt = Date.now(); probe.answerMessageId = id; break; }
        }
      }
      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  });
}
async function newPersonalChat(page) {
  // The main chat's New Chat button leaves project context and opens a personal draft.
  const button = page.getByTestId('new-chat-button').filter({ visible: true }).first();
  if (await button.count()) await button.click();
  await page.getByTestId('message-editor').waitFor({ state: 'visible', timeout: 30000 });
  if (await page.getByTestId('project-workspace-header').isVisible().catch(() => false))
    throw new Error('Project workspace active; refusing ordinary-chat sample');
}
function matchingEvents(wire, start, chatId, userMessageId) {
  return wire.filter(e => e.at >= start && e.chat_id === chatId &&
    (!userMessageId || !e.user_message_id || e.user_message_id === userMessageId));
}
async function sample(page, wire, item) {
  await newPersonalChat(page);
  const editor = page.getByTestId('message-editor').locator('.ProseMirror');
  await editor.click();
  await page.keyboard.insertText(CASES.find(x => x.id === item.id).prompt);
  const send = page.getByTestId('composer-send-button').filter({ visible: true }).first();
  await send.waitFor({ state: 'visible', timeout: 10000 });
  await page.waitForFunction(() => {
    const button = [...document.querySelectorAll('[data-testid="composer-send-button"]')]
      .find(e => e.getClientRects().length && !e.disabled);
    const wrapper = button?.closest('[data-action="message-input"]');
    const selector = [...(wrapper?.querySelectorAll('[data-testid="composer-model-selector"]') || [])]
      .find(e => e.getClientRects().length);
    return !!button && !!wrapper && !wrapper.closest('[inert]') &&
      !!selector && !selector.disabled && selector.getAttribute('data-loading') === 'false';
  }, null, { timeout: 30000 });
  await installPaintProbe(page);
  const begun = Date.now();
  await send.click();
  const deadline = begun + MAX_TURN_MS;
  let chatId = null, taskId = null, userMessageId = null, final = null, paint = null;
  while (Date.now() < deadline) {
    const ui = await page.evaluate(() => {
      const p = window.__ordinaryLatencyProbe;
      return { clickAt: p?.clickAt, mateAt: p?.mateAt, answerAt: p?.answerAt,
        answerMessageId: p?.answerMessageId, mateClasses: p?.mateClasses,
        chatId: document.querySelector('[data-action="message-input"]')?.getAttribute('data-current-chat-id') || null };
    });
    paint = ui;
    chatId = chatId || (ui.chatId && ui.chatId !== 'new-chat' ? ui.chatId : null);
    const current = chatId ? matchingEvents(wire, begun, chatId, null) : [];
    taskId = taskId || current.find(e => e.type === 'ai_typing_started')?.task_id ||
      current.find(e => e.type === 'ai_message_update')?.task_id || null;
    userMessageId = userMessageId || current.find(e => e.type === 'ai_typing_started')?.user_message_id ||
      current.find(e => e.type === 'ai_message_update')?.user_message_id || null;
    const own = matchingEvents(wire, begun, chatId, userMessageId);
    final = own.findLast(e => e.type === 'ai_message_update' && e.final && !e.continuation) || null;
    if (final && ui.mateAt && ui.answerAt) break;
    await page.waitForTimeout(50);
  }
  await page.evaluate(() => window.__ordinaryLatencyProbe?.stop());
  if (!paint?.clickAt || !chatId || !taskId || !userMessageId || !final || !paint.mateAt || !paint.answerAt)
    throw new Error('Incomplete current-turn source correlation, final chunk, or visible paint');
  if (paint.answerMessageId !== final.message_id)
    throw new Error('Visible authored message does not match current-turn source final');
  const own = matchingEvents(wire, begun, chatId, userMessageId);
  const typing = own.find(e => e.type === 'ai_typing_started' && e.user_message_id === userMessageId);
  if (!typing || !typing.category || !typing.model || !paint.mateClasses?.includes(typing.category) ||
      !/gemini[-_\s]*3[.]8[-_\s]*flash/i.test(typing.model)) {
    throw new Error('Visible Mate did not match current-turn AI typing category/model metadata');
  }
  const answer = page.getByTestId('message-assistant').last();
  const modelText = await answer.getByTestId('using-model').or(answer.getByTestId('generated-by')).first()
    .textContent({ timeout: 10000 }).catch(() => null);
  const modelObserved = (modelText || own.map(e => e.model).find(Boolean) || '').trim();
  if (!/gemini\s*3[.]8\s*flash/i.test(modelObserved)) throw new Error('Default Gemini 3.8 Flash model not verified');
  return { prompt_id: item.id, sample: item.sample, status: 'complete', model: 'Gemini 3.8 Flash',
    thinking_level: 'server_log_verification_required_LOW', selected_category: typing.category,
    send_to_selected_mate_ms: paint.mateAt - paint.clickAt,
    send_to_stage1_source_ms: typing.at - paint.clickAt,
    send_to_authored_paint_ms: paint.answerAt - paint.clickAt,
    send_to_source_final_ms: final.at - paint.clickAt,
    tool_event_count: own.filter(e => /skill|tool/.test(e.type)).length,
    source_event_count: own.length,
    source_final_sequence: Number.isInteger(final.sequence) ? final.sequence : null,
    _private: { chat_id: chatId, task_id: taskId, user_message_id: userMessageId, final_task_id: final.task_id,
      final_message_id: final.message_id,
      send_at: paint.clickAt, mate_at: paint.mateAt, answer_at: paint.answerAt, final_at: final.at } };
}
async function main() {
  const { chromium } = require('playwright');
  const wire = []; const results = [];
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const clips = [];
  let videoPath = null;
  async function closeContext() {
    if (!main.context) return;
    const video = main.page.video();
    await main.context.close();
    if (video) clips.push(await video.path());
    main.context = null;
    main.page = null;
  }
  try {
    // One fresh browser context per prompt provides its cold sample; two following
    // samples reuse the same authenticated context and connections.
    for (const item of plan) {
      const fresh = item.sample === 'cold';
      if (fresh) {
        await closeContext();
        main.context = await browser.newContext({ viewport: { width: 1440, height: 900 },
          recordVideo: { dir: output, size: { width: 1440, height: 900 } } });
        main.page = await main.context.newPage();
        main.page.on('websocket', wireObserver(wire));
        await login(main.page, readAccount());
      }
      try {
        const result = await sample(main.page, wire, item);
        results.push(result);
      } catch (error) {
        results.push({ prompt_id: item.id, sample: item.sample, status: 'failed', reason: error.message });
        throw error;
      }
    }
  } finally {
    await closeContext();
    await browser.close();
    if (results.length === plan.length && results.every(x => x.status === 'complete') && clips.length === 2) {
      // Lossless concatenation of the two personal-chat context recordings.
      const list = path.join(output, 'clips.private.txt');
      fs.writeFileSync(list, clips.map(clip => `file '${clip.replace(/'/g, "'\\''")}'`).join('\n') + '\n', { mode: 0o600 });
      const combined = path.join(output, 'ordinary-web-combined.webm');
      const render = spawnSync('ffmpeg', ['-nostdin', '-hide_banner', '-loglevel', 'error', '-f', 'concat',
        '-safe', '0', '-i', list, '-c', 'copy', '-y', combined], { encoding: 'utf8', timeout: 30000 });
      fs.unlinkSync(list);
      if (render.status === 0 && fs.existsSync(combined)) videoPath = combined;
      else if (fs.existsSync(combined)) fs.unlinkSync(combined);
    }
    const privateData = results.map(({ _private, ...publicRow }) => ({ ...publicRow, ...( _private ? { source: _private } : {}) }));
    const publicData = results.map(({ _private, ...publicRow }) => publicRow);
    fs.writeFileSync(path.join(output, 'source-correlation.private.json'), JSON.stringify(privateData, null, 2), { mode: 0o600 });
    fs.writeFileSync(path.join(output, 'metrics.json'), JSON.stringify({ mode: 'executed', client: 'ordinary-web',
      app_origin: APP_ORIGIN, api_origin: API_ORIGIN, results: publicData,
      low_thinking_verified: false, video: videoPath && results.every(x => x.status === 'complete') ? path.basename(videoPath) : null }, null, 2), { mode: 0o600 });
    // Retain raw clips, including failed cohorts, for diagnosis. Deliver only
    // the core combined successful recording under the user's media limit.
  }
}
main().catch(error => { process.stderr.write(`Ordinary web benchmark failed: ${error.message}\n`); process.exitCode = 1; });
