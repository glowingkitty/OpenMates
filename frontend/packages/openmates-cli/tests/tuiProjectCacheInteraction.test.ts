// contract-test-file: infrastructure
/** Controller-level cache and route behavior with an isolated encrypted snapshot. */
import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { OpenMatesClient, WorkflowDetail } from "../src/client.js";
import type { TuiProject } from "../src/tuiProjectsWorkspace.js";
import { encryptWithAesGcmCombined } from "../src/crypto.js";
import { saveSession, clearSession, type OpenMatesSession } from "../src/storage.js";
import { writeCachedTuiWorkspace, readCachedTuiWorkspace, invalidateCachedTuiWorkspace } from "../src/tuiCachedWorkspaces.js";
import { createInitialTuiState } from "../src/tuiRenderer.js";
import { handleWorkspaceCommand, handleWorkspaceKey, type WorkspaceContext } from "../src/tuiWorkspaceController.js";
import type { DecryptedUserTask } from '../src/tasksCli.js';

const stateDir = mkdtempSync(join(tmpdir(), "openmates-tui-project-controller-"));
const previousStateDir = process.env.OPENMATES_STATE_DIR;
process.env.OPENMATES_STATE_DIR = stateDir;
const key = new Uint8Array(32).fill(13);
const session = {
  apiUrl: "https://api.example.test", sessionId: "project-controller", wsToken: null, cookies: {},
  masterKeyExportedB64: Buffer.from(key).toString("base64"), hashedEmail: "project-controller-account",
  userEmailSalt: "salt", createdAt: Date.now(), authorizerDeviceName: null,
  autoLogoutMinutes: null, activeTeamId: null,
} as OpenMatesSession;
before(() => saveSession(session, {replace: true}));
after(() => {
  try { clearSession(); } finally {
    rmSync(stateDir, {recursive: true, force: true});
    if (previousStateDir === undefined) delete process.env.OPENMATES_STATE_DIR;
    else process.env.OPENMATES_STATE_DIR = previousStateDir;
  }
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return {promise, resolve};
}
const tick = () => new Promise<void>(done => setImmediate(done));
async function waitUntil(condition: () => boolean): Promise<void> {
  for (let attempt = 0; attempt < 50 && !condition(); attempt++)
    await new Promise<void>(done => setTimeout(done, 10));
  assert.ok(condition(), "expected background Project refresh to publish");
}
const project = (name = "Saved Project"): TuiProject => ({
  id: "project-one", slug: "saved-project", name, description: "Saved encrypted snapshot", readme: "",
  icon: "folder", color: "#4488cc", pinned: false, archived: false, itemCount: 1,
  files: [{id: "docs", name: "Docs", path: "docs", kind: "folder"}],
  folders: [{id: "docs", name: "Docs"}], items: [], sources: [], projectKey: key, teamId: null, sourceRecords: [],
});
function projectClient(overrides: Record<string, unknown> = {}): OpenMatesClient {
  return {
    apiUrl: session.apiUrl, hasSession: () => true, getSession: () => session,
    getActiveTeamId: () => null, getMasterKeyBytes: () => key, decryptProjectKey: async () => key,
    listProjectItems: async () => ({folders: [], items: []}), listProjectSources: async () => [],
    listUserTasks: async () => [],
    ...overrides,
  } as unknown as OpenMatesClient;
}
function context(client: OpenMatesClient): WorkspaceContext {
  const state = createInitialTuiState(); state.signedIn = true;
  return {state, client, terminal: {width: 120} as never, render: () => {}, command: async () => {}, send: async () => {}};
}

// contract-test: supporting surface=cli assertions=tasks.surface.semantic-parity
test('a confirmed task deletion updates every linked Project snapshot',async()=>{
  const client=projectClient({deleteUserTask:async()=>({deleted:true})});
  const task={taskId:'task-delete',version:1,linkedProjectIds:['project-one','project-two']} as DecryptedUserTask;
  const unrelated={taskId:'keep-task'} as DecryptedUserTask;
  for(const name of ['tasks:list','project:project-one:tasks','project:project-two:tasks'])await writeCachedTuiWorkspace(client,name,[task,unrelated]);
  const ctx=context(client);ctx.state.workspace='tasks';ctx.state.screen='task';ctx.state.tasks=[task,unrelated];ctx.state.activeTask=task;
  await handleWorkspaceCommand(ctx,'/task-delete');ctx.state.form!.fields.find(field=>field.name==='confirm')!.value='DELETE';
  await handleWorkspaceKey(ctx,'\x13',{name:'s',ctrl:true});
  for(const name of ['tasks:list','project:project-one:tasks','project:project-two:tasks'])assert.deepEqual((await readCachedTuiWorkspace<DecryptedUserTask[]>(client,name))?.map(task=>task.taskId),['keep-task']);
});

// contract-test: supporting surface=cli assertions=workflows.surface.semantic-parity
test('workflow toggle updates its carousel and saved list immediately',async()=>{
  const workflow={id:'toggle-workflow',title:'Toggle',enabled:true} as WorkflowDetail;
  const client=projectClient({updateWorkflow:async()=>({...workflow,enabled:false})});
  const ctx=context(client);ctx.state.workspace='workflows';ctx.state.screen='workflow';ctx.state.activeWorkflow=workflow;ctx.state.workflows=[workflow];
  await writeCachedTuiWorkspace(client,'workflows:list',[workflow]);await handleWorkspaceCommand(ctx,'/workflow-toggle');
  assert.equal(ctx.state.workflows[0].enabled,false);
  assert.equal((await readCachedTuiWorkspace<WorkflowDetail[]>(client,'workflows:list'))?.[0].enabled,false);
});
async function encryptedRecord(name: string) {
  return {project_id: "project-one", encrypted_name: await encryptWithAesGcmCombined(name, key),
    encrypted_slug: await encryptWithAesGcmCombined("saved-project", key),
    encrypted_description: await encryptWithAesGcmCombined("Fresh description", key)};
}

// contract-test: direct surface=cli assertions=projects.surface.semantic-parity
test("a Files shortcut during a cold Project load does not discard its detail response", async () => {
  const pending = deferred<{project: Awaited<ReturnType<typeof encryptedRecord>>}>();
  const requested = deferred<void>();
  const encryptedFolderName = await encryptWithAesGcmCombined("Docs", key);
  const client = projectClient({
    getProject: () => { requested.resolve(); return pending.promise; },
    listProjectItems: async () => ({folders: [{folder_id: "docs", encrypted_name: encryptedFolderName}], items: []}),
  });
  await invalidateCachedTuiWorkspace(client, "project:project-one:detail");
  const ctx = context(client);
  const opening = handleWorkspaceCommand(ctx, "/project project-one");
  await requested.promise;
  assert.equal(ctx.state.screen, "project");
  assert.equal(ctx.state.activeProject, null);
  const route = ctx.state.routeVersion;
  assert.equal(await handleWorkspaceKey(ctx, "2", {name: "2"}), true);
  assert.equal(ctx.state.routeVersion, route, "loading tab input must preserve the pending Project route");
  assert.equal(ctx.state.projectTab, "overview");
  pending.resolve({project: await encryptedRecord("Fresh Project")});
  await opening;
  assert.equal(ctx.state.activeProject?.name, "Fresh Project");
  assert.equal(ctx.state.status, null);
  assert.equal(ctx.state.projectTab, "overview");
  assert.equal(await handleWorkspaceKey(ctx, "2", {name: "2"}), true);
  assert.equal(ctx.state.projectTab, "files");
  assert.deepEqual(ctx.state.projectFiles.map(file => file.name), ["Docs"]);
});

// contract-test: direct surface=cli assertions=projects.surface.semantic-parity
test("a saved encrypted Project snapshot opens immediately while the network is offline", async () => {
  const pending = deferred<never>();
  const client = projectClient({getProject: () => pending.promise});
  assert.equal(await writeCachedTuiWorkspace(client, "project:project-one:detail", project()), true);
  const ctx = context(client);
  await handleWorkspaceCommand(ctx, "/project project-one");
  assert.equal(ctx.state.screen, "project");
  assert.equal(ctx.state.activeProject?.name, "Saved Project");
  assert.deepEqual(ctx.state.projectFiles.map(file => file.name), ["Docs"]);
  pending.resolve(Promise.reject(new Error("offline")) as never);
  await tick();
  assert.match(ctx.state.status ?? "", /Showing saved Project.*Offline/);
  assert.equal(ctx.state.activeProject?.name, "Saved Project");
});

// contract-test: direct surface=cli assertions=projects.surface.semantic-parity
test("leaving a cached Project route fences a late background detail response", async () => {
  const pending = deferred<{project: Awaited<ReturnType<typeof encryptedRecord>>}>();
  const client = projectClient({getProject: () => pending.promise});
  await writeCachedTuiWorkspace(client, "project:project-one:detail", project());
  const ctx = context(client);
  await handleWorkspaceCommand(ctx, "/project project-one");
  assert.equal(ctx.state.activeProject?.name, "Saved Project");
  await handleWorkspaceCommand(ctx, "/chats");
  pending.resolve({project: await encryptedRecord("Late Project")});
  await tick();
  assert.equal(ctx.state.screen, "chats");
  assert.notEqual(ctx.state.activeProject?.name, "Late Project");
});

// contract-test: direct surface=cli assertions=projects.surface.semantic-parity
test("a background detail refresh preserves the chosen Files or Tasks tab and current draft", async () => {
  for (const tab of ["files", "tasks"] as const) {
    const pending = deferred<{project: Awaited<ReturnType<typeof encryptedRecord>>}>();
    const client = projectClient({getProject: () => pending.promise});
    await writeCachedTuiWorkspace(client, "project:project-one:detail", project());
    const ctx = context(client);
    await handleWorkspaceCommand(ctx, "/project project-one");
    ctx.state.projectTab = tab;
    ctx.state.projectFolderId = tab === "files" ? "docs" : null;
    ctx.state.filter = "keep search";
    ctx.state.input = "Keep this draft";
    pending.resolve({project: await encryptedRecord(`Fresh ${tab}`)});
    await waitUntil(() => ctx.state.activeProject?.name === `Fresh ${tab}`);
    assert.equal(ctx.state.activeProject?.name, `Fresh ${tab}`);
    assert.equal(ctx.state.projectTab, tab);
    assert.equal(ctx.state.projectFolderId, tab === "files" ? "docs" : null);
    assert.equal(ctx.state.filter, "keep search");
    assert.equal(ctx.state.input, "Keep this draft");
  }
});

// contract-test: direct surface=cli assertions=workflows.surface.semantic-parity
test("late Workflow capabilities never replace an edited fallback form", async () => {
  const capabilities = deferred<[]>();
  const client = {listWorkflowCapabilities: () => capabilities.promise} as unknown as OpenMatesClient;
  const ctx = context(client);
  const workflow = {id: "workflow-one", title: "Plan", status: "active", enabled: true,
    current_version_id: "v1", created_at: 1, updated_at: 1,
    graph: {version: 1, trigger_node_id: "start", nodes: [{id: "start", type: "manual_trigger", title: "Start"}], edges: []},
  } as WorkflowDetail;
  ctx.state.workspace = "workflows"; ctx.state.screen = "workflow";
  ctx.state.workflowTab = "graph"; ctx.state.activeWorkflow = workflow;
  const opening = handleWorkspaceCommand(ctx, "/workflow-edit");
  assert.ok(ctx.state.form);
  const form = ctx.state.form;
  const title = form.fields.find(field => field.name === "title")!;
  title.value = "Edited while loading";
  capabilities.resolve([]);
  await opening;
  assert.equal(ctx.state.form, form);
  assert.equal(ctx.state.form?.fields.find(field => field.name === "title")?.value, "Edited while loading");
});
