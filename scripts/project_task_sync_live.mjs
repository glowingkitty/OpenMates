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
import { createHash, randomUUID, randomBytes } from 'node:crypto';
import { chmodSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { createInterface } from 'node:readline';
import { OpenMatesClient } from '../frontend/packages/openmates-cli/src/client.ts';
import { encryptBytesWithAesGcm, encryptWithAesGcmCombined } from '../frontend/packages/openmates-cli/src/crypto.ts';
import { buildBlockUserTaskInput, buildCreateUserTaskInput, buildUpdateUserTaskInput, decryptUserTask, taskKeyFromRecord } from '../frontend/packages/openmates-cli/src/tasksCli.ts';
import { buildCreateUserPlanInput, decryptUserPlan } from '../frontend/packages/openmates-cli/src/plansCli.ts';
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
const cliProofRoot = process.env.OPENMATES_TASK_SYNC_CLI_PROOF;
assert.ok(cliProofRoot, 'Real CLI operations require their terminal evidence directory');
const cliBin = join(folder, 'bin');
mkdirSync(cliBin);
chmodSync(resolve('frontend/packages/openmates-cli/dist/cli.js'), 0o755);
symlinkSync(resolve('frontend/packages/openmates-cli/dist/cli.js'), join(cliBin, 'openmates'));
symlinkSync('/usr/bin/zutty', join(cliBin, 'x-terminal-emulator'));
let cliCapture = 0;
async function runCli(args, owner) {
  const result = await promisify(execFile)('python3', ['scripts/cli_video_capture.py',
    '--output-dir', join(cliProofRoot, String(++cliCapture)), '--target-environment', 'isolated-github-ci',
    '--timeout-seconds', '60', '--no-response-media', '--', 'openmates', ...args], {
    env: {...process.env, PATH:`${cliBin}:${process.env.PATH}`, CODEX_THREAD_ID:owner}, timeout:80_000,
  });
  const captured = JSON.parse(result.stdout);
  assert.equal(captured.status, 'passed', 'The recorded CLI operation must succeed');
  return readFileSync(captured.manifest.command_output_path, 'utf8');
}
const now = Math.floor(Date.now() / 1000);
const tasks = [];
let bridge;
let stage = 'create_project';
let nativeChatId, nativePlanId;
let dependencyLinked = false;
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
// This control is restricted to the harness-owned, credential-free daemon. It
// creates one empty fixture and requires its actual deletion notification.
const codexFixtureControl = `
import json, os, subprocess, sys, time
from pathlib import Path
from scripts.codex_rpc import CodexRPC
assert os.environ.get('GITHUB_ACTIONS') == 'true'
fixture = Path(os.environ['RUNNER_TEMP']) / 'openmates-codex-fixture'
assert Path(os.environ['CODEX_HOME']).is_relative_to(fixture)
meta = json.loads(subprocess.check_output(['codex','app-server','daemon','version'], text=True))
assert Path(meta['socketPath']).is_relative_to(fixture)
action, directory = sys.argv[1:3]
receipt = Path(directory) / 'disposable-codex.json'
rpc = CodexRPC()
try:
    if action == 'create':
        assert not receipt.exists()
        result = rpc.call('thread/start', {'cwd':directory,'approvalPolicy':'never','sandbox':'read-only','ephemeral':False})
        thread_id = result['thread']['id']
        receipt.write_text(json.dumps({'thread_id':thread_id}))
        print(json.dumps({'thread_id':thread_id}))
    elif action == 'delete':
        thread_id = json.loads(receipt.read_text())['thread_id']
        # Empty metadata fixtures have no persisted rollout to resume. The
        # delete caller receives thread/deleted directly on this connection.
        rpc.call('thread/delete', {'threadId':thread_id})
        until = time.monotonic() + 5
        confirmed = False
        while time.monotonic() < until and not confirmed:
            confirmed = any(item.get('method') == 'thread/deleted' and item.get('params',{}).get('threadId') == thread_id for item in rpc.poll_notifications(0.5))
        assert confirmed, 'A deletion acknowledgement cannot substitute for the actual event'
        print(json.dumps({'thread_id':thread_id,'confirmed':True}))
    else:
        raise ValueError('Unknown fixture action')
finally:
    rpc.close()
`;
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
  const owner = process.env.OPENMATES_TASK_TEST_CODEX_THREAD_ID;
  assert.ok(owner, 'Include tasks-flow.spec.ts so the existing harness provisions its genuine Codex fixture');
  await runCli(['tasks', 'create', '--title', `Task sync fixture 0 ${randomUUID()}`,
    '--external-chat', `codex:${owner}`, '--project', projectId], owner);
  // Keep the recorded terminal human-readable. One scoped read correlates the
  // sole Task in this fresh Project; create-and-link is still one mutation.
  const created = await client.listUserTasks({projectId,personal:true});
  assert.equal(created.length,1,'The fresh Project must contain exactly the acknowledged CLI Task');
  const first = created[0];
  assert.ok(first?.task_id, 'The real create-and-link command must acknowledge its Task');
  tasks.push(await client.getUserTask(first.task_id, {personal:true}));
  for (let i = 1; i < 12; i++) tasks.push(await client.createUserTask(await buildCreateUserTaskInput(master, {
    title: `Task sync fixture ${i} ${randomUUID()}`, description: 'Only the most recent activity belongs in cached context.', projectIds: [projectId],
  })));
  stage = 'ownership';
  async function connectTask(task) {
    await runCli(['tasks','connect',task.task_id,'--thread',owner],owner);
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
  dependencyLinked = true;
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
    stage = 'native_chat_create';
    nativeChatId = randomUUID();
    const chatKey = randomBytes(32);
    // Store only encrypted metadata through the existing first-party WS protocol.
    // No message, skill, model turn or paid inference is requested.
    const { ws } = await client.openWsClient({taskUpdateJobs:false});
    try {
      const stored = ws.waitForMessage('encrypted_metadata_stored', payload => payload.chat_id === nativeChatId, 20_000);
      ws.send('encrypted_chat_metadata', {chat_id:nativeChatId,
        encrypted_title:await encryptWithAesGcmCombined('Disposable native deletion fixture',chatKey),
        encrypted_icon:await encryptWithAesGcmCombined('chat',chatKey),
        encrypted_chat_category:await encryptWithAesGcmCombined('general_knowledge',chatKey),
        encrypted_chat_key:await encryptBytesWithAesGcm(chatKey,master), created_at:now,
        versions:{messages_v:0,title_v:1,last_edited_overall_timestamp:now}});
      await stored;
    } finally { ws.close(); }
    // The metadata acknowledgement can precede asynchronous database persistence.
    const persistedBy = Date.now() + 20_000;
    for (;;) {
      const response = await client.http.get('/v1/chats?limit=20',client.getCliRequestHeaders());
      assert.ok(response.ok,'Native fixture metadata must remain readable');
      if (response.data.chats.some(chat => chat.id === nativeChatId)) break;
      assert.ok(Date.now() < persistedBy,'Native fixture metadata did not persist');
      await new Promise(resolve => setTimeout(resolve,500));
    }
    stage = 'native_task_links';
    const nativeTitles = new Map();
    for (const index of [8,9,10]) {
      stage = `native_task_link_${index}`;
      const current = await client.getUserTask(tasks[index].task_id,{personal:true});
      const plain = await decryptUserTask(current,master);
      nativeTitles.set(current.task_id,plain.title);
      const patch = await buildUpdateUserTaskInput(plain,master,{chatId:nativeChatId,status:index===8?'in_progress':'todo'});
      const taskKey = await taskKeyFromRecord(current,master);
      // A native link needs chat access while retaining master and Project access.
      // The update builder prepares fields; callers supply context key wrappers.
      patch.key_wrappers = [
        {key_type:'master',encrypted_task_key:current.encrypted_task_key,created_at:now},
        {key_type:'chat',hashed_chat_id:createHash('sha256').update(nativeChatId).digest('hex'),
          encrypted_task_key:await encryptBytesWithAesGcm(taskKey,chatKey),created_at:now},
        {key_type:'project',hashed_project_id:createHash('sha256').update(projectId).digest('hex'),
          encrypted_task_key:await encryptBytesWithAesGcm(taskKey,key),created_at:now},
      ];
      let linked = await client.updateUserTask(current.task_id,patch,{personal:true});
      if (index===9) await client.completeUserTask(linked.task_id,{version:linked.version});
      if (index===10) await client.blockUserTask(linked.task_id,
        await buildBlockUserTaskInput(await decryptUserTask(linked,master),master,
          {reasonCode:'external_dependency',reasonText:'Human review must remain required.'}));
    }
    stage = 'native_plan_create';
    const nativePlanTitle = `Native deletion Plan fixture ${nativeChatId}`;
    const plan = await client.createUserPlan(await buildCreateUserPlanInput(master,
      {title:nativePlanTitle,status:'active',primaryChatId:nativeChatId,primaryChatKey:chatKey,
        linkedProjectIds:[projectId],linkedProjectKeys:[{projectId,projectKey:key}]}));
    nativePlanId = plan.plan_id;
    stage = 'native_chat_delete';
    await client.deleteChat(nativeChatId,{personal:true});
    stage = 'native_unlink_assertions';
    // chat_deleted acknowledges the queued deletion; SQL cleanup commits in
    // the persistence worker. Observe that commit before checking its effects.
    const unlinkedBy = Date.now() + 20_000;
    for (;;) {
      const probe = await client.getUserTask(tasks[8].task_id,{personal:true});
      if (probe.primary_chat_id === null) break;
      assert.ok(Date.now() < unlinkedBy,'Native deletion did not commit Task unlink');
      await new Promise(resolve => setTimeout(resolve,500));
    }
    for (const [index,expected] of [[8,'todo'],[9,'done'],[10,'blocked']]) {
      const record = await client.getUserTask(tasks[index].task_id,{personal:true});
      assert.equal(record.primary_chat_id,null,'Confirmed native deletion must unlink Tasks');
      assert.equal(record.status,expected,'Deletion must preserve Done and independent blockers');
      const plain = await decryptUserTask(record,master);
      assert.equal(plain.title,nativeTitles.get(record.task_id),'Task keys must remain usable');
      if (index===10) assert.equal(plain.blockedReason,'Human review must remain required.');
    }
    const detachedPlan = (await client.listUserPlans({projectId,personal:true})).find(item => item.plan_id===nativePlanId);
    assert.ok(detachedPlan,'Linked Plan must survive native chat deletion');
    assert.equal(detachedPlan.primary_chat_id,null);
    assert.equal(detachedPlan.status,'awaiting_confirmation');
    assert.equal(detachedPlan.continuation_state,'paused');
    assert.equal((await decryptUserPlan(detachedPlan,master)).title,nativePlanTitle);
    stage = 'confirmed_codex_create';
    const disposable = JSON.parse((await promisify(execFile)('python3',['-c',codexFixtureControl,'create',rootPath],{env:process.env,timeout:30_000})).stdout);
    stage = 'confirmed_codex_claim';
    await runCli(['tasks','connect',tasks[11].task_id,'--thread',disposable.thread_id],disposable.thread_id);
    const owned = await client.getUserTask(tasks[11].task_id,{personal:true});
    const ownership = owned.external_chat_lookup_hash;
    assert.ok(ownership);
    stage = 'confirmed_codex_delete';
    const deleted = JSON.parse((await promisify(execFile)('python3',['-c',codexFixtureControl,'delete',rootPath],{env:process.env,timeout:30_000})).stdout);
    assert.equal(deleted.confirmed,true);
    stage = 'confirmed_codex_unlink';
    const eventId = createHash('sha256').update(`ci-confirmed-delete:${disposable.thread_id}`).digest('hex');
    assert.equal((await client.unlinkDeletedTaskChat(ownership,eventId,{personal:true})).unlinked_tasks,1);
    assert.equal((await client.unlinkDeletedTaskChat(ownership,eventId,{personal:true})).unlinked_tasks,0,'Repeated delivery must be idempotent');
    const detached = await client.getUserTask(owned.task_id,{personal:true});
    assert.equal(detached.external_chat_provider,null);
    assert.equal((await decryptUserTask(detached,master)).title,(await decryptUserTask(owned,master)).title);
    emit({event: 'verified', checks: ['twelve_tasks', 'single_owner', 'dependency_todo', 'lost_ack_reconciled', 'reconnect_update', 'reconnect_deletion','native_chat_task_plan_unlink','confirmed_codex_unlink']});
    break;
  }
  input.close();
} catch (error) {
  // Stage and HTTP status are sufficient diagnostics without encrypted/session payloads.
  emit({event: 'failure', stage, error: error?.name ?? 'Error', status: error?.status ?? (Number(error?.message?.match(/HTTP (\d{3})/)?.[1]) || null), exit_code: error?.code ?? null,
    check:error?.code==='ERR_ASSERTION'?error.message.split('\n')[0].slice(0,180):undefined});
  process.exitCode = 1;
} finally {
  try {
    await stop();
    if (dependencyLinked) await client.removeTaskDependency(tasks[5].task_id,'task',tasks[6].task_id);
    if (nativePlanId) {
      const plan = (await client.listUserPlans({projectId,personal:true})).find(item => item.plan_id===nativePlanId);
      if (plan) await client.deleteUserPlan(plan.plan_id,plan.version);
    }
    for (const task of tasks) {
      const current = await client.getUserTask(task.task_id, {personal: true});
      if (current) await client.deleteUserTask(current.task_id, current.version);
    }
    emit({event:'finished'});
  } catch (error) {
    emit({event:'failure',stage:'cleanup',error:error?.name ?? 'Error',
      status:error?.status ?? (Number(error?.message?.match(/HTTP (\d{3})/)?.[1]) || null)});
    process.exitCode = 1;
  } finally {
    // The isolated account/stack owns Project cleanup; no shared account is used.
    rmSync(folder, {recursive: true, force: true});
  }
}
