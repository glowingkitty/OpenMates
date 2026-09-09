#!/usr/bin/env node
/**
 * Real encrypted Task push/replay probe for the isolated GitHub runner only.
 * Uses its paired CLI session, candidate-built foreground CLI and real API/DB.
 * Browser edits arrive independently while the probe observes private disk state.
 * Reports synthetic fixture IDs and check names; never session keys or payloads.
 * Source-bound evidence is owned by project-task-sync.spec.ts and the CI harness.
 */
import assert from 'node:assert/strict';
import { spawn, execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { randomUUID, randomBytes } from 'node:crypto';
import { mkdirSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { createInterface } from 'node:readline';
import { OpenMatesClient } from '../frontend/packages/openmates-cli/src/client.ts';
import { encryptBytesWithAesGcm, encryptWithAesGcmCombined } from '../frontend/packages/openmates-cli/src/crypto.ts';
import { buildCreateUserTaskInput, buildUpdateUserTaskInput, decryptUserTask } from '../frontend/packages/openmates-cli/src/tasksCli.ts';
import { startRemoteAccessSource } from '../frontend/packages/openmates-cli/src/remoteAccess.ts';
import { taskMutationStore } from '../frontend/packages/openmates-cli/src/taskMutationDelivery.ts';
import { TaskDeliveryPending } from '../frontend/packages/openmates-cli/src/taskDelivery.ts';
import { ProjectTaskCache } from '../frontend/packages/openmates-cli/src/projectTaskSync.ts';

const apiUrl = process.env.OPENMATES_API_URL;
assert.equal(apiUrl, 'http://localhost:8000', 'Run only against the isolated runner API');
assert.equal(process.env.CI, 'true', 'This integration probe belongs on GitHub CI');
const client = new OpenMatesClient({ apiUrl });
assert.ok(client.hasSession(), 'Pair the real candidate CLI first');
const master = client.getMasterKeyBytes();
const projectId = randomUUID(), sourceId = randomUUID(), key = randomBytes(32);
const folder = mkdtempSync(join(tmpdir(), 'task-sync-integration-'));
const rootPath = join(folder, 'files'), cacheRoot = join(folder, 'cache');
mkdirSync(rootPath);
const now = Math.floor(Date.now() / 1000);
const tasks = [];
let bridge;
let stage = 'create_project';
const scope = JSON.stringify([client.getSession().apiUrl, client.getSession().hashedEmail, 'personal']);
const cache = new ProjectTaskCache(cacheRoot, scope, projectId);
const snapshotFile = join(cache.directory, 'snapshot.json');
function snapshot() { try { return JSON.parse(readFileSync(snapshotFile, 'utf8')); } catch (error) { if (error.code === 'ENOENT') return null; throw error; } }
async function until(predicate, message) {
  const deadline = Date.now() + 20_000;
  while (Date.now() < deadline) { if (predicate()) return; await new Promise(resolve => setTimeout(resolve, 100)); }
  throw new Error(message);
}
function start() {
  bridge = spawn('node', [resolve('frontend/packages/openmates-cli/dist/cli.js'), 'remote-access', '--personal', '--path', rootPath, '--task-cache', cacheRoot, '--json'], {
    env: process.env, stdio: ['ignore', 'pipe', 'pipe'],
  });
  // Retain only a bounded count of diagnostics; private account output is not an artifact.
  let diagnostics = 0;
  bridge.stdout.on('data', data => { diagnostics += data.length; });
  bridge.stderr.on('data', data => { diagnostics += data.length; });
  bridge.on('error', () => { diagnostics++; });
}
async function stop() {
  if (!bridge || bridge.exitCode !== null) return;
  const stopped = new Promise(resolve => bridge.once('exit', resolve));
  bridge.kill('SIGTERM');
  const timer = setTimeout(() => bridge.kill('SIGKILL'), 5000);
  try { await stopped; } finally { clearTimeout(timer); }
}
const emit = data => process.stdout.write(JSON.stringify(data) + '\n');
try {
  await client.createProject({ project_id: projectId, encrypted_project_key: await encryptBytesWithAesGcm(key, master),
    encrypted_name: await encryptWithAesGcmCombined('Task sync CI fixture', key), encrypted_description: await encryptWithAesGcmCombined('', key),
    encrypted_icon: await encryptWithAesGcmCombined('folder', key), encrypted_color: await encryptWithAesGcmCombined('default', key),
    pinned: false, created_at: now, updated_at: now, last_opened_at: now, key_wrappers: [] });
  stage = 'create_source';
  await client.createProjectSource(projectId, {source_id: sourceId, source_type: 'local_folder',
    encrypted_display_name: await encryptWithAesGcmCombined('Task sync CI source', key), encrypted_metadata: await encryptWithAesGcmCombined('{}', key),
    capabilities: ['read', 'search', 'import'], status: 'offline', created_at: now, updated_at: now });
  startRemoteAccessSource({ sourceId, projectId, rootPath, sourceType: 'local_folder', displayName: 'Task sync CI source' });
  stage = 'create_tasks';
  for (let i = 0; i < 12; i++) tasks.push(await client.createUserTask(await buildCreateUserTaskInput(master, {
    title: `Task sync fixture ${i} ${randomUUID()}`, description: 'Only the most recent activity belongs in cached context.', projectIds: [projectId],
  })));
  stage = 'ownership';
  const owner = process.env.OPENMATES_TASK_TEST_CODEX_THREAD_ID;
  assert.ok(owner, 'Include tasks-flow.spec.ts so the existing harness provisions its genuine Codex fixture');
  async function connectTask(task) {
    const result = await promisify(execFile)('node', [resolve('frontend/packages/openmates-cli/dist/cli.js'), 'tasks', 'connect', task.task_id, '--thread', owner, '--json'], {
      env: {...process.env, CODEX_THREAD_ID: owner}, timeout: 30_000,
    });
    return JSON.parse(result.stdout);
  }
  await connectTask(tasks[4]);
  const claimed = await client.getUserTask(tasks[4].task_id, {personal:true});
  await connectTask(tasks[4]);
  assert.equal((await client.getUserTask(tasks[4].task_id, {personal:true})).version, claimed.version, 'Same-owner claim must be idempotent');
  const competing = await buildUpdateUserTaskInput(await decryptUserTask(claimed, master), master, {externalChat:{provider:'codex',id:randomUUID(),title:'Competing CI claimant'}});
  await assert.rejects(client.updateUserTask(claimed.task_id, competing, {personal:true}), error => error.status === 409);
  stage = 'dependency';
  await connectTask(tasks[5]);
  await client.addTaskDependency(tasks[5].task_id, `task:${tasks[6].task_id}`);
  const waiting = await client.getUserTask(tasks[5].task_id, {personal:true});
  assert.equal((await client.blockUserTask(waiting.task_id, {version:waiting.version, blocked_reason_code:'external_dependency'})).status, 'blocked');
  const dependency = await client.getUserTask(tasks[6].task_id, {personal:true});
  await client.completeUserTask(dependency.task_id, {version:dependency.version});
  assert.equal((await client.getUserTask(waiting.task_id, {personal:true})).status, 'todo', 'Dependency completion must persist Todo in the database');
  stage = 'lost_acknowledgement';
  const editTarget = await client.getUserTask(tasks[7].task_id, {personal:true});
  const patch = await buildUpdateUserTaskInput(await decryptUserTask(editTarget, master), master, {title:'Accepted before the simulated response loss'});
  let writes=0, clock=Date.now();
  const transport = new Proxy(client, {get(target, property) {
    if (property === 'updateUserTask') return async (...args) => {
      writes++;
      await target.updateUserTask(...args);
      throw Object.assign(new Error('Simulated loss after the real API acknowledged the write'), {status:503});
    };
    const value=Reflect.get(target, property);
    return typeof value === 'function' ? value.bind(target) : value;
  }});
  const delivery = taskMutationStore([client.getSession().apiUrl,client.getSession().hashedEmail,'personal'], join(folder,'loss-test-delivery'), ()=>clock);
  await assert.rejects(delivery.deliver('a'.repeat(64), async()=>({kind:'update',taskId:editTarget.task_id,input:patch}),transport), TaskDeliveryPending);
  clock+=7000;
  await delivery.flush(transport);
  assert.equal(writes,1,'Lost acknowledgement must reconcile through the real API without a duplicate PATCH');
  stage = 'initial_sync';
  start();
  await until(() => snapshot()?.connection === 'connected' && snapshot().tasks.length === 12, 'Initial snapshot did not contain all twelve Tasks');
  emit({event: 'ready', task_id: tasks[0].task_id, snapshot: snapshotFile, project_id: projectId});
  const input = createInterface({input: process.stdin});
  for await (const line of input) {
    if (line !== 'verify-replay') continue;
    stage = 'replay';
    await stop();
    const previous = await client.getUserTask(tasks[1].task_id, {personal: true});
    const decrypted = await decryptUserTask(previous, master);
    const changed = await client.updateUserTask(previous.task_id, await buildUpdateUserTaskInput(decrypted, master, {title: 'Changed while remote access was stopped'}), {personal: true});
    const removed = await client.getUserTask(tasks[2].task_id, {personal: true});
    await client.deleteUserTask(removed.task_id, removed.version);
    start();
    await until(() => {
      const data = snapshot();
      return data?.connection === 'connected' && data.tasks.length === 11 && data.tasks.some(task => task.task_id === changed.task_id && task.title === 'Changed while remote access was stopped') && !data.tasks.some(task => task.task_id === removed.task_id);
    }, 'Reconnect did not replay update and deletion');
    emit({event: 'verified', checks: ['twelve_tasks', 'single_owner', 'dependency_todo', 'lost_ack_reconciled', 'reconnect_update', 'reconnect_deletion']});
    break;
  }
  input.close();
} catch (error) {
  // Stage and HTTP status are sufficient diagnostics without encrypted/session payloads.
  emit({event: 'failure', stage, error: error?.name ?? 'Error', status: error?.status ?? null});
  process.exitCode = 1;
} finally {
  await stop();
  for (const task of tasks) {
    const current = await client.getUserTask(task.task_id, {personal: true});
    if (current) await client.deleteUserTask(current.task_id, current.version);
  }
  // The isolated account/stack owns project cleanup; no shared account is used.
  rmSync(folder, {recursive: true, force: true});
}
