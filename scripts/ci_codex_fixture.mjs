/**
 * Provision real empty Codex thread metadata only inside a GitHub runner.
 * Uses the supported CLI daemon and JSON-RPC APIs, never internal databases.
 * A separate private Codex home survives the OpenMates CLI pairing HOME change.
 * No prompt/turn/generation method is permitted; no account credentials inherit.
 * See docs/architecture/isolated-github-tests.md and official Codex App Server docs.
 */
import { execFileSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { mkdirSync, readFileSync, writeFileSync, appendFileSync, existsSync } from 'node:fs';
import path from 'node:path';

const source = process.env.OPENMATES_CI_SOURCE_ROOT;
if (process.env.GITHUB_ACTIONS !== 'true' || process.env.RUNNER_ENVIRONMENT !== 'github-hosted' || !source || !process.env.RUNNER_TEMP) {
  throw new Error('Codex fixture requires an isolated GitHub-hosted runner');
}
const require = createRequire(path.join(source, 'frontend/packages/openmates-cli/package.json'));
const WebSocket = require('ws');
const directory = path.join(process.env.RUNNER_TEMP, 'openmates-codex-fixture');
const codexHome = path.join(directory, 'codex');
const workspace = path.join(directory, 'workspace');
const receiptPath = path.join(source, 'test-results/ci-codex.json');
const methods = new Set(['initialize', 'initialized', 'thread/start', 'thread/read']);
const called = [];
// Deliberately omit user tokens, API keys, inherited Codex endpoints and config.
const env = { PATH: process.env.PATH, HOME: process.env.HOME, CODEX_HOME: codexHome,
  XDG_RUNTIME_DIR: path.join(directory, 'runtime'), LANG: 'C.UTF-8', RUST_LOG: 'error' };
function cli(...args) {
  return execFileSync('codex', args, { env, cwd: workspace, encoding: 'utf8', timeout: 30000, maxBuffer: 65536 });
}
function metadata() { return JSON.parse(cli('app-server', 'daemon', 'version')); }
function rpc(socketPath, action, params) {
  if (!methods.has(action)) throw new Error('Only empty-thread metadata operations are allowed');
  if (!path.isAbsolute(socketPath) || !socketPath.startsWith(directory + path.sep)) {
    throw new Error('Refusing a Codex socket outside this runner-private fixture');
  }
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(`ws+unix://${socketPath}:/`, { perMessageDeflate: false, maxPayload: 1024 * 1024, handshakeTimeout: 10000 });
    const timer = setTimeout(() => { ws.terminate(); reject(new Error('Codex metadata request timed out')); }, 30000);
    const send = (method, id, value) => {
      if (!methods.has(method)) throw new Error('Generation is forbidden in the Codex fixture');
      called.push(method);
      ws.send(JSON.stringify({ method, ...(id ? { id } : {}), ...(value ? { params: value } : {}) }));
    };
    ws.on('open', () => send('initialize', 1, { clientInfo: { name: 'openmates-ci-metadata', version: '1.0.0' } }));
    ws.on('error', error => { clearTimeout(timer); reject(error); });
    ws.on('message', data => {
      const message = JSON.parse(data.toString());
      if (![1, 2].includes(message.id)) return;
      if (message.error) { clearTimeout(timer); ws.close(); reject(new Error('Codex rejected metadata: ' + message.error.message)); return; }
      if (message.id === 1) { send('initialized'); send(action, 2, params); return; }
      clearTimeout(timer); ws.close(); resolve(message.result);
    });
  });
}
const action = process.argv[2];
if (action === 'start') {
  if (existsSync(directory)) throw new Error('Codex fixture directory already exists; do not reuse thread state');
  for (const location of [codexHome, workspace, env.XDG_RUNTIME_DIR]) mkdirSync(location, { recursive: true, mode: 0o700 });
  writeFileSync(path.join(codexHome, 'config.toml'), '[analytics]\nenabled = false\n', { mode: 0o600 });
  cli('app-server', 'daemon', 'start');
  let owned = false;
  try {
    const daemon = metadata();
    if (daemon.status !== 'running' || !daemon.socketPath?.startsWith(directory + path.sep)) throw new Error('Runner-private Codex daemon did not start');
    owned = true;
    const started = await rpc(daemon.socketPath, 'thread/start', { cwd: workspace, approvalPolicy: 'never', sandbox: 'read-only', ephemeral: false });
    const id = started.thread?.id;
    if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id || '')) throw new Error('Codex did not return a real thread UUID');
    // A fresh connection reproduces the product adapter's existing-thread read.
    const read = await rpc(daemon.socketPath, 'thread/read', { threadId: id, includeTurns: false });
    if (read.thread?.id !== id || read.thread?.status?.type === 'active' || (read.thread?.turns || []).length) throw new Error('Fixture thread is not empty and idle');
    const receipt = { thread_id: id, version: cli('--version').trim(), methods: called, inference_requested: false,
      source_commit: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: source, encoding: 'utf8' }).trim(),
      harness_commit: process.env.CI_HARNESS_COMMIT, run_id: process.env.GITHUB_RUN_ID, status: 'ready' };
    mkdirSync(path.dirname(receiptPath), { recursive: true });
    writeFileSync(receiptPath, JSON.stringify(receipt, null, 2));
    appendFileSync(process.env.GITHUB_ENV, `CODEX_HOME=${codexHome}\nXDG_RUNTIME_DIR=${env.XDG_RUNTIME_DIR}\nOPENMATES_TASK_TEST_CODEX_THREAD_ID=${id}\n`);
    console.log(JSON.stringify({ status: 'ready', inference_requested: false }));
  } catch (error) { if (owned) cli('app-server', 'daemon', 'stop'); throw error; }
} else if (action === 'stop') {
  if (existsSync(directory)) {
    const daemon = metadata();
    if (!daemon.socketPath?.startsWith(directory + path.sep)) throw new Error('Refusing to stop a daemon outside the private fixture');
    cli('app-server', 'daemon', 'stop');
  }
} else if (action === 'verify') {
  const receipt = JSON.parse(readFileSync(receiptPath, 'utf8'));
  const daemon = metadata();
  const read = await rpc(daemon.socketPath, 'thread/read', { threadId: receipt.thread_id, includeTurns: false });
  if (read.thread?.id !== receipt.thread_id || read.thread?.status?.type === 'active') throw new Error('Existing fixture thread is unavailable');
  console.log(JSON.stringify({ status: 'passed', inference_requested: false }));
} else throw new Error('Expected start, verify or stop');
