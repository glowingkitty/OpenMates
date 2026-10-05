/** Real CLI/client-crypto workload adapter for scripts/storage_capacity.py.
 *
 * State manifest contains only disposable isolated-runner account state paths.
 * Version and page adapters are mandatory because those interfaces are supplied
 * by their owning storage phases; absence aborts before any workload writes.
 */

import { createHash, randomUUID } from 'node:crypto';
import { createWriteStream, readFileSync } from 'node:fs';
import { once } from 'node:events';
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';
import { cpus, totalmem } from 'node:os';
import { isMainThread, Worker, workerData, parentPort } from 'node:worker_threads';

const [planPath, resultPath] = process.argv.slice(2);
if (!planPath || !resultPath) throw new Error('Expected plan path and result path');
const plan = JSON.parse(readFileSync(planPath, 'utf8'));
const statesPath = process.env.OPENMATES_CAPACITY_STATES_JSON;
const versionAdapterPath = process.env.OPENMATES_CAPACITY_VERSION_ADAPTER;
const pageAdapterPath = process.env.OPENMATES_CAPACITY_PAGE_ADAPTER;
if (!statesPath || !versionAdapterPath || !pageAdapterPath) {
  throw new Error('Disposable account states, version adapter and archive-page adapter are required');
}
const states = JSON.parse(readFileSync(statesPath, 'utf8'));
if (!Array.isArray(states) || states.length !== plan.users || states.some(s => !s.allowlisted || !s.state_dir)) {
  throw new Error('Every capacity user requires a fresh allowlisted isolated account state');
}
let createCapacityProject;
let writeVersion;
let readArchivedPage;
let OpenMatesClient;
if (!isMainThread) {
  ({ createCapacityProject, writeVersion } = await import(pathToFileURL(resolve(versionAdapterPath)).href));
  ({ readArchivedPage } = await import(pathToFileURL(resolve(pageAdapterPath)).href));
  if (typeof createCapacityProject !== 'function' || typeof writeVersion !== 'function' || typeof readArchivedPage !== 'function') {
    throw new Error('Capacity adapters must export createCapacityProject, writeVersion and readArchivedPage');
  }
  const sdkPath = resolve('frontend/packages/openmates-cli/dist/index.js');
  ({ OpenMatesClient } = await import(pathToFileURL(sdkPath).href));
}
const apiUrl = process.env.OPENMATES_CAPACITY_API_URL;
if (!apiUrl || !/^https?:\/\/(localhost|127\.0\.0\.1|[^/]+\.ci\.test)(:\d+)?$/.test(apiUrl)) {
  throw new Error('Capacity client requires an isolated loopback/ci.test API origin');
}

function payload(user, kind, number, size) {
  const label = `${plan.seed}:${user}:${kind}:${number}`;
  let value = '';
  for (let i = 0; value.length < size; i++) {
    // Python ledger uses four-byte big-endian counters.
    const counter = Buffer.alloc(4);
    counter.writeUInt32BE(i);
    value += createHash('sha256').update(label).update(counter).digest('hex');
  }
  return value.slice(0, size);
}
function digest(value) { return createHash('sha256').update(value).digest('hex'); }

const output = isMainThread ? createWriteStream(resultPath, { flags: 'wx', mode: 0o600 }) : null;
let writeChain = Promise.resolve();
function emit(row) {
  if (!isMainThread) {
    parentPort.postMessage({ type: 'row', row });
    return Promise.resolve();
  }
  writeChain = writeChain.then(async () => {
    if (!output.write(JSON.stringify(row) + '\n')) await once(output, 'drain');
  });
  return writeChain;
}

