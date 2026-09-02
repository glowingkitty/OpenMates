/**
 * Unit tests for OpenMates user task CLI client methods.
 *
 * Purpose: lock the shared encrypted /v1/user-tasks contract without a real API.
 * Security: uses a local HTTP server and synthetic session only; no account data
 * or task ciphertext leaves the process.
 * Run: node --test --experimental-strip-types --loader ./tests/loader.mjs tests/tasks.test.ts
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";

import { OpenMatesClient, type UserTaskCreateInput } from "../src/client.ts";
import { formatEmbedPreviewLines } from "../src/embedRenderers.ts";
import {
  decryptUserTask,
  findTask,
  taskEditLookupScope,
  taskLookupScopes,
  type DecryptedUserTask,
  workflowProjectionDeleteGuidance,
} from "../src/tasksCli.ts";
import type { OpenMatesSession } from "../src/storage.ts";

type SeenRequest = { method: string | undefined; url: string | undefined; body: unknown };

function testSession(): OpenMatesSession {
  return {
    apiUrl: "http://127.0.0.1",
    sessionId: "session-1",
    wsToken: "x",
    cookies: { auth_refresh_token: "x" },
    masterKeyExportedB64: Buffer.alloc(32).toString("base64"),
    hashedEmail: "hashed-email",
    userEmailSalt: "salt",
    createdAt: Date.now(),
    authorizerDeviceName: "test-device",
    autoLogoutMinutes: null,
  };
}

function encryptedTaskInput(): UserTaskCreateInput {
  return {
    task_id: "task-1",
    encrypted_task_key: "cipher-key",
    encrypted_title: "cipher-title",
    encrypted_description: "cipher-description",
    encrypted_tags: "cipher-tags",
    status: "todo",
    assignee_type: "user",
    version: 1,
    linked_project_ids: ["project-1"],
    primary_chat_id: "chat-1",
    created_at: 100,
    updated_at: 100,
  };
}

async function withServer(
  handler: (request: IncomingMessage, body: unknown) => unknown,
  run: (apiUrl: string, seen: SeenRequest[]) => Promise<void>,
): Promise<void> {
  const seen: SeenRequest[] = [];
  const server = createServer((request: IncomingMessage, response: ServerResponse) => {
    let raw = "";
    request.setEncoding("utf8");
    request.on("data", (chunk) => { raw += chunk; });
    request.on("end", () => {
      const body = raw ? JSON.parse(raw) : undefined;
      seen.push({ method: request.method, url: request.url, body });
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify(handler(request, body)));
    });
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  try {
    await run(`http://127.0.0.1:${address.port}`, seen);
  } finally {
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
}

describe("OpenMatesClient user tasks", () => {
  // contract-test: direct surface=cli assertions=tasks.content.client-encrypted,tasks.lifecycle.visible,tasks.project-links.encrypted,tasks.surface.semantic-parity
  it("lists, creates, updates, and starts encrypted user tasks", async () => {
    const task = encryptedTaskInput();
    await withServer(
      (request, body) => {
        if (request.method === "GET") return { tasks: [task] };
        return { task: { ...task, ...(body as Record<string, unknown>) } };
      },
      async (apiUrl, seen) => {
        const client = new OpenMatesClient({ apiUrl, session: testSession() });
        assert.equal((await client.listUserTasks({ status: "todo", chatId: "chat-1", projectId: "project-1", limit: 1000 }))[0]?.task_id, "task-1");
        assert.equal((await client.createUserTask(task)).encrypted_title, "cipher-title");
        assert.equal((await client.updateUserTask("task-1", { status: "done", version: 1 })).status, "done");
        assert.equal((await client.updateUserTask("team-task", { status: "done", version: 1 }, { teamId: "team-1" })).status, "done");
        const activeTeamClient = new OpenMatesClient({ apiUrl, session: { ...testSession(), activeTeamId: "team-active" } });
        assert.equal((await activeTeamClient.updateUserTask("active-team-task", { status: "done", version: 1 })).status, "done");
        assert.equal((await activeTeamClient.updateUserTask("personal-task", { status: "done", version: 1 }, { personal: true })).status, "done");
        assert.equal((await client.startUserTaskWithAI("task-1", {
          version: 2,
          plaintext_title: "Draft launch plan",
          plaintext_description: "Use project context",
        })).task_id, "task-1");

        assert.deepEqual(seen.map((request) => [request.method, request.url]), [
          ["GET", "/v1/user-tasks?status=todo&chat_id=chat-1&project_id=project-1&limit=1000"],
          ["POST", "/v1/user-tasks"],
          ["PATCH", "/v1/user-tasks/task-1"],
          ["PATCH", "/v1/user-tasks/team-task?team_id=team-1"],
          ["PATCH", "/v1/user-tasks/active-team-task?team_id=team-active"],
          ["PATCH", "/v1/user-tasks/personal-task"],
          ["POST", "/v1/user-tasks/task-1/start-ai"],
        ]);
        assert.deepEqual(seen[1]?.body, task);
        assert.deepEqual(seen[2]?.body, { status: "done", version: 1 });
        assert.deepEqual(seen[3]?.body, { status: "done", version: 1 });
        assert.deepEqual(seen[4]?.body, { status: "done", version: 1 });
        assert.deepEqual(seen[5]?.body, { status: "done", version: 1 });
        assert.deepEqual(seen[6]?.body, {
          version: 2,
          plaintext_title: "Draft launch plan",
          plaintext_description: "Use project context",
        });
      },
    );
  });

  // contract-test: direct surface=cli assertions=tasks.surface.semantic-parity
  it("rejects ambiguous short task IDs", () => {
    const tasks = [
      { taskId: "task-1", shortId: "TASK-1234" },
      { taskId: "task-2", shortId: "TASK-1234" },
    ] as DecryptedUserTask[];

    assert.throws(() => findTask(tasks, "TASK-1234"), /ambiguous/);
    assert.equal(findTask(tasks, "task-2").taskId, "task-2");
  });

  // contract-test: direct surface=cli assertions=tasks.lifecycle.visible,tasks.surface.semantic-parity
  it("resolves task IDs across statuses without filtering on edited values", () => {
    const scopes = taskLookupScopes({ status: "todo", priority: 2, teamId: null, personal: true });
    assert.deepEqual(scopes.map((scope) => scope.status), ["backlog", "todo", "in_progress", "blocked", "done"]);
    assert.ok(scopes.every((scope) => scope.priority === 2 && scope.personal === true));

    assert.deepEqual(taskEditLookupScope({
      status: "done",
      chatId: "new-chat",
      projectId: "new-project",
      planId: "new-plan",
      labelHashes: ["new-label"],
      priority: 4,
      teamId: "team-1",
      personal: false,
    }), { teamId: "team-1", personal: false });
  });

  // contract-test: direct surface=cli assertions=tasks.workflow-projections.read-only,tasks.surface.semantic-parity
  it("renders workflow task projections without decrypting task ciphertext", async () => {
    const task = await decryptUserTask({
      task_id: "workflow-schedule:trigger-1:1000",
      source: "workflow_run",
      projection_kind: "next_run",
      workflow_id: "workflow-1",
      workflow_run_id: null,
      trigger_id: "trigger-1",
      title: "Morning rain - 1970-01-01 00:16 UTC",
      status: "todo",
      run_status: "planned",
      due_at: 1000,
      position: 1000,
      can_cancel: false,
      can_delete: true,
      read_only: true,
      encrypted_title: "",
      assignee_type: "user",
    }, Buffer.alloc(32));

    assert.equal(task.source, "workflow_run");
    assert.equal(task.projectionKind, "next_run");
    assert.equal(task.workflowId, "workflow-1");
    assert.equal(task.workflowRunId, null);
    assert.equal(task.triggerId, "trigger-1");
    assert.equal(task.title, "Morning rain - 1970-01-01 00:16 UTC");
    assert.equal(task.status, "todo");
    assert.equal(task.queueState, "planned");
    assert.equal(task.readOnly, true);
    assert.equal(task.canCancel, false);
    assert.equal(task.canDelete, true);
    assert.match(task.shortId, /^WF-/);
  });

  // contract-test: direct surface=cli assertions=tasks.workflow-projections.read-only,tasks.surface.semantic-parity
  it("gives workflow projection deletion guidance", () => {
    const task = {
      shortId: "WF-123456",
      projectionKind: "next_run",
      workflowId: "workflow-1",
      canDelete: true,
    } as DecryptedUserTask;
    const guidance = workflowProjectionDeleteGuidance(task);

    assert.match(guidance, /openmates tasks delete WF-123456 --confirm/);
    assert.match(guidance, /openmates workflows disable workflow-1/);
  });

  // contract-test: supporting surface=cli assertions=tasks.surface.semantic-parity
  it("formats task child embeds for CLI output", () => {
    const lines = formatEmbedPreviewLines({
      embedId: "task-embed-12345678",
      type: "tasks-task",
      status: "finished",
      content: {
        type: "task",
        title: "Draft launch announcement",
        short_id: "TASK-42",
        status: "todo",
        assignee: "openmates",
      },
    });

    assert.equal(lines[0], "┌─ ✓ task · TASK-42 · Draft launch announcement");
    assert.deepEqual(lines.slice(1, 4), [
      "│  Status: todo",
      "│  Assignee: openmates",
      "└─ openmates tasks show TASK-42",
    ]);
  });
});
