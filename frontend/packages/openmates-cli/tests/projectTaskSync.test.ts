/**
 * Project Task cache recovery and completeness using synthetic task data.
 * Exercises partial batches, reconnect, deletion, old replay and account scope.
 * No product server, authentication data or model requests are used.
 * Real database/WebSocket integration runs in the isolated GitHub harness.
 * See docs/plans/codex-tasks-orchestration/plan.yml.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { ProjectTaskCache, renderTaskOverview, type CachedTask, type ProjectTaskFrame } from "../src/projectTaskSync.ts";
const task = (id: string): CachedTask => ({ task_id: id, short_id: `TASK-${id}`, title: `Work ${id} ` + "long title ".repeat(30),
  description: "detail ".repeat(1000), status: "blocked", version: 1, primary_chat_id: null,
  external_chat: { provider: "codex", id: "worker-1", title: "Landing - Header" },
  blocked_reason: "Waiting for approval", blocked_reason_code: "waiting_for_approval", dependencies: [], latest_activity: "update ".repeat(1000) });
const frame = (changes: Partial<ProjectTaskFrame> = {}): ProjectTaskFrame => ({ project_id: "project", batch_id: "batch", part: 0,
  final: true, reset: true, cursor: "epoch:1", tasks: [], removed_task_ids: [], ...changes });
const decrypt = async (record: ProjectTaskFrame["tasks"][number]) => task(record.task_id);

// contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
test("full snapshot keeps all titles; text limits only description and activity", async () => {
  const directory = mkdtempSync(join(tmpdir(), "om-task-sync-"));
  try {
    const cache = new ProjectTaskCache(directory, "account", "project");
    await cache.accept(frame({ tasks: Array.from({ length: 12 }, (_, i) => ({ task_id: String(i) }) as never) }), decrypt);
    const view = renderTaskOverview(cache.snapshot.tasks);
    for (let i = 0; i < 12; i++) assert.ok(view.includes(JSON.stringify(task(String(i)).title)));
    assert.ok(view.includes("Waiting for approval"));
    assert.ok(!view.includes("detail ".repeat(1000)));
    assert.ok(!view.includes("update ".repeat(1000)));
    assert.equal(statSync(join(cache.directory, "snapshot.json")).mode & 0o777, 0o600);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

// contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
test("partial batch never advances disk cursor, restart replays safely", async () => {
  const directory = mkdtempSync(join(tmpdir(), "om-task-sync-"));
  try {
    const cache = new ProjectTaskCache(directory, "account", "project");
    await cache.accept(frame({ tasks: [{ task_id: "1" } as never] }), decrypt);
    await cache.accept(frame({ cursor: "epoch:2", batch_id: "new", final: false, tasks: [{ task_id: "2" } as never] }), decrypt);
    const restarted = new ProjectTaskCache(directory, "account", "project");
    assert.equal(restarted.cursor, "epoch:1");
    assert.deepEqual(restarted.snapshot.tasks.map(task => task.task_id), ["1"]);
    await restarted.accept(frame({ cursor: "epoch:2", reset: false, removed_task_ids: ["1"] }), decrypt);
    await restarted.accept(frame({ cursor: "epoch:1", tasks: [{ task_id: "1" } as never] }), decrypt);
    assert.equal(restarted.cursor, "epoch:2");
    assert.equal(restarted.snapshot.tasks.length, 0);
    assert.equal(new ProjectTaskCache(directory, "other-account", "project").cursor, undefined);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

// contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
test("revocation clears cached content and replay cursor", async () => {
  const directory = mkdtempSync(join(tmpdir(), "om-task-sync-"));
  try {
    const cache = new ProjectTaskCache(directory, "account", "project");
    await cache.accept(frame({ tasks: [{ task_id: "1" } as never] }), decrypt);
    cache.connection("revoked");
    assert.equal(cache.cursor, undefined);
    assert.equal(cache.snapshot.tasks.length, 0);
    assert.ok(!readFileSync(join(cache.directory, "tasks.txt"), "utf8").includes("Work 1"));
  } finally { rmSync(directory, { recursive: true, force: true }); }
});
