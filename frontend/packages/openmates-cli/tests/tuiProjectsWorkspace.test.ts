import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import type { OpenMatesClient, ProjectRecord } from "../src/client.ts";
import { decryptBytesWithAesGcm, encryptWithAesGcmCombined } from "../src/crypto.ts";
import { cells } from "../src/tuiText.ts";
import {
  buildProjectForm, filteredProjectFiles, loadTuiProject, loadTuiProjectFiles, loadTuiProjects,
  parentTuiProjectFolderId, readTuiProjectFile, renderProjectDetail, renderProjectIdentity,
  renderProjectList, renderProjectTabs, submitProjectForm,
} from "../src/tuiProjectsWorkspace.ts";

const key = new Uint8Array(32).fill(9);
const id = "11111111-1111-4111-8111-111111111111";

async function encrypted(value: string): Promise<string> {
  return encryptWithAesGcmCombined(value, key);
}

async function record(): Promise<ProjectRecord> {
  return {
    project_id: id,
    encrypted_name: await encrypted("Demo\u001b[31m Project"),
    encrypted_slug: await encrypted("demo-project"),
    encrypted_description: await encrypted("Example workspace"),
  };
}

describe("TUI Project workspace", () => {
  // contract-test: supporting surface=cli assertions=projects.lifecycle.encrypted-crud,projects.links.openmates-only-encrypted,projects.files.no-server-decryption-authority
  it("decrypts metadata and linked files without requesting or activating remote access", async () => {
    const projectRecord = await record();
    let remoteCalls = 0;
    let storedReads = 0;
    const client = {
      getActiveTeamId: () => null,
      listProjects: async () => [projectRecord],
      getProject: async () => ({ project: projectRecord, folders: [], items: [] }),
      decryptProjectKey: async () => key,
      listProjectItems: async () => ({
        folders: [{ folder_id: "folder-1", encrypted_name: await encrypted("Docs") }],
        items: [{ project_item_id: "item-1", item_type: "embed", target_id_encrypted: await encrypted("embed-1"),
          encrypted_display_name: await encrypted("notes.md"), encrypted_metadata: await encrypted(JSON.stringify({ path: "notes.md" })) }],
      }),
      listProjectSources: async () => [{ source_id: "source-1", source_type: "remote_folder", encrypted_display_name: await encrypted("Laptop"), encrypted_metadata: await encrypted("{}"), status: "connected" }],
      createProjectRemoteAccessRequest: async () => { remoteCalls++; throw new Error("unexpected remote access"); },
      readEncryptedProjectFile: async () => { storedReads++; return { content: { code: "# Notes\n" } }; },
    } as unknown as OpenMatesClient;
    const listed = await loadTuiProjects(client);
    assert.equal(listed[0]?.name, "Demo\u001b[31m Project");
    const project = await loadTuiProject(client, id);
    assert.equal(project.files.find((file) => file.kind === "stored")?.path, "notes.md");
    assert.equal(project.sources[0]?.name, "Laptop");
    assert.equal(remoteCalls, 0);
    assert.equal(storedReads, 0);
    const file = project.files.find((entry) => entry.kind === "stored");
    assert.ok(file);
    assert.equal(await readTuiProjectFile(client, project, file), "# Notes\n");
    assert.equal(storedReads, 1);
    assert.ok(renderProjectList([project], { width: 80, selectedId: id })[0]?.startsWith(">"));
    assert.ok(!renderProjectDetail(project, { width: 80, tab: "overview" })[0]?.includes("\u001b"));
  });

  // contract-test: supporting surface=cli assertions=projects.keys.client-wrapped,projects.files.write-policy-setup,projects.lifecycle.encrypted-crud
  it("rejects unlinked stored files and validates the embedded create form", async () => {
    const project = {
      id, projectKey: key, teamId: null, files: [], sourceRecords: [],
    } as unknown as Awaited<ReturnType<typeof loadTuiProject>>;
    const client = {
      getActiveTeamId: () => null,
      projectWrappingKey: async () => ({ key, teamId: null }),
      createProject: async (payload: ProjectRecord) => ({ project: payload }),
      decryptProjectKey: async (value: ProjectRecord) => {
        assert.ok(value.encrypted_project_key);
        const unwrapped = await decryptBytesWithAesGcm(value.encrypted_project_key, key);
        assert.ok(unwrapped);
        return unwrapped;
      },
    } as unknown as OpenMatesClient;
    await assert.rejects(readTuiProjectFile(client, project, { id: "other", name: "x", path: "x", kind: "stored", embedId: "x" }), /not linked/);
    const form = buildProjectForm();
    await assert.rejects(submitProjectForm(client, form), /name is required/);
    form.fields[0]!.value = "New Project";
    const created = await submitProjectForm(client, form);
    assert.equal(created.name, "New Project");
    assert.equal(created.slug, "new-project");
  });

  // contract-test: supporting surface=cli assertions=projects.links.openmates-only-encrypted,projects.files.no-server-decryption-authority
  it("navigates hashed local folders without touching a connected remote source", async () => {
    const projectRecord = await record();
    const rootHash = createHash("sha256").update("folder-root").digest("hex");
    const nestedHash = createHash("sha256").update("folder-nested").digest("hex");
    let remoteCalls = 0;
    const client = {
      getActiveTeamId: () => null,
      getProject: async () => ({ project: projectRecord, folders: [], items: [] }),
      decryptProjectKey: async () => key,
      listProjectItems: async () => ({
        folders: [
          { folder_id: "folder-root", encrypted_name: await encrypted("Docs"), hashed_parent_folder_id: null },
          { folder_id: "folder-nested", encrypted_name: await encrypted("Guides"), hashed_parent_folder_id: rootHash },
        ],
        items: [
          { project_item_id: "root-item", item_type: "embed", target_id_encrypted: await encrypted("embed-root"),
            encrypted_display_name: await encrypted("root.md"), encrypted_metadata: await encrypted("{}") },
          { project_item_id: "nested-item", item_type: "embed", hashed_folder_id: nestedHash,
            target_id_encrypted: await encrypted("embed-nested"), encrypted_display_name: await encrypted("setup.md"),
            encrypted_metadata: await encrypted(JSON.stringify({ path: "setup.md" })) },
        ],
      }),
      listProjectSources: async () => [{ source_id: "source-1", source_type: "remote_folder", encrypted_display_name: await encrypted("Laptop"), encrypted_metadata: await encrypted("{}"), status: "connected" }],
      createProjectRemoteAccessRequest: async () => { remoteCalls++; throw new Error("unexpected remote access"); },
    } as unknown as OpenMatesClient;
    const project = await loadTuiProject(client, id);
    const rootFiles = await loadTuiProjectFiles(client, project);
    assert.deepEqual(rootFiles.map((file) => file.name), ["Docs", "root.md"]);
    assert.equal(rootFiles[0]?.path, "folder-root");
    assert.equal(rootFiles[0]?.sourceId, undefined);
    const docsFiles = await loadTuiProjectFiles(client, project, { folderId: "folder-root" });
    assert.deepEqual(docsFiles.map((file) => file.name), ["Guides"]);
    const guidesFiles = await loadTuiProjectFiles(client, project, { folderId: "folder-nested" });
    assert.deepEqual(guidesFiles.map((file) => file.name), ["setup.md"]);
    assert.equal(parentTuiProjectFolderId(project, "folder-nested"), "folder-root");
    assert.equal(parentTuiProjectFolderId(project, "folder-root"), null);
    assert.deepEqual(filteredProjectFiles(guidesFiles, "SETUP").map((file) => file.id), ["nested-item"]);
    assert.ok(renderProjectDetail(project, { width: 80, tab: "files", files: guidesFiles, folderId: "folder-nested" }).some((line) => line.includes("Files / Docs / Guides")));
    await assert.rejects(loadTuiProjectFiles(client, project, { path: "folder-root" }), /Select a Project source/);
    await assert.rejects(loadTuiProjectFiles(client, project, { sourceId: "source-1", path: "folder-root" }), /local folder ID/);
    assert.equal(remoteCalls, 0);
  });

  // contract-test: supporting surface=cli assertions=projects.surface.semantic-parity,projects.files.connected-embed-previews
  it("renders vertical Project cards and a distinct selected tab and file panel", () => {
    const project = {
      id: "project-1", slug: "project-1", name: "Design Project", description: "Plan the next release.",
      icon: "folder", color: "blue", pinned: false, archived: false, itemCount: 3, createdAt: 1_700_000_000,
      readme: "# Overview\nGoals and next steps.", files: [], folders: [], items: [], sources: [],
      projectKey: key, teamId: null, sourceRecords: [],
    } as Awaited<ReturnType<typeof loadTuiProject>>;
    const second = { ...project, id: "project-2", name: "Research Project", description: "Collect references." };
    const home = renderProjectList([project, second], { width: 48, selectedId: project.id });
    assert.equal(home.filter((line) => line.includes("PROJECT-")).length, 2);
    assert.ok(home[0]?.startsWith("> "));
    assert.ok(home.findIndex((line) => line.includes("Research Project")) > home.findIndex((line) => line.includes("Design Project")));
    assert.ok(home.every((line) => line.length <= 48));
    const identity = renderProjectIdentity(project, { width: 48 });
    assert.ok(identity.some((line) => line.includes("PROJECT / PRODUCTIVITY")));
    assert.ok(identity.some((line) => line.includes("3 items")));
    assert.deepEqual(renderProjectTabs("files", 48).filter((line) => line.includes("FILES" )).length, 1);
    const overview = renderProjectDetail(project, { width: 48, tab: "overview" });
    assert.ok(overview.some((line) => line.includes("[OVERVIEW]")));
    assert.ok(overview.some((line) => line.includes("Goals and next steps.")));
    const files = renderProjectDetail(project, { width: 48, tab: "files", files: [
      { id: "folder-1", name: "Research", path: "folder-1", kind: "folder" },
      { id: "file-1", name: "notes.md", path: "notes.md", kind: "stored", embedId: "embed-1" },
    ], selectedFileId: "file-1" });
    assert.ok(files.some((line) => line.includes("[FILES]")));
    assert.ok(files.some((line) => line.includes("1 folder, 1 file")));
    assert.ok(files.some((line) => line.includes("> [embed] notes.md")));
    assert.ok(files.every((line) => line.length <= 48));
    assert.ok(renderProjectDetail(project, { width: 30, tab: "files", files: [] }).every((line) => line.length <= 30));
    const wide = { ...project, name: "研究🧭 Project", description: "多语言 work 🌍 and planning" };
    const wideHome = renderProjectList([wide], { width: 112, selectedId: wide.id });
    assert.equal(cells(wideHome[0]!), 88);
    assert.ok(wideHome.every((line) => cells(line) <= 88));
    const wideDetail = renderProjectDetail(wide, { width: 112, tab: "overview" });
    assert.equal(cells(wideDetail[0]!), 112);
    assert.ok(wideDetail.every((line) => cells(line) <= 112));
    assert.ok(renderProjectDetail(wide, { width: 30, tab: "files", files: [] }).every((line) => cells(line) <= 30));
  });
});
