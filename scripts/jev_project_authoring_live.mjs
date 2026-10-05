#!/usr/bin/env node
/**
 * Disposable REAL-INFERENCE proof for TASK-8917 / approved Plan AC-13, AC-14.
 * Never run automatically or in CI. Run only after scoped dev deployment and a
 * dev lease, using a separately paired disposable account with paid credits.
 *
 * Prerequisites: current built CLI dist/index.js, Node with strip-types support,
 * the existing CLI test loader, Google/Jev providers, Project + Workflow APIs,
 * ask worker/postprocessor, encrypted hosted CAS, source-write settlement.
 *
 * Bootstrap a FRESH /tmp/openmates-authoring-live.* state directory using the
 * existing openmates_cli_test_account.mjs login helper and explicit disposable
 * credentials injected by the runner. Do not use a personal/engineering session.
 * Supply OPENMATES_LIVE_DISPOSABLE_HASHED_EMAIL matching that session, plus
 * OPENMATES_LIVE_AUTHORING=run-disposable. Credentials are never printed.
 *
 * Invocation (runner supplies the two authorization environment values):
 * OPENMATES_STATE_DIR=/tmp/openmates-authoring-live.XXXXXX \
 * node --experimental-strip-types --loader ./frontend/packages/openmates-cli/tests/loader.mjs \
 *   scripts/jev_project_authoring_live.mjs https://api.dev.openmates.org
 * Optional --focus-only omits Workflow/physical-folder checks and records a skip.
 * Only this harness's Project, chat, Workflow and physical directory are deleted.
 * Evidence contains IDs/statuses/revisions/digests, never private bodies or keys.
 */
