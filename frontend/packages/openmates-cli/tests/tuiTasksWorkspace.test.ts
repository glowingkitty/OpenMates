import assert from "node:assert/strict";
import { test } from "node:test";
import type { OpenMatesClient } from "../src/client.js";
import type { DecryptedUserTask } from "../src/tasksCli.js";
import { cells, lineText, type TuiLine } from "../src/tuiText.js";
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
const boardText = (lines: TuiLine[]): string => lines.map(lineText).join("\n");

// contract-test: supporting surface=cli assertions=tasks.lifecycle.visible,cli.output.actionable-readable
test("filters by status and searchable task details in position order", () => {
  const records = [task({taskId: "two", shortId: "T-2", title: "Second CLI task", position: 2}), task(), task({taskId: "three", shortId: "T-3", status: "done", title: "Third task", position: 0})];
  assert.deepEqual(filterTasks(records, "cli task", "todo").map((item) => item.taskId), ["task-1", "two"]);
  assert.deepEqual(filterTasks(records, "T-3").map((item) => item.taskId), ["three"]);
});

// contract-test: supporting surface=cli assertions=tasks.lifecycle.visible,cli.output.actionable-readable
test("wide board keeps five statuses while narrow board focuses one reachable column", () => {
  const records = [task({queueState: "waiting_for_user"}), task({taskId: "two", shortId: "T-2", status: "done", title: "Finished"})];
  const wide = boardText(renderTaskBoard(records, {width: 125, selectedTaskId: "task-1"}));
  assert.match(wide, /Backlog/);
  assert.match(wide, /In progress/);
  assert.match(wide, /Blocked/);
  assert.match(wide, /Done/);
  assert.match(wide, /Search: \/search/);
  assert.match(wide, /Filter: All statuses/);
  assert.match(wide, /Tags {2}#cli/);
  assert.match(wide, /Q waiting_for_user/);
  assert.match(wide, /› First task/);
  const wideFocused = boardText(renderTaskBoard(records, {width:125, status:"done"}));
  assert.match(wideFocused, /▌ Todo \(1\)/);
  assert.match(wideFocused, /▌ Done \(1\)/);
  const narrow = boardText(renderTaskBoard(records, {width: 55}));
  assert.match(narrow, /←\/→ columns {2}· {2}Todo 2\/5/);
  assert.match(narrow, /▌ Todo \(1\)/);
  assert.match(narrow, /First task/);
  assert.doesNotMatch(narrow, /T-2/);
  assert.doesNotMatch(narrow, /Tags {2}#cli/);
  const done = boardText(renderTaskBoard(records, {width:55, selectedTaskId:"two"}));
  assert.match(done, /Done 5\/5/);
  assert.match(done, /Finished/);
  assert.doesNotMatch(done, /First task/);
  const empty = boardText(renderTaskBoard(records, {width:55, status:"backlog"}));
  assert.match(empty, /▌ Backlog \(0\)/);
  assert.match(empty, /No tasks here/);
  assert.match(empty, /Tasks board {2}· {2}2 tasks/);
});

// contract-test: supporting surface=cli assertions=tasks.lifecycle.visible,cli.output.actionable-readable
test("medium board shows adjacent columns and keeps the focused status reachable", () => {
  const records = [
    task({taskId: "backlog", shortId: "T-1", status: "backlog", title: "Plan work"}),
    task({taskId: "progress", shortId: "T-2", status: "in_progress", title: "Build work"}),
    task({taskId: "done", shortId: "T-3", status: "done", title: "Ship work"}),
  ];
  const three = renderTaskBoard(records, {width: 100, selectedTaskId: "done"});
  const threeText = boardText(three);
  assert.match(threeText, /▌ In progress \(1\) +▌ Blocked \(0\) +▌ Done \(1\)/);
  assert.match(threeText, /No tasks here\./);
  assert.match(threeText, /› Ship work/);
  assert.match(threeText, /T-3/);
  assert.doesNotMatch(threeText, /Plan work/);
  assert.ok(three.every((line) => cells(lineText(line)) <= 100));

  const two = renderTaskBoard(records, {width: 80, status: "blocked"});
  const twoText = boardText(two);
  assert.match(twoText, /▌ In progress \(1\) +▌ Blocked \(0\)/);
  assert.match(twoText, /Build work/);
  assert.match(twoText, /No tasks here\./);
  assert.doesNotMatch(twoText, /Ship work/);
  assert.ok(two.every((line) => cells(lineText(line)) <= 80));
});

// contract-test: supporting surface=cli assertions=tasks.lifecycle.visible,cli.output.actionable-readable
test("wide board aligns display cells for CJK and emoji titles", () => {
  const records = [task({title: "確認 🧪 task", status: "backlog"})];
  const lines = renderTaskBoard(records, {width: 125});
  const cardLine = lines.find((line) => lineText(line).includes("確認 🧪"));
  assert.ok(cardLine);
  assert.equal(cells(lineText(cardLine)), 123);
  assert.match(boardText(lines), /╭─+╮/);
});

// contract-test: supporting surface=cli assertions=tasks.lifecycle.visible,cli.output.actionable-readable
test("Kanban headers carry web status colors and bold labels at every responsive width", () => {
  const colors = ["#bf5af2", "#32ade6", "#f0a050", "#ff6b6b", "#30d158"];
  for (const [width, focus, expected] of [[125, "todo", colors], [100, "in_progress", colors.slice(1, 4)], [80, "in_progress", colors.slice(1, 3)], [55, "todo", [colors[1]]] ] as const) {
    const lines = renderTaskBoard([task()], {width, status: focus});
    const header = lines.find((line) => lineText(line).includes("▌ Todo (1)"));
    assert.ok(header && typeof header !== "string");
    assert.deepEqual(header.spans?.filter((span) => span.text === "▌").map((span) => span.color), expected);
    assert.ok(header.spans?.filter((span) => span.text.includes("(")).every((span) => span.bold));
    assert.ok(lines.every((line) => cells(lineText(line)) <= width));
  }
});

// contract-test: supporting surface=cli assertions=tasks.lifecycle.visible,cli.output.actionable-readable
test("only the selected card has the accented border, background, and title marker", () => {
  const records = [task(), task({taskId: "two", shortId: "T-2", title: "Second task", position: 2})];
  const lines = renderTaskBoard(records, {width: 55, selectedTaskId: "two"});
  const text = boardText(lines);
  assert.match(text, /╭─+╮[\s\S]*First task[\s\S]*╰─+╯/);
  assert.match(text, /╔═+╗[\s\S]*› Second task[\s\S]*╚═+╝/);
  assert.equal((text.match(/› /g) ?? []).length, 1);
  const selectedRows = lines.filter((line) => lineText(line).includes("Second task") || lineText(line).includes("╔") || lineText(line).includes("╚"));
  assert.ok(selectedRows.every((line) => typeof line !== "string" && line.spans?.some((span) => span.background === "#263b52")));
  const firstTitle = lines.find((line) => lineText(line).includes("First task"));
  assert.ok(firstTitle&&typeof firstTitle!=="string");
  assert.equal(firstTitle.background,undefined);
  assert.equal(firstTitle.spans?.some(span=>span.background),undefined);
  assert.deepEqual(firstTitle.action,{kind:"select",target:"task",column:1,index:0,id:"task-1",activate:true});
});

// contract-test: supporting surface=cli assertions=tasks.lifecycle.visible,cli.output.actionable-readable
test("board viewport preserves row positions, visible styling, and pointer actions at every width", () => {
  const statuses = ["backlog", "todo", "in_progress", "blocked", "done"] as const;
  const records = Array.from({length: 60}, (_, index) => task({
    taskId: `task-${index}`, shortId: `T-${index}`, position: index,
    status: statuses[index % statuses.length], title: index % 3 === 0 ? `確認 🧪 long task ${index} with wrapped title` : `Task ${index}`,
    linkedProjectIds: index % 4 === 0 ? ["project"] : [], dueAt: index % 5 === 0 ? 1767225600 : null,
    priority: index % 7 === 0 ? 2 : 0, priorityLevel: index % 7 === 0 ? "high" : "none",
    queueState: index % 6 === 0 ? "waiting_for_user" : "none",
  }));
  for (const width of [55, 80, 100, 125]) {
    const options = {width, selectedTaskId: "task-56"};
    const full = renderTaskBoard(records, options);
    const viewport = {start: 8, end: 23};
    const windowed = renderTaskBoard(records, {...options, viewport});
    assert.equal(windowed.length, full.length, `row count at width ${width}`);
    assert.deepEqual(windowed.slice(viewport.start, viewport.end), full.slice(viewport.start, viewport.end), `visible rows at width ${width}`);
    const selectedRow = full.findIndex((line) => lineText(line).includes("› Task 56"));
    assert.ok(selectedRow > viewport.end, `selected task is outside initial viewport at width ${width}`);
    assert.deepEqual(windowed.slice(selectedRow - 10, selectedRow + 10), full.slice(selectedRow - 10, selectedRow + 10), `selection scroll rows at width ${width}`);
    assert.ok(windowed.slice(viewport.end, selectedRow - 15).some((line) => line === ""), `distant rows are placeholders at width ${width}`);

    const scrolling = renderTaskBoard(records, {...options, viewport: {...viewport, followSelection: false}});
    assert.equal(scrolling.length, full.length);
    assert.deepEqual(scrolling.slice(viewport.start, viewport.end), full.slice(viewport.start, viewport.end), `scroll rows at width ${width}`);
    assert.equal(scrolling[selectedRow], "", `offscreen selection is deferred at width ${width}`);
  }
});

// contract-test: supporting surface=cli assertions=tasks.lifecycle.visible,cli.output.actionable-readable
test("board viewport reflects in-place task edits, reordering, filtering, and fresh actions", () => {
  const records = Array.from({length: 24}, (_, index) => task({taskId: `task-${index}`, shortId: `T-${index}`, title: `Task ${index}`, position: index}));
  const options = {width: 55, selectedTaskId: "task-20", viewport: {start: 0, end: 12}};
  const before = renderTaskBoard(records, options);
  assert.equal(before.length, renderTaskBoard(records, {width: 55, selectedTaskId: "task-20"}).length);
  records[20].title = "確認 🧪 edited title across cells and enough extra words to wrap onto a second row";
  records[20].position = -1;
  records[20].queueState = "waiting_for_user";
  const full = renderTaskBoard(records, {width: 55, selectedTaskId: "task-20"});
  const windowed = renderTaskBoard(records, options);
  assert.ok(full.length > before.length, "in-place title and queue changes update cached card height");
  assert.equal(windowed.length, full.length);
  assert.deepEqual(windowed.slice(0, 12), full.slice(0, 12));
  const selected = windowed.find((line) => lineText(line).includes("› 確認 🧪"));
  assert.ok(selected && typeof selected !== "string");
  assert.deepEqual(selected.action, {kind:"select",target:"task",column:1,index:0,id:"task-20",activate:true});
  assert.match(boardText(windowed), /Q waiting_for_user/);
  const filtered = renderTaskBoard(records, {...options, query:"edited"});
  assert.deepEqual(filtered, renderTaskBoard(records, {width:55,selectedTaskId:"task-20",query:"edited"}));
  assert.ok(filtered.length < before.length);
});

// contract-test: supporting surface=cli assertions=tasks.lifecycle.visible,cli.output.actionable-readable
test("board viewport clamps End jumps to complete tail rows", () => {
  const records = Array.from({length: 34}, (_, index) => task({
    taskId: `task-${index}`, shortId: `T-${index}`, title: index % 2 ? `確認 🧪 task ${index}` : `Task ${index}`,
    position: index, queueState: index % 3 === 0 ? "waiting_for_user" : "none",
  }));
  for (const width of [55, 125]) {
    const full = renderTaskBoard(records, {width});
    const span = 18;
    assert.ok(full.length > span);
    const atEnd = renderTaskBoard(records, {width, viewport: {start: 10000, end: 10000 + span}});
    assert.equal(atEnd.length, full.length);
    assert.deepEqual(atEnd.slice(-span), full.slice(-span), `tail at width ${width}`);
    assert.ok(atEnd.slice(8, -span).some((line) => line === ""), `distant rows at width ${width}`);

    const beforeTop = renderTaskBoard(records, {width, viewport: {start: -10, end: 5}});
    assert.equal(beforeTop.length, full.length);
    assert.deepEqual(beforeTop.slice(0, 15), full.slice(0, 15), `negative start at width ${width}`);
  }

  for (const width of [55, 125]) {
    const full = renderTaskBoard([task()], {width});
    const atEnd = renderTaskBoard([task()], {width, viewport: {start: 10000, end: 10050}});
    assert.deepEqual(atEnd, full, `short board at width ${width}`);
  }
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
  const board = boardText(renderTaskBoard([task({title:"Design 3D model",linkedProjectIds:["opaque-project-id"],dueAt:1767225600})], {width:125}));
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
