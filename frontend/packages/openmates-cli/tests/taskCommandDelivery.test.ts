/** Durable CLI-absent intent delivery with real encryption and synthetic HTTP. */
import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { flushTaskCommands } from "../src/taskCommandDelivery.ts";
import type { OpenMatesClient } from "../src/client.ts";
const scope = ["api", "account", "personal"];
const hash = (text: string) => createHash("sha256").update(text).digest("hex");
function setup(root: string) {
  const directory = join(root, "task-command-delivery", hash(JSON.stringify(scope)));
  mkdirSync(directory, {recursive: true});
  const path = join(directory, "a".repeat(64) + ".json");
  writeFileSync(path, JSON.stringify({schema_version: 1, id: "a".repeat(64), scope, thread: "00000000-0000-0000-0000-000000000001",
    task_id: "00000000-0000-0000-0000-000000000002", project_id: "00000000-0000-0000-0000-000000000003", created_at: 100,
    operation: {kind: "create", title: "Restore the header", link_to_chat: false}, state: "pending"}));
  return path;
}
// contract-test: supporting surface=cli assertions=tasks.delivery.durable-intent,tasks.delivery.execution-boundary
test("foreground encrypts a queued creation once and acknowledges only accepted delivery", async () => {
  const root = mkdtempSync(join(tmpdir(), "task-command-"));
  try {
    const path = setup(root); let posts = 0;
    const client = {getSession: () => ({apiUrl: scope[0], hashedEmail: scope[1]}), getMasterKeyBytes: () => new Uint8Array(32),
      createUserTask: async (input: Record<string, unknown>) => {posts++; assert.equal(input.primary_chat_id, null); assert.ok(input.encrypted_title); assert.equal(JSON.stringify(input).includes("Restore the header"), false); return input;} } as unknown as OpenMatesClient;
    await flushTaskCommands(client, undefined, root);
    assert.equal(JSON.parse(readFileSync(path, "utf8")).state, "acknowledged");
    await flushTaskCommands(client, undefined, root);
    assert.equal(posts, 1);
  } finally {rmSync(root, {recursive: true, force: true});}
});
// contract-test: supporting surface=cli assertions=tasks.delivery.durable-intent,tasks.delivery.execution-boundary
test("permanent preparation failure remains rejected instead of escaping retry persistence", async () => {
  const root = mkdtempSync(join(tmpdir(), "task-command-"));
  try {
    const path = setup(root); let attempts = 0;
    const client = {getSession: () => ({apiUrl: scope[0], hashedEmail: scope[1]}), getMasterKeyBytes: () => {attempts++; throw Object.assign(new Error("HTTP 403"), {status: 403});}} as unknown as OpenMatesClient;
    await flushTaskCommands(client, undefined, root);
    assert.equal(JSON.parse(readFileSync(path, "utf8")).state, "rejected");
    await flushTaskCommands(client, undefined, root);
    assert.equal(attempts, 1);
  } finally {rmSync(root, {recursive: true, force: true});}
});