let active = 0;
let maxActive = 0;
let failed = false;
let workerPhase = 'client_init';
const start = performance.now();
function failureRow(error, fallbackPhase) {
  const phases = new Set(['client_init', 'project_create', 'round_send', 'embed_readback',
    'archive_readback', 'version_write', 'version_send', 'version_callback_count', 'version_readback']);
  const phase = phases.has(error?.capacityPhase) ? error.capacityPhase : fallbackPhase;
  const name = error?.capacityErrorClass || error?.name || 'Error';
  const errorClass = new Set(['Error', 'TypeError', 'RangeError', 'SyntaxError',
    'ReferenceError', 'AggregateError', 'AbortError']).has(name) ? name : 'Error';
  const stack = String(error?.stack || '');
  const frame = /(storage_capacity_(?:client|version_adapter|page_adapter)\.mjs):(\d+):\d+/.exec(stack);
  const sourceLocation = error?.capacitySourceLocation || (frame
    ? `${frame[1]}:${frame[2]}` : 'storage_capacity_client.mjs:unavailable');
  return { kind: 'failure', phase, error_class: errorClass, source_location: sourceLocation,
    // This field is restricted to the mode-0600 runner-private result and
    // bounded diagnostic artifact; verification never copies it to public JSON.
    reason: String(error?.message || error).slice(0, 200) };
}
async function withSlot(action) {
  parentPort.postMessage({ type: 'inflight', delta: 1 });
  try { return await action(); }
  finally { parentPort.postMessage({ type: 'inflight', delta: -1 }); }
}
async function oneUser(user) {
  workerPhase = 'client_init';
  const client = new OpenMatesClient({ apiUrl });
  if (!client.hasSession()) throw new Error('Capacity account state has no valid real CLI session');
  let chatId;
  const embedIds = [];
  let archiveSamples = 0;
  workerPhase = 'project_create';
  const project = await createCapacityProject(client, user);
  for (let round = 0; round < plan.rounds_per_user; round++) {
    if (failed) return;
    if (plan.profile === 'sustained') {
      const due = workerData.userStartEpoch + round * workerData.userDurationSeconds * 1000 / plan.rounds_per_user;
      const delay = due - Date.now();
      if (delay > 0) await new Promise(resolve => setTimeout(resolve, delay));
    }
    const text = payload(user, 'round', round, plan.payload_bytes.round);
    const preparedEmbeds = [];
    let embedText;
    let embedId;
    if (round < plan.embeds_per_user) {
      embedText = payload(user, 'embed', round, plan.payload_bytes.embed);
      embedId = randomUUID();
      preparedEmbeds.push({
        embedId, type: 'code', status: 'finished', textPreview: `Capacity code ${round}`,
        content: JSON.stringify({ code: embedText, language: 'text' }),
      });
    }
    const dispatchedAt = performance.now();
    const scenario = round % 50 === 10 ? 'child' : round % 20 === 0 ? 'tool' : 'round';
    workerPhase = 'round_send';
    const response = await withSlot(() => client.sendMessage({
        message: `${text}\nSTORAGE_CAPACITY_SCENARIO:${scenario}`,
        testMockMarker: '<<<TEST_LIVE_MOCK:storage_capacity_v1>>>',
        chatId, preparedEmbeds,
        autoApproveSubChats: scenario === 'child',
      }));
      if (response.status !== 'completed' || !response.chatId || !response.messageId) {
        throw new Error('Full application turn did not complete with persisted response');
      }
      chatId = response.chatId;
      if (scenario === 'child' && (!response.subChatEvents?.some(event => event.type === 'spawn_sub_chats') ||
          !response.subChatEvents?.some(event => event.type === 'sub_chat_completed'))) {
        throw new Error('Synthetic child was not dispatched and completed through the full path');
      }
      await emit({ kind: 'round', user, number: round, status: 'persisted', client_crypto: true,
        content_sha256: digest(text), duration_ms: performance.now() - dispatchedAt,
        child_completed: scenario === 'child' });
      if (embedId) {
        workerPhase = 'embed_readback';
        const stored = await client.getEmbed(embedId);
        if (stored?.content?.code !== embedText) throw new Error('Client decrypted embed differs from expected payload');
        embedIds.push(embedId);
        await emit({ kind: 'embed', user, number: round, status: 'persisted', client_crypto: true,
          content_sha256: digest(embedText) });
      }
      if (round % 20 === 19) {
        workerPhase = 'archive_readback';
        const page = await readArchivedPage({ client, chatId, user, round, cache: 'cold' });
        if (page.archived) {
          archiveSamples++;
          await emit({ kind: 'archive_page', cache: page.cache, ready_ms: page.readyMs,
            authorized: page.authorized === true, decrypted: page.decrypted === true,
            archive_page_ids: page.archivePageIds });
        }
      }
      const firstVersion = Math.floor(round * plan.versions_per_user / plan.rounds_per_user);
      const afterVersion = Math.floor((round + 1) * plan.versions_per_user / plan.rounds_per_user);
      for (let number = firstVersion; number < afterVersion; number++) {
        workerPhase = 'version_write';
        const versionText = payload(user, 'version', number, plan.payload_bytes.version);
        const result = await withSlot(() => writeVersion({ client, chatId, project, user, number, content: versionText }));
        if (result?.persisted !== true || result?.reconstructedContent !== versionText) {
          throw new Error('Encrypted version write/reconstruction failed');
        }
        await emit({ kind: 'version', user, number, status: 'persisted', client_crypto: true,
          content_sha256: digest(versionText), reconstructed_sha256: digest(result.reconstructedContent) });
      }
    }
  if (plan.rounds_per_user >= 30 && archiveSamples === 0) {
    for (let attempt = 0; attempt < 10 && archiveSamples === 0; attempt++) {
      await new Promise(resolve => setTimeout(resolve, 3000));
      workerPhase = 'archive_readback';
      const page = await readArchivedPage({ client, chatId, user, round: plan.rounds_per_user, cache: 'cold' });
      if (page.archived) {
        archiveSamples++;
        await emit({ kind: 'archive_page', cache: page.cache, ready_ms: page.readyMs,
          authorized: page.authorized === true, decrypted: page.decrypted === true,
          archive_page_ids: page.archivePageIds });
      }
    }
  }
  if (plan.rounds_per_user >= 30 && archiveSamples === 0) throw new Error('No real archived page became readable after checkpoint processing');
  if (!embedIds.length) throw new Error('Version workload requires a real encrypted seed embed');
}
if (!isMainThread) {
  process.env.OPENMATES_STATE_DIR = states[workerData.user].state_dir;
  try { await oneUser(workerData.user); }
  catch (error) {
    await emit(failureRow(error, workerPhase));
    process.exitCode = 1;
  }
} else {
  let nextUser = 0;
  const workerCount = Math.min(plan.users, plan.peak_concurrency);
  // RSS is process-wide for Node Worker threads; never sum thread RSS values.
  const driverIdleRssBytes = process.memoryUsage().rss;
  let driverPeakRssBytes = driverIdleRssBytes;
  const sampleDriverRss = () => { driverPeakRssBytes = Math.max(driverPeakRssBytes, process.memoryUsage().rss); };
  const driverSampler = setInterval(sampleDriverRss, 200);
  driverSampler.unref();
  async function runWorker() {
    while (nextUser < plan.users && !failed) {
      const user = nextUser++;
      const worker = new Worker(new URL(import.meta.url), {
        argv: [planPath, resultPath],
        env: { ...process.env, OPENMATES_STATE_DIR: states[user].state_dir },
        workerData: {
          user,
          userStartEpoch: Date.now(),
          userDurationSeconds: plan.duration_seconds * workerCount / plan.users,
        },
      });
      const exitCode = await new Promise((resolveExit) => {
        worker.on('message', (message) => {
          if (message?.type === 'row') emit(message.row);
          else if (message?.type === 'inflight') {
            active += message.delta;
            maxActive = Math.max(maxActive, active);
          }
        });
        worker.once('error', (error) => {
          failed = true;
          emit(failureRow(error, 'client_init'));
        });
        worker.once('exit', resolveExit);
      });
      if (exitCode !== 0) failed = true;
    }
  }
  await Promise.all(Array.from({ length: workerCount }, runWorker));
  sampleDriverRss();
  clearInterval(driverSampler);
  await emit({ kind: 'meta', max_concurrency: maxActive, duration_ms: performance.now() - start,
    profile: plan.profile,
    hardware: { logical_cpu_count: cpus().length, memory_bytes: totalmem(),
      network: 'runner loopback to isolated internal Docker network', worker_threads: workerCount,
      driver_idle_peak_bytes: driverIdleRssBytes, driver_sample_peak_bytes: driverPeakRssBytes,
      driver_peak_metric: 'process_rss_peak' } });
  await writeChain;
  output.end();
  await once(output, 'finish');
  if (failed) process.exitCode = 1;
}
