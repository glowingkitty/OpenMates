/*
 * Recoverable encrypted activity delivery with a synthetic server callback.
 * Simulates accepted-write/lost-response and a fresh CLI process instance.
 * Verifies identical ciphertext retries, account isolation and acknowledgements.
 * Temporary files contain synthetic ciphertext only and are removed afterward.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync, readdirSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { activityDeliveryStore } from "../src/taskActivityDelivery.ts";
import type { UserTaskActivityCreateInput, UserTaskActivityRecord } from "../src/client.ts";

// contract-test: supporting surface=cli assertions=tasks.activity.client-encrypted,tasks.activity.single-final-section
test("lost acknowledgement recovers identical ciphertext after restart without duplication", async () => {
  const directory = mkdtempSync(join(tmpdir(), "activity-delivery-"));
  const id = "a".repeat(64);
  const input: UserTaskActivityCreateInput = { entry_id: id, encrypted_message: "ciphertext-only", created_at: 100, embed_refs: [] };
  const entry = { ...input, task_id: "task-1", kind: "comment" } as UserTaskActivityRecord;
  let builds = 0;
  let writes = 0;
  try {
    const first = activityDeliveryStore("account-a:task-1:assignee", directory);
    await assert.rejects(first.deliver(id, async () => { builds++; return input; }, async () => { writes++; throw new Error("response lost"); }));
    const restarted = activityDeliveryStore("account-a:task-1:assignee", directory);
    const flushed = await restarted.flush(async actual => { assert.deepEqual(actual, input); writes++; return entry; });
    assert.equal(flushed.pending, 0);
    await restarted.deliver(id, async () => { throw new Error("must not encrypt again"); }, async () => { throw new Error("must not post again"); });
    assert.equal(builds, 1);
    assert.equal(writes, 2);
    assert.equal((await activityDeliveryStore("account-b:task-1:assignee", directory).flush(async () => { throw new Error("cross-account delivery"); })).attempted, 0);
    const folders = readdirSync(join(directory, "task-activity-delivery"));
    const files = folders.flatMap(folder => readdirSync(join(directory, "task-activity-delivery", folder, "acknowledged")).map(name => join(directory, "task-activity-delivery", folder, "acknowledged", name)));
    assert.equal(files.length, 1);
    assert.match(readFileSync(files[0], "utf8"), /ciphertext-only/);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});