import { randomUUID, randomBytes, createHash } from 'node:crypto';
import { existsSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import { join, resolve, basename, isAbsolute } from 'node:path';
import { tmpdir } from 'node:os';
import { createRequire } from 'node:module';

const root = resolve(import.meta.dirname, '..');
const cliDirectory = join(root, 'frontend/packages/openmates-cli');
const apiUrl = (process.argv.find(value => /^https?:/.test(value)) ?? 'https://api.dev.openmates.org').replace(/\/$/, '');
const focusOnly = process.argv.includes('--focus-only');
const stateDirectory = process.env.OPENMATES_STATE_DIR;
function requireValue(value, code) { if (!value) throw Object.assign(new Error(code), { code }); }
requireValue(process.env.OPENMATES_LIVE_AUTHORING === 'run-disposable', 'explicit_disposable_authorization_required');
requireValue(stateDirectory && isAbsolute(stateDirectory) && existsSync(stateDirectory), 'private_disposable_state_required');
requireValue(realpathSync(stateDirectory).startsWith(realpathSync(tmpdir()) + '/')
  && basename(stateDirectory).startsWith('openmates-authoring-live.'), 'fresh_tmp_state_required');
requireValue(/^(?:https:\/\/api\.dev\.openmates\.org|http:\/\/(?:localhost|127\.0\.0\.1)(?::\d+)?)$/.test(apiUrl), 'dev_target_required');
requireValue(existsSync(join(cliDirectory, 'dist/index.js')), 'current_cli_build_required');
// Provider/transport helpers may emit debugging logs. This standalone harness
// exposes only its explicitly selected, content-free evidence below.
for (const method of ['log', 'info', 'debug', 'warn', 'error']) console[method] = () => {};

const { OpenMatesClient } = await import('../frontend/packages/openmates-cli/dist/index.js');
const { encryptWithAesGcmCombined, encryptBytesWithAesGcm, decryptWithAesGcmCombined } = await import('../frontend/packages/openmates-cli/src/crypto.ts');
const { projectItemRevision, boundedAuthoringHistory } = await import('../frontend/packages/openmates-cli/src/cliProjectAuthoring.ts');
const { persistCliProjectAuthoringJob, AuthoringSaveApprovalRequired } = await import('../frontend/packages/openmates-cli/src/cliProjectAuthoringSave.ts');
const { parseFocusAuthoringDocument, loadActiveCliProjectContext } = await import('../frontend/packages/openmates-cli/src/cliJevContext.ts');
const { runRemoteAccessBridge } = await import('../frontend/packages/openmates-cli/src/remoteAccess.ts');
const { registerCliProjectFileExecutor } = await import('../frontend/packages/openmates-cli/src/projectFileExecutor.ts');
const { validateWorkflowFile } = await import('../frontend/packages/workflowFile.ts');
const { parse: parseYaml } = createRequire(join(cliDirectory, 'package.json'))('yaml');
const client = OpenMatesClient.load({ apiUrl });
requireValue(client.hasSession(), 'paired_disposable_session_required');
requireValue(process.env.OPENMATES_LIVE_DISPOSABLE_HASHED_EMAIL
  && client.getSession().hashedEmail === process.env.OPENMATES_LIVE_DISPOSABLE_HASHED_EMAIL, 'disposable_account_identity_mismatch');
requireValue(!client.getActiveTeamId(), 'personal_disposable_scope_required');

const evidencePath = process.env.OPENMATES_LIVE_EVIDENCE ?? join(stateDirectory, `authoring-evidence-${randomUUID()}.json`);
// Keep the served filesystem outside CLI credential storage and its protected
// ancestry. Only this newly created directory is exposed to the source bridge.
const physicalRoot = mkdtempSync(join(tmpdir(), 'openmates-authoring-folder-'));
const fixture = { projectId: randomUUID(), chatId: randomUUID(), sourceId: randomUUID(), workflowId: null,
  projectKey: new Uint8Array(randomBytes(32)), defaultFocusId: randomUUID(), projectAttempted: false, chatAttempted: false,
  workflowAttempted: false, workflowTitle: '' };
const steps = [];
const abort = new AbortController();
let bridge;
let fileSocket;
let stopFileExecutor;
const time = () => Math.floor(Date.now() / 1000);
const defaultInstruction = 'Work only on the synthetic disposable verification. Discuss the specified reusable debugging process; do not write files, execute workflows or create tasks from chat.';
const digest = text => createHash('sha256').update(text).digest('hex');
const delay = milliseconds => new Promise(resolveDelay => setTimeout(resolveDelay, milliseconds));
function record(step, values = {}) {
  const entry = { step, at: new Date().toISOString(), ...values };
  steps.push(entry);
  // Every value supplied here is content-free fixture evidence.
  process.stdout.write(JSON.stringify(entry) + '\n');
  writeFileSync(evidencePath, JSON.stringify({ api_url: apiUrl, fixture_project_id: fixture.projectId, steps }, null, 2), { mode: 0o600 });
}
// Shape-only evidence covers the actual automatic CLI assessment too. Never
// retain message prose or provider request/response payloads in live receipts.
const requestRecommendations = client.requestProjectAuthoringRecommendations.bind(client);
client.requestProjectAuthoringRecommendations = async (projectId, input) => {
  record('recommendation_history_shape', {
    history: input.history.map(row => ({ role: row.role, content_length: row.content.length,
      explicit_reusable_focus: row.content.includes('reusable Project Debugging Playbook Focus'),
      established_old_guide: row.content.includes('established old guide'),
      proven_source_marker: row.content.includes('SOURCE-PROVENANCE-47'),
      synthetic_case_marker: row.content.includes('SYNTHETIC-CASE-52') })),
    catalog_count: input.catalog.length,
    catalog_kinds: input.catalog.map(row => row.kind),
  });
  return requestRecommendations(projectId, input);
};
async function waitUntil(probe, code, timeout = 300_000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) { const value = await probe(); if (value) return value; await delay(1_500); }
  throw Object.assign(new Error(code), { code });
}
async function request(path, method = 'GET', body) {
  const response = await fetch(apiUrl + path, { method,
    headers: { 'Content-Type': 'application/json', Cookie: Object.entries(client.getSession().cookies).map(([name, value]) => `${name}=${value}`).join('; '),
      'User-Agent': 'OpenMates CLI disposable authoring proof' },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
  const data = await response.json().catch(() => ({}));
  requireValue(response.ok || method === 'DELETE' && response.status === 404, `fixture_http_${response.status}`);
  return data;
}
async function createProject() {
  fixture.projectAttempted = true;
  await client.createProject({ project_id: fixture.projectId,
    encrypted_project_key: await encryptBytesWithAesGcm(fixture.projectKey, client.getMasterKeyBytes()),
    encrypted_name: await encryptWithAesGcmCombined(`Disposable authoring ${fixture.projectId.slice(0, 8)}`, fixture.projectKey),
    encrypted_description: await encryptWithAesGcmCombined('', fixture.projectKey),
    encrypted_icon: await encryptWithAesGcmCombined('folder', fixture.projectKey),
    encrypted_color: await encryptWithAesGcmCombined('default', fixture.projectKey),
    pinned: false, created_at: time(), updated_at: time(), last_opened_at: time(), write_mode: 'always_ask',
    default_focus_id: fixture.defaultFocusId,
    encrypted_settings: await encryptWithAesGcmCombined(JSON.stringify({ default_focus: { focus_id: fixture.defaultFocusId,
      name: 'Disposable authoring verification', instructions: defaultInstruction, source: 'generated' } }), fixture.projectKey),
  });
  record('encrypted_disposable_project_created', { project_id: fixture.projectId });
}
async function conversation(prompt, initial = false) {
  fixture.chatAttempted = true;
  const response = await client.sendMessage({ message: prompt, projectId: fixture.projectId,
    ...(initial ? { newChatId: fixture.chatId } : { chatId: fixture.chatId }), personal: true,
    taskUpdateJobs: false, responseTimeoutMs: 300_000,
    onProjectWriteApproval: () => false, onProjectReadApproval: () => false,
  });
  requireValue(response.status === 'completed' && response.assistant, 'real_project_response_required');
  const saved = await client.getChatMessages(fixture.chatId, { personal: true });
  const user = [...saved.messages].reverse().find(message => message.role === 'user');
  requireValue(user, 'persisted_originating_user_turn_required');
  const userId = user.clientMessageId || user.id;
  record('actual_project_response_permit', { user_message_id: userId, assistant_message_id: response.messageId });
  return { userId, assistant: response.assistant,
    history: boundedAuthoringHistory(saved.messages.map(message => ({ role: message.role, content: message.content }))) };
}
async function focusBody(itemId) {
  const detail = await client.getProject(fixture.projectId, { personal: true });
  const item = detail.items.find(row => row.project_item_id === itemId && !row.deleted_target_state);
  requireValue(item, 'selected_focus_owned_item_required');
  const embedId = await decryptWithAesGcmCombined(item.target_id_encrypted, fixture.projectKey);
  const head = await client.readEncryptedProjectFile(fixture.projectId, embedId, fixture.projectKey, { personal: true });
  const markdown = [head.content.code, head.content.content, head.content.text, head.content.markdown].find(value => typeof value === 'string');
  requireValue(markdown, 'saved_focus_body_required');
  return { item, embedId, revision: projectItemRevision(item), head: head.revision, markdown, document: parseFocusAuthoringDocument(markdown) };
}
async function recommend(turn, kind, action, targetId) {
  if (kind === 'focus' && action === 'update') {
    // Explicit owner selection of the fixture's real encrypted default Focus
    // makes the saved specialist inactive before catalog assessment. This is an
    // ordinary activation API action, not an injected inference/write grant.
    await client.activateProjectFocus(fixture.projectId, { chat_id: fixture.chatId,
      focus_id: fixture.defaultFocusId, instruction: defaultInstruction }, { personal: true });
  }
  const detail = await client.getProject(fixture.projectId, { personal: true });
  const catalog = [];
  const linked = new Set();
  for (const item of detail.items.filter(row => !row.deleted_target_state)) {
    const metadata = item.encrypted_metadata ? JSON.parse(await decryptWithAesGcmCombined(item.encrypted_metadata, fixture.projectKey)) : {};
    if (item.item_type === 'workflow') linked.add(await decryptWithAesGcmCombined(item.target_id_encrypted, fixture.projectKey));
    if (metadata.focus_title && metadata.focus_description && metadata.focus_when_to_use) catalog.push({ kind: 'focus', id: item.project_item_id,
      title: metadata.focus_title, summary: metadata.focus_description, revision: projectItemRevision(item) });
  }
  for (const workflow of await client.listWorkflows({ personal: true })) if (linked.has(workflow.id)) catalog.push({ kind: 'workflow',
    id: workflow.id, title: workflow.title, summary: workflow.description ?? '', revision: String(workflow.version) });
  const active = await client.getActiveProjectFocus(fixture.chatId);
  requireValue(active?.project_id === fixture.projectId, 'fresh_project_binding_required');
  const proposals = await client.requestProjectAuthoringRecommendations(fixture.projectId, { chat_id: fixture.chatId,
    message_id: turn.userId, team_id: null, catalog, history: turn.history });
  record('jev_catalog_assessment', { focus_count: catalog.filter(row => row.kind === 'focus').length,
    workflow_count: catalog.filter(row => row.kind === 'workflow').length, inactive_focus_catalog: !active.specialist_focus_id,
    proposal_actions: proposals.map(row => `${row.kind}:${row.action}`) });
  const confirmed = [];
  for (const proposal of proposals) {
    if (proposal.action !== 'inspect') { confirmed.push(proposal); continue; }
    requireValue(proposal.kind === 'focus', 'focus_inspection_only');
    const selected = await focusBody(proposal.target_id);
    requireValue(selected.revision === proposal.expected_revision, 'selected_focus_revision_mismatch');
    const result = await client.inspectProjectFocusRecommendation(fixture.projectId, { assessment_id: proposal.recommendation_id,
      document: selected.document, history: turn.history });
    record('jev_selected_focus_inspection', { selected_item_id: proposal.target_id, selected_revision: selected.revision,
      useful_update: result?.action === 'update' });
    if (result) confirmed.push(result);
  }
  const proposal = confirmed.find(row => row.kind === kind && row.action === action && (!targetId || row.target_id === targetId));
  requireValue(proposal, `real_jev_positive_${kind}_${action}_required`);
  record('validated_explicit_button_intent', { recommendation_id: proposal.recommendation_id, kind, action });
  return proposal;
}
async function author(proposal, turn, remoteBinding) {
  const input = { recommendation_id: proposal.recommendation_id, expected_revision: proposal.expected_revision,
    history: turn.history, timezone: 'UTC', ...(remoteBinding ? { remote_binding: remoteBinding } : {}),
    ...(proposal.kind === 'focus' && proposal.action === 'update' ? { target: (await focusBody(proposal.target_id)).document } : {}) };
  const started = await client.startProjectAuthoringJob(fixture.projectId, input);
  const repeated = await client.startProjectAuthoringJob(fixture.projectId, input);
  requireValue(started.job_id === repeated.job_id, 'authoring_click_idempotency_required');
  record('real_background_authoring_started', { job_id: started.job_id, kind: proposal.kind, same_id_on_repeated_click: true });
  return waitUntil(async () => {
    const job = await client.getProjectAuthoringJob(fixture.projectId, started.job_id);
    if (job.status === 'running' || job.status === 'pending_file') return null;
    return job;
  }, 'background_authoring_timeout');
}
async function persist(job) {
  requireValue(['needs_save', 'needs_binding_save'].includes(job.status), `authoring_result_${job.status}`);
  let ready;
  try {
    ready = await persistCliProjectAuthoringJob(client, job);
  } catch (error) {
    requireValue(error instanceof AuthoringSaveApprovalRequired && job.status === 'needs_save', 'exact_file_save_approval_expected');
    // Explicit harness action approves precisely the resulting synthetic draft;
    // it does not inherit authority from the earlier generation click.
    requireValue(error.mutation.content === job.draft.markdown || typeof error.mutation.patch === 'string', 'concrete_generated_file_required');
    record('exact_generated_file_reviewed_and_save_clicked', { job_id: job.job_id,
      operation_id: error.mutation.operation_id, draft_sha256: digest(job.draft.markdown) });
    ready = await persistCliProjectAuthoringJob(client, job, error.digest);
  }
  requireValue(ready.status === 'ready', 'server_ready_ack_required');
  const notification = await waitUntil(async () => {
    const data = await client.listNotifications();
    return data.events?.find(event => event.type === 'project.authoring_ready' && event.routing?.job_id === job.job_id);
  }, 'ready_notification_required', 30_000);
  requireValue(notification.routing.project_id === fixture.projectId && notification.routing.result_id === ready.result_id,
    'notification_saved_result_identity_required');
  requireValue(!JSON.stringify(notification).includes('SOURCE-PROVENANCE-47'), 'private_instructions_not_in_notification');
  record('encrypted_save_backend_ack_and_notification_ready', { job_id: job.job_id, result_id: ready.result_id,
    revision: ready.result_revision, notification_id: notification.id });
  return ready;
}
async function workflowRemote() {
  await client.createProjectSource(fixture.projectId, { source_id: fixture.sourceId, source_type: 'local_folder',
    encrypted_display_name: await encryptWithAesGcmCombined('Disposable Workflow folder', fixture.projectKey),
    encrypted_metadata: await encryptWithAesGcmCombined('{}', fixture.projectKey),
    capabilities: ['read', 'search', 'import', 'write_request'], status: 'offline', created_at: time(), updated_at: time() });
  const now = time();
  const source = { sourceId: fixture.sourceId, projectId: fixture.projectId, sourceType: 'local_folder', rootPath: physicalRoot,
    displayName: 'Disposable Workflow folder', cachePath: join(physicalRoot, '.fixture-cache'), status: 'offline', createdAt: now, updatedAt: now };
  bridge = runRemoteAccessBridge({ client, sourceSessionId: randomUUID(), bindings: [{ source, projectKey: fixture.projectKey, keyEpoch: 1 }],
    signal: abort.signal, taskCacheRoot: join(physicalRoot, '.task-cache') });
  void bridge.catch(() => {});
  await waitUntil(async () => (await client.listProjectSources(fixture.projectId, { personal: true })).some(row => row.source_id === fixture.sourceId && row.status === 'connected'),
    'physical_source_connection_required', 30_000);
  fileSocket = await client.openProjectAuthoringWebSocket();
  stopFileExecutor = registerCliProjectFileExecutor({ client, ws: fileSocket, chatId: fixture.chatId,
    chatKey: await client.getChatEncryptionKey(fixture.chatId, { personal: true }),
    requestApproval: () => false, requestReadApproval: () => false });
  await fileSocket.sendAsync('set_active_chat', { chat_id: fixture.chatId });
  fixture.workflowTitle = `Synthetic incident completion notice ${fixture.projectId.slice(0, 8)}`;
  fixture.workflowAttempted = true;
  const workflow = await client.createWorkflow({ title: fixture.workflowTitle, enabled: false, sourceChatId: fixture.chatId,
    graph: { version: 1, trigger_node_id: 'start', nodes: [{ id: 'start', type: 'manual_trigger', config: {} }, { id: 'end', type: 'end', config: {} }], edges: [{ from: 'start', to: 'end' }] } });
  fixture.workflowId = workflow.id;
  const binding = { project_id: fixture.projectId, source_id: fixture.sourceId, folder_path: '', file_path: 'synthetic_incident.workflow.yml' };
  await client.createProjectItem(fixture.projectId, { project_item_id: randomUUID(), item_type: 'workflow', target_id: workflow.id,
    target_id_encrypted: await encryptWithAesGcmCombined(workflow.id, fixture.projectKey),
    encrypted_display_name: await encryptWithAesGcmCombined(workflow.title, fixture.projectKey),
    encrypted_note: await encryptWithAesGcmCombined('', fixture.projectKey),
    encrypted_metadata: await encryptWithAesGcmCombined(JSON.stringify({ remote_workflow_file: binding, remote_file_status: 'pending' }), fixture.projectKey),
    created_at: time(), updated_at: time() }, { personal: true });
  // Remote writes use the ordinary existing apply-and-show source policy. The
  // earlier Focus slice already proved always-ask exact concrete save approval.
  await client.updateProjectSettings(fixture.projectId, { write_mode: 'apply_and_show', updated_at: time() }, { personal: true });
  const turn = await conversation(`For the existing disabled saved Workflow "${workflow.title}", we proved a useful improvement: its manual trigger currently ends silently. Add one send_notification node before end with title "Synthetic incident complete" and message "Synthetic incident evidence reviewed". Keep the Workflow disabled. This is a reusable Workflow update, not a Focus change. Discuss it briefly; do not execute or edit it from chat.`);
  const proposal = await recommend(turn, 'workflow', 'update', workflow.id);
  const job = await author(proposal, turn, binding);
  const ready = await persist(job);
  const physicalFile = join(physicalRoot, binding.file_path);
  requireValue(existsSync(physicalFile), 'actual_physical_yaml_required');
  const yaml = readFileSync(physicalFile, 'utf8');
  const portable = validateWorkflowFile(parseYaml(yaml));
  requireValue(portable.workflow.graph.nodes.some(node => node.type === 'send_notification'), 'authored_notification_node_required');
  const savedWorkflow = await client.getWorkflow(workflow.id, { personal: true });
  requireValue(savedWorkflow.current_version_id === ready.workflow_version_id && !savedWorkflow.enabled, 'future_saved_disabled_workflow_version_required');
  record('existing_workflow_engine_and_physical_yaml_saved', { workflow_id: workflow.id,
    workflow_version_id: savedWorkflow.current_version_id, yaml_sha256: digest(yaml), byte_count: Buffer.byteLength(yaml) });
  // A real external filesystem edit must survive the next authored version.
  const external = yaml + '\n# Disposable external edit: reconcile explicitly\n';
  writeFileSync(physicalFile, external);
  const detail = await client.getProject(fixture.projectId, { personal: true });
  const linked = detail.items.find(row => row.item_type === 'workflow');
  const metadata = JSON.parse(await decryptWithAesGcmCombined(linked.encrypted_metadata, fixture.projectKey));
  const conflictTurn = await conversation(`The existing disabled "${workflow.title}" Workflow needs another proven useful update: the send_notification message must now be "Synthetic incident evidence reviewed; case SYNTHETIC-CASE-52" to preserve the incident identifier. Keep trigger, delivery title, disabled state and other nodes. Discuss this required reusable Workflow improvement; do not execute or edit the graph from chat.`);
  const conflictProposal = await recommend(conflictTurn, 'workflow', 'update', workflow.id);
  const conflict = await author(conflictProposal, conflictTurn, metadata.remote_workflow_file);
  requireValue(conflict.status === 'conflict' && readFileSync(physicalFile, 'utf8') === external, 'external_file_conflict_must_preserve_bytes');
  const notifications = await client.listNotifications();
  requireValue(!notifications.events?.some(event => event.routing?.job_id === conflict.job_id), 'conflict_must_not_notify_ready');
  record('physical_file_version_conflict_preserved', { job_id: conflict.job_id, status: conflict.status, preserved_sha256: digest(external), ready_notification_absent: true });
}

let succeeded = false;
let failure;
try {
  await createProject();
  const createTurn = await conversation('For repeated synthetic Python service incidents in this Project, we explicitly want a reusable Project Debugging Playbook Focus. Our established old guide is: reproduce the issue, capture bounded logs, then compare configuration. Preserve these steps for repeated incidents. There is not yet a proven source-check step; do not invent one now. Discuss the useful reusable Focus briefly without creating files or tasks from chat.', true);
  const createProposal = await recommend(createTurn, 'focus', 'create');
  const created = await persist(await author(createProposal, createTurn));
  const old = await focusBody(created.result_id);
  requireValue(!old.markdown.includes('SOURCE-PROVENANCE-47'), 'old_guide_lacks_proven_step_required');
  const updateTurn = await conversation('We have now proved the missing source-check step for repeated incidents: SOURCE-PROVENANCE-47. Before diagnosing logs, compare the running module SHA against the approved source revision and record the exact source path; stop if they differ. The existing saved Project Debugging Playbook Focus lacks this proven step. Update that reusable Focus rather than creating another Focus. Keep its established reproduce/log/config steps. Discuss the improvement briefly without file writes or new tasks from chat.');
  const updateProposal = await recommend(updateTurn, 'focus', 'update', created.result_id);
  const updated = await persist(await author(updateProposal, updateTurn));
  const fresh = await focusBody(updated.result_id);
  requireValue(fresh.revision !== old.revision && fresh.head === old.head + 1 && fresh.markdown.includes('SOURCE-PROVENANCE-47'), 'saved_updated_focus_revision_required');
  const context = await loadActiveCliProjectContext(client, fixture.chatId, 'Apply the saved Project Debugging Playbook Focus to the next repeated incident and perform SOURCE-PROVENANCE-47.');
  const selected = context.project_focus_documents?.find(row => row.item_id === updated.result_id);
  requireValue(selected?.revision === fresh.revision && selected.document.includes('SOURCE-PROVENANCE-47'), 'fresh_followup_private_revision_required');
  const followup = await conversation('Apply the saved Project Debugging Playbook to a new synthetic incident. What exact proven source-check step comes before reading logs? Reply briefly with the SOURCE-PROVENANCE-47 source-check step only; do not write files or create tasks.');
  requireValue(followup.assistant.includes('SOURCE-PROVENANCE-47'), 'followup_proven_step_response_required');
  const accepted = await client.getActiveProjectFocus(fixture.chatId);
  requireValue(accepted?.specialist_focus_id === updated.result_id
    || accepted?.specialist_focus_id === `project-focus:${fixture.projectId}:${updated.result_id}`, 'followup_saved_specialist_activation_required');
  record('next_followup_loaded_updated_focus_revision', { project_item_id: updated.result_id, item_revision: fresh.revision, embed_revision: fresh.head });
  if (focusOnly) record('workflow_remote_skipped', { explicit_focus_only: true });
  else await workflowRemote();
  succeeded = true;
} catch (error) {
  failure = typeof error?.code === 'string' ? error.code : 'live_authoring_step_failed';
  record('failure', { code: failure });
} finally {
  stopFileExecutor?.();
  fileSocket?.close();
  abort.abort();
  if (bridge) await Promise.race([bridge.catch(() => {}), delay(10_000)]);
  const cleanup = [];
  // Recover an uncertain create response only by this exact synthetic title and
  // this harness's owned source chat; never sweep other account Workflows.
  if (fixture.workflowAttempted && !fixture.workflowId) try {
    fixture.workflowId = (await client.listWorkflows({ personal: true })).find(row => row.source_chat_id === fixture.chatId
      && row.title === fixture.workflowTitle)?.id ?? null;
  } catch { cleanup.push('workflow_lookup_cleanup_failed'); }
  if (fixture.workflowId) try { await client.deleteWorkflow(fixture.workflowId); cleanup.push('workflow'); } catch { cleanup.push('workflow_cleanup_failed'); }
  if (fixture.chatAttempted) try { await client.deleteChat(fixture.chatId, { personal: true }); cleanup.push('chat'); } catch { cleanup.push('chat_cleanup_failed'); }
  if (fixture.projectAttempted) try { await request(`/v1/projects/${fixture.projectId}?confirmation_project_id=${fixture.projectId}`, 'DELETE'); cleanup.push('project'); } catch { cleanup.push('project_cleanup_failed'); }
  rmSync(physicalRoot, { recursive: true, force: true });
  record('harness_owned_cleanup', { outcomes: cleanup, physical_directory_removed: true });
  if (cleanup.some(value => value.endsWith('_failed'))) succeeded = false;
  record('complete', { success: succeeded, ...(failure ? { failure_code: failure } : {}) });
}
process.exitCode = succeeded ? 0 : 1;
