import assert from "node:assert/strict";
import { test } from "node:test";
import type { OpenMatesClient } from "../src/client.js";
import type { DecryptedUserTask } from "../src/tasksCli.js";
import { cells } from "../src/tuiText.js";
import { buildTaskForm, filterTasks, renderTaskBoard, renderTaskDetails, submitTaskForm } from "../src/tuiTasksWorkspace.js";

function task(overrides: Partial<DecryptedUserTask> = {}): DecryptedUserTask {
  return {
    taskId: "task-1", shortId: "T-1", slug: "one", title: "First task", description: "A useful description",
    labels: ["cli"], tags: ["cli"], latestInstruction: "", status: "todo", assigneeType: "user", assigneeIdentity: null,
    assigneeHash: null, primaryChatId: null, externalChat: null, linkedProjectIds: [], planId: null, dueAt: null,
    priority: 0, priorityLevel: "none", position: 1, queueState: "none", blockedReasonCode: null, blockedReason: "",
    aiExecutionState: null, version: 2, encrypted: {} as DecryptedUserTask["encrypted"], ...overrides,
  };
}

// contract-test: supporting surface=cli assertions=tasks.lifecycle.visible,cli.output.actionable-readable
test("filters by status and searchable task details in position order", () => {
  const records = [task({taskId: "two", shortId: "T-2", title: "Second CLI task", position: 2}), task(), task({taskId: "three", shortId: "T-3", status: "done", title: "Third task", position: 0})];
  assert.deepEqual(filterTasks(records, "cli task", "todo").map((item) => item.taskId), ["task-1", "two"]);
  assert.deepEqual(filterTasks(records, "T-3").map((item) => item.taskId), ["three"]);
});

