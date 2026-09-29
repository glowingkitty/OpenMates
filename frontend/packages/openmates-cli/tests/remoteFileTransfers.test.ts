// contract-test-file: infrastructure
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { executeRemoteFileTransfer, RemoteFileTransferError } from "../src/remoteFileTransfers.js";

function fixture(run: (root: string) => Promise<void>): Promise<void> {
  const root = mkdtempSync(join(tmpdir(), "openmates-file-transfer-"));
  return run(root).finally(() => rmSync(root, { recursive: true, force: true }));
}

test("copies and moves large binary files without routing bytes through the bridge", async () => fixture(async (root) => {
  mkdirSync(join(root, "to"));
  mkdirSync(join(root, "other"));
  const bytes = Buffer.alloc(6 * 1024 * 1024, 0x84);
  writeFileSync(join(root, "archive.bin"), bytes);
  const copied = await executeRemoteFileTransfer({ sourceRoot: root, operation: "copy_entries", paths: ["archive.bin"], destinationPath: "to" });
  assert.deepEqual(copied.completed, ["archive.bin"]);
  assert.deepEqual(copied.failed, []);
  assert.equal(createHash("sha256").update(readFileSync(join(root, "to", "archive.bin"))).digest("hex"), createHash("sha256").update(bytes).digest("hex"));
  const moved = await executeRemoteFileTransfer({ sourceRoot: root, operation: "move_entries", paths: ["to/archive.bin"], destinationPath: "other" });
  assert.deepEqual(moved.completed, ["to/archive.bin"]);
  assert.deepEqual(moved.failed, []);
  assert.equal(readFileSync(join(root, "other", "archive.bin")).length, bytes.length);
}));

test("preserves destination collisions and returns per-entry failures", async () => fixture(async (root) => {
  mkdirSync(join(root, "to"));
  writeFileSync(join(root, "first.txt"), "first");
  writeFileSync(join(root, "second.txt"), "second");
  writeFileSync(join(root, "to", "second.txt"), "existing");
  const result = await executeRemoteFileTransfer({ sourceRoot: root, operation: "copy_entries", paths: ["first.txt", "second.txt"], destinationPath: "to" });
  assert.deepEqual(result.completed, ["first.txt"]);
  assert.deepEqual(result.failed, [{ path: "second.txt", code: "target_exists" }]);
  assert.equal(readFileSync(join(root, "to", "second.txt"), "utf8"), "existing");
}));

test("copies folders but rejects hidden and linked descendants", async () => fixture(async (root) => {
  mkdirSync(join(root, "to"));
  mkdirSync(join(root, "safe"));
  writeFileSync(join(root, "safe", "child.txt"), "hello");
  const copied = await executeRemoteFileTransfer({ sourceRoot: root, operation: "copy_entries", paths: ["safe"], destinationPath: "to" });
  assert.deepEqual(copied.completed, ["safe"]);
  assert.equal(readFileSync(join(root, "to", "safe", "child.txt"), "utf8"), "hello");
  mkdirSync(join(root, "blocked"));
  writeFileSync(join(root, "blocked", ".private"), "hidden");
  symlinkSync(join(root, "safe", "child.txt"), join(root, "blocked", "link"));
  const denied = await executeRemoteFileTransfer({ sourceRoot: root, operation: "move_entries", paths: ["blocked"], destinationPath: "to" });
  assert.equal(denied.failed[0]?.code, "protected_path");
}));

test("rejects traversal and moving a directory into itself", async () => fixture(async (root) => {
  mkdirSync(join(root, "a"));
  await assert.rejects(
    executeRemoteFileTransfer({ sourceRoot: root, operation: "copy_entries", paths: ["../outside"], destinationPath: "." }),
    (error) => error instanceof RemoteFileTransferError && error.code === "invalid_path",
  );
  await assert.rejects(
    executeRemoteFileTransfer({ sourceRoot: root, operation: "move_entries", paths: ["a"], destinationPath: "a/child" }),
    (error) => error instanceof RemoteFileTransferError && error.code === "invalid_path",
  );
}));
