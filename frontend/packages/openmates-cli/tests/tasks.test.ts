/**
 * Unit tests for OpenMates user task CLI client methods.
 *
 * Purpose: lock the shared encrypted /v1/user-tasks Specification behavior without a real API.
 * Security: uses a local HTTP server and synthetic session only; no account data
 * or task ciphertext leaves the process.
 * Run: node --test --experimental-strip-types --loader ./tests/loader.mjs tests/tasks.test.ts
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { createHmac, hkdfSync } from "node:crypto";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";

import {
  OpenMatesClient,
  type UserTaskActivityCreateInput,
  type UserTaskActivityRecord,
  type UserTaskCreateInput,
} from "../src/client.ts";
import { formatEmbedPreviewLines } from "../src/embedRenderers.ts";
import {
  buildBlockUserTaskInput,
  buildCreateTaskActivityInput,
  buildCreateUserTaskInput,
  buildUpdateUserTaskInput,
  decryptTaskActivityEntry,
  decryptUserTask,
  externalChatLookupHash,
  findTask,
  normalizeBlockedReasonCode,
  parseExternalChatRef,
  renderTaskActivityList,
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
  // contract-test: direct surface=cli assertions=tasks.activity.client-encrypted,tasks.activity.context-attribution,tasks.activity.deletion-tombstone,tasks.surface.semantic-parity
  it("encrypts, transports, decrypts, and tombstones Task Activity", async () => {
    const masterKey = Buffer.alloc(32, 11);
    const encryptedTask = await buildCreateUserTaskInput(masterKey, { title: "Activity task" });
    const task = await decryptUserTask(encryptedTask, masterKey);
    const activityInput = await buildCreateTaskActivityInput(task, masterKey, {
      entryId: "activity-1",
      message: "First line\nSecond line",
      createdAt: 100,
    });
    assert.doesNotMatch(JSON.stringify(activityInput), /First line|Second line/);
    assert.equal("encrypted_entry_key" in activityInput, false);
    assert.ok(activityInput.encrypted_message);

    const stored: UserTaskActivityRecord = {
      ...activityInput,
      task_id: task.taskId,
      kind: "comment",
      actor_type: "user",
      actor_hash: "author-hash",
      event_type: "comment_added",
      source_surface: "cli",
    };
    const decrypted = await decryptTaskActivityEntry(task, masterKey, stored);
    assert.equal(decrypted.message, "First line\nSecond line");
    await assert.rejects(
      decryptTaskActivityEntry(task, masterKey, { ...stored, entry_id: "activity-moved" }),
      /Failed to decrypt Task Activity entry/,
    );

    const tombstone: UserTaskActivityRecord = {
      entry_id: "activity-1",
      task_id: task.taskId,
      kind: "tombstone",
      actor_type: "user",
      actor_hash: "author-hash",
      author_hash: "author-hash",
      event_type: "comment_deleted",
      source_surface: "cli",
      created_at: 100,
      deleted_at: 101,
      deleted_by_hash: "deleter-hash",
      encrypted_message: null,
      encrypted_embed_key_material: null,
      embed_refs: [],
    };
    assert.match(renderTaskActivityList([await decryptTaskActivityEntry(task, masterKey, tombstone)]), /deleted/i);

    await withServer(
      (request, body) => request.method === "GET"
        ? { entries: [stored] }
        : request.method === "POST"
          ? { entry: { ...stored, ...(body as UserTaskActivityCreateInput) } }
          : { entry: tombstone },
      async (apiUrl, seen) => {
        const client = new OpenMatesClient({ apiUrl, session: testSession() });
        await client.listUserTaskActivity(task.taskId, { teamId: "team-1" });
        await client.createUserTaskActivity(task.taskId, activityInput, { teamId: "team-1" });
        await client.deleteUserTaskActivity(task.taskId, "activity-1", { teamId: "team-1" });

        assert.deepEqual(seen.map((request) => [request.method, request.url]), [
          ["GET", `/v1/user-tasks/${task.taskId}/activity?team_id=team-1`],
          ["POST", `/v1/user-tasks/${task.taskId}/activity?team_id=team-1`],
          ["DELETE", `/v1/user-tasks/${task.taskId}/activity/activity-1?team_id=team-1`],
        ]);
        assert.deepEqual(seen[1]?.body, activityInput);
      },
    );
  });

  // contract-test: direct surface=cli assertions=tasks.assignment.identity-separated,tasks.surface.semantic-parity
  it("separates assignment type from allowlisted identity", async () => {
    const masterKey = Buffer.alloc(32, 3);
    const external = await buildCreateUserTaskInput(masterKey, { title: "External work", assign: "external-ai" });
    const native = await buildCreateUserTaskInput(masterKey, { title: "Native work", assign: "openmates" });
    const human = await buildCreateUserTaskInput(masterKey, { title: "Human work", assign: "user" });

    assert.deepEqual([external.assignee_type, external.assignee_identity], ["external_ai", "opencode"]);
    assert.deepEqual([native.assignee_type, native.assignee_identity], ["openmates", "openmates"]);
    assert.deepEqual([human.assignee_type, human.assignee_identity], ["user", null]);
  });

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

  // contract-test: direct surface=cli assertions=tasks.content.client-encrypted,tasks.external-chat.encrypted-context,tasks.surface.semantic-parity
  it("encrypts and filters an allowlisted external chat locally", async () => {
    const masterKey = Buffer.alloc(32, 7);
    const context = parseExternalChatRef("opencode:ses_external_123");
    const lookupHash = externalChatLookupHash(masterKey, context);
    const input = await buildCreateUserTaskInput(masterKey, {
      title: "Implement task bridge",
      externalChat: { ...context, title: "OpenCode task bridge" },
    });

    assert.deepEqual(context, { provider: "opencode", id: "ses_external_123" });
    assert.match(lookupHash, /^[0-9a-f]{64}$/);
    assert.equal(input.primary_chat_id, null);
    assert.equal("key_wrappers" in input, false, "personal external tasks retain the master-wrapped encrypted_task_key only");
    assert.equal(input.external_chat_provider, "opencode");
    assert.equal(input.external_chat_lookup_hash, lookupHash);
    assert.ok(input.encrypted_external_chat_id);
    assert.ok(input.encrypted_external_chat_title);
    assert.doesNotMatch(JSON.stringify(input), /ses_external_123|OpenCode task bridge/);

    const decrypted = await decryptUserTask(input, masterKey);
    assert.deepEqual(decrypted.externalChat, {
      provider: "opencode",
      id: "ses_external_123",
      title: "OpenCode task bridge",
    });
    assert.throws(() => parseExternalChatRef("unknown:session"), /Unsupported external chat provider/);
    await assert.rejects(
      buildCreateUserTaskInput(masterKey, {
        title: "Invalid mixed context",
        chatId: "chat-1",
        externalChat: context,
      }),
      /both native chat and external chat context/,
    );
  });

  // contract-test: supporting surface=cli assertions=tasks.external-chat.encrypted-context
  it("derives the external-chat lookup hash with the shared HKDF info literal", () => {
    const masterKey = Buffer.from([...Array(32).keys()]);
    const context = { provider: "opencode" as const, id: "ses_known_derivation" };
    const indexKey = hkdfSync(
      "sha256",
      masterKey,
      Buffer.alloc(0),
      "openmates-task-external-chat-index-v1",
      32,
    );
    const expected = createHmac("sha256", indexKey)
      .update(`${context.provider}\u0000${context.id}`)
      .digest("hex");

    assert.equal(externalChatLookupHash(masterKey, context), expected);
  });

  // contract-test: direct surface=cli assertions=tasks.external-chat.encrypted-context,tasks.surface.semantic-parity
  it("clears external context when assigning a native chat", async () => {
    const masterKey = Buffer.alloc(32, 7);
    const encrypted = await buildCreateUserTaskInput(masterKey, {
      title: "Move task context",
      externalChat: { provider: "opencode", id: "ses_external_123" },
    });
    const task = await decryptUserTask(encrypted, masterKey);
    const patch = await buildUpdateUserTaskInput(task, masterKey, { chatId: "chat-native-1" });

    assert.deepEqual(patch, {
      version: task.version,
      updated_at: patch.updated_at,
      primary_chat_id: "chat-native-1",
      external_chat_provider: null,
      external_chat_lookup_hash: null,
      encrypted_external_chat_id: null,
      encrypted_external_chat_title: null,
    });
  });

  // contract-test: direct surface=cli assertions=tasks.external-chat.encrypted-context,tasks.surface.semantic-parity
  it("sends only the external provider and blind lookup hash when filtering", async () => {
    const masterKey = Buffer.alloc(32, 5);
    const context = parseExternalChatRef("opencode:ses_private_456");
    const lookupHash = externalChatLookupHash(masterKey, context);
    await withServer(
      () => ({ tasks: [] }),
      async (apiUrl, seen) => {
        const client = new OpenMatesClient({ apiUrl, session: testSession() });
        await client.listUserTasks({
          externalChatProvider: context.provider,
          externalChatLookupHash: lookupHash,
        });

        assert.equal(
          seen[0]?.url,
          `/v1/user-tasks?external_chat_provider=opencode&external_chat_lookup_hash=${lookupHash}`,
        );
        assert.doesNotMatch(seen[0]?.url ?? "", /ses_private_456/);
      },
    );
  });

  // contract-test: direct surface=cli assertions=tasks.lifecycle.visible,tasks.blocking.encrypted-reason,tasks.surface.semantic-parity
  it("encrypts blocked explanation while preserving a safe reason code", async () => {
    const masterKey = Buffer.alloc(32, 9);
    const encrypted = await buildCreateUserTaskInput(masterKey, { title: "Publish changes" });
    const task = await decryptUserTask(encrypted, masterKey);
    const action = await buildBlockUserTaskInput(task, masterKey, {
      reasonCode: "missing_credentials",
      reasonText: "A repository write token is required.",
    });

    assert.equal(normalizeBlockedReasonCode("missing_credentials"), "missing_credentials");
    assert.throws(() => normalizeBlockedReasonCode("secret token missing"), /Unknown blocked reason code/);
    assert.equal(action.version, task.version);
    assert.equal(action.blocked_reason_code, "missing_credentials");
    assert.ok(action.encrypted_blocked_reason);
    assert.doesNotMatch(JSON.stringify(action), /repository write token/);

    const blocked = await decryptUserTask({
      ...encrypted,
      status: "blocked",
      blocked_reason_code: "missing_credentials",
      encrypted_blocked_reason: action.encrypted_blocked_reason,
    }, masterKey);
    assert.equal(blocked.blockedReason, "A repository write token is required.");
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