// contract-test: supporting surface=cli assertions=tasks.lifecycle.visible,cli.output.actionable-readable
test("wide board keeps five statuses while narrow board focuses one reachable column", () => {
  const records = [task({queueState: "waiting_for_user"}), task({taskId: "two", shortId: "T-2", status: "done", title: "Finished"})];
  const wide = renderTaskBoard(records, {width: 125, selectedTaskId: "task-1"}).join("\n");
  assert.match(wide, /Backlog/);
  assert.match(wide, /In progress/);
  assert.match(wide, /Blocked/);
  assert.match(wide, /Done/);
  assert.match(wide, /Search: \/search/);
  assert.match(wide, /Filter: All statuses/);
  assert.match(wide, /Tags {2}#cli/);
  assert.match(wide, /Q waiting_for_user/);
  assert.match(wide, /› First task/);
  const wideFocused = renderTaskBoard(records, {width:125, status:"done"}).join("\n");
  assert.match(wideFocused, /Todo \(1\)/);
  assert.match(wideFocused, /Done \(1\)/);
  const narrow = renderTaskBoard(records, {width: 55}).join("\n");
  assert.match(narrow, /←\/→ columns {2}· {2}Todo 2\/5/);
  assert.match(narrow, /Todo \(1\)/);
  assert.match(narrow, /First task/);
  assert.doesNotMatch(narrow, /T-2/);
  assert.doesNotMatch(narrow, /Tags {2}#cli/);
  const done = renderTaskBoard(records, {width:55, selectedTaskId:"two"}).join("\n");
  assert.match(done, /Done 5\/5/);
  assert.match(done, /Finished/);
  assert.doesNotMatch(done, /First task/);
  const empty = renderTaskBoard(records, {width:55, status:"backlog"}).join("\n");
  assert.match(empty, /Backlog \(0\)/);
  assert.match(empty, /No tasks here/);
  assert.match(empty, /Tasks board {2}· {2}2 tasks/);
});

// contract-test: supporting surface=cli assertions=tasks.lifecycle.visible,cli.output.actionable-readable
test("wide board aligns display cells for CJK and emoji titles", () => {
  const records = [task({title: "確認 🧪 task", status: "backlog"})];
  const lines = renderTaskBoard(records, {width: 125});
  const cardLine = lines.find((line) => line.includes("確認 🧪"));
  assert.ok(cardLine);
  assert.equal(cells(cardLine), 123);
  assert.match(lines.join("\n"), /╭─+╮/);
});

// contract-test: supporting surface=cli assertions=tasks.structure.flat-dependencies,tasks.activity.single-final-section
test("detail leads with readable task context, relations, and activity", () => {
  const lines = renderTaskDetails(task(), {width: 80, dependencies: {dependencies: [{source_ref: "task:task-1", target_ref: "plan:plan-2"}], blockers: []}, activity: [{entryId: "a", taskId: "task-1", kind: "comment", actorType: "user", actorHash: "", actorIdentity: null, actorDisplayName: "Alice", actorProfileImageUrl: null, authorHash: null, eventType: "", sourceSurface: "", previousStatus: null, nextStatus: null, createdAt: 1, deletedAt: null, deletedByHash: null, deletedByDisplayName: null, message: "Started", embedRefs: []}]}).join("\n");
  assert.match(lines, /First task\nT-1 {2}· {2}Todo/);
  assert.match(lines, /Plan plan-2/);
  assert.match(lines, /Alice: Started/);
  const identityHash = "a".repeat(64);
  const human = renderTaskDetails(task({assigneeHash:identityHash}), {width:100}).join("\n");
  assert.match(human, /Assigned to User/);
  assert.ok(!human.includes(identityHash));
});

// contract-test: supporting surface=cli assertions=tasks.lifecycle.visible,cli.output.actionable-readable
test("web-aligned cards place title before project, assignee and due metadata", () => {
  const board = renderTaskBoard([task({title:"Design 3D model",linkedProjectIds:["opaque-project-id"],dueAt:1767225600})], {width:125}).join("\n");
  const title = board.indexOf("Design 3D model");
  const project = board.indexOf("Project", title);
  const assigned = board.indexOf("User", project);
  const due = board.indexOf("Due 2026-01-01", assigned);
  assert.ok(title >= 0 && project > title && assigned > project && due > assigned);
  assert.doesNotMatch(board, /opaque-project-id/);
});

// contract-test: supporting surface=cli assertions=tasks.lifecycle.visible,cli.surface.semantic-parity
test("forms carry the stable task ID and validate destructive confirmation", async () => {
  const current = task();
  const form = buildTaskForm("delete", current);
  assert.equal(form.kind, "task-delete");
  assert.equal(form.contextId, current.taskId);
  assert.equal(buildTaskForm("edit", current).title, "Edit task · T-1");
  assert.equal(buildTaskForm("create").title, "Create task");
  assert.equal(buildTaskForm("status", current).title, "Move task · T-1");
  let called = false;
  const client = {getMasterKeyBytes: () => new Uint8Array(32), deleteUserTask: async () => {called = true; return {deleted: true};}} as unknown as OpenMatesClient;
  await assert.rejects(submitTaskForm(client, form, current), /DELETE/);
  assert.equal(called, false);
  form.fields[0].value = "DELETE";
  assert.deepEqual(await submitTaskForm(client, form, current), {deleted: true});
  assert.equal(called, true);
});

// contract-test: supporting surface=cli assertions=tasks.lifecycle.visible,cli.surface.semantic-parity
test("reorder submits versioned position and returns the matching decrypted task", async () => {
  const current = task();
  const form = buildTaskForm("reorder", current);
  form.fields[0].value = "12";
  let submitted: unknown;
  const client = {
    getMasterKeyBytes: () => new Uint8Array(32),
    reorderUserTasks: async (input: unknown) => {submitted = input; return [];},
  } as unknown as OpenMatesClient;
  await assert.rejects(submitTaskForm(client, form, current), /missing from the server response/);
  assert.deepEqual(submitted, {moves: [{task_id: "task-1", version: 2, position: 12}]});
});
