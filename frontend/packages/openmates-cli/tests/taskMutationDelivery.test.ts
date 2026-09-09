/**
 * Mutation recovery across accepted writes, lost responses and concurrent edits.
 * Tests use synthetic encrypted records and private temporary state directories.
 * No server, external account, model calls or wall-clock retry sleeps are used.
 * Real HTTP and database coverage belongs to the isolated GitHub integration gate.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { taskMutationStore, reconcileMutation, type TaskMutation } from "../src/taskMutationDelivery.ts";
import { TaskDeliveryPending, TaskDeliveryRejected } from "../src/taskDelivery.ts";
import type { UserTaskRecord, OpenMatesClient } from "../src/client.ts";

test("accepted creation with a lost response is reconciled without a duplicate POST", async () => {
  const directory = mkdtempSync(join(tmpdir(), "mutation-delivery-"));
  try {
    let clock = 1000;
    let posts = 0;
    let reads = 0;
    let current: UserTaskRecord | null = null;
    const input = { task_id: "task", encrypted_title: "ciphertext", version: 1 } as never;
    const client = { createUserTask: async () => { posts++; current = { ...input, status: "todo" } as UserTaskRecord; throw new Error("HTTP 503"); },
      getUserTask: async () => { reads++; return current; } } as unknown as OpenMatesClient;
    const scope: [string, string, string] = ["api", "account", "personal"];
    await assert.rejects(taskMutationStore(scope, directory, () => clock).deliver("a".repeat(64), async () => ({kind: "create", taskId: "task", input}), client), TaskDeliveryPending);
    assert.equal(reads, 0);
    clock += 7000;
    await taskMutationStore(scope, directory, () => clock).flush(client);
    assert.equal(posts, 1);
    assert.equal(reads, 1);
    await taskMutationStore(scope, directory, () => clock).deliver("a".repeat(64), async () => { throw new Error("must reuse persisted request"); }, client);
    assert.equal(reads, 1);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

test("uncertain edits never overwrite a newer version or a changed owner", () => {
  const operation: TaskMutation = { kind: "update", taskId: "task", input: { version: 4, encrypted_title: "new" }, ownerHash: "owner" };
  const current = {task_id: "task", version: 4, encrypted_title: "old", external_chat_lookup_hash: "owner"} as UserTaskRecord;
  assert.equal(reconcileMutation(operation, current), "retry");
  assert.equal(reconcileMutation(operation, {...current, version: 5, encrypted_title: "new"}), "accepted");
  assert.throws(() => reconcileMutation(operation, {...current, version: 6, encrypted_title: "different"}), TaskDeliveryRejected);
  assert.throws(() => reconcileMutation(operation, {...current, external_chat_lookup_hash: "other"}), /ownership changed/);
  assert.throws(() => reconcileMutation(operation, null), /no longer accessible/);
});
