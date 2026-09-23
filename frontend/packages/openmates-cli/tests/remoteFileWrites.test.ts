import assert from "node:assert/strict";
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, statSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, it } from "node:test";

import {
  executeRemoteFileMutation,
  readProjectFileVersion,
  RemoteFileMutationError,
  sha256ProjectFile,
} from "../src/remoteFileWrites.ts";

function fixture(): { root: string; journal: string; cleanup: () => void } {
  const base = mkdtempSync(join(tmpdir(), "openmates-file-writes-"));
  const root = join(base, "source");
  const journal = join(base, "journal");
  mkdirSync(root);
  return { root, journal, cleanup: () => rmSync(base, { recursive: true, force: true }) };
}

const authorize = async () => undefined;

function errorCode(reason: unknown): string | undefined {
  return reason instanceof RemoteFileMutationError ? reason.code : undefined;
}

describe("remote Project file writes", () => {
  // contract-test: supporting surface=cli assertions=projects.files.expected-base,projects.files.exact-patch,projects.files.commit-replay
  it("creates, exactly patches, preserves mode, exposes the full version, and replays", async () => {
    const item = fixture();
    try {
      const created = await executeRemoteFileMutation({
        sourceRoot: item.root,
        journalRoot: item.journal,
        operationScope: "account:chat",
        authorize,
        mutation: {
          operation: "create_file",
          operation_id: "create-1",
          path: "notes.txt",
          expected_base: null,
          content: "alpha\nbeta\n",
        },
      });
      assert.equal(created.before_hash, null);
      assert.equal(created.after_hash, sha256ProjectFile("alpha\nbeta\n"));
      assert.match(created.applied_diff, /^--- \/dev\/null/m);
      assert.equal(created.replayed, false);

      chmodSync(join(item.root, "notes.txt"), 0o640);
      const version = readProjectFileVersion({ sourceRoot: item.root, path: "notes.txt" });
      assert.deepEqual(version, {
        content: "alpha\nbeta\n",
        expected_base: sha256ProjectFile("alpha\nbeta\n"),
        sizeBytes: 11,
      });
      const options = {
        sourceRoot: item.root,
        journalRoot: item.journal,
        operationScope: "account:chat",
        authorize,
        mutation: {
          operation: "update_file" as const,
          operation_id: "update-1",
          path: "notes.txt",
          expected_base: version.expected_base,
          patch: "--- a/notes.txt\n+++ b/notes.txt\n@@ -1,2 +1,2 @@\n alpha\n-beta\n+gamma\n",
        },
      };
      const updated = await executeRemoteFileMutation(options);
      assert.equal(updated.content, "alpha\ngamma\n");
      assert.equal(readFileSync(join(item.root, "notes.txt"), "utf8"), "alpha\ngamma\n");
      assert.equal(statSync(join(item.root, "notes.txt")).mode & 0o777, 0o640);

      const replay = await executeRemoteFileMutation(options);
      assert.equal(replay.replayed, true);
      assert.equal(replay.already_applied, true);
      assert.equal(replay.after_hash, updated.after_hash);
    } finally {
      item.cleanup();
    }
  });

  // contract-test: supporting surface=cli assertions=projects.files.expected-base,projects.files.concurrent-chat-safety
  it("allows one concurrent winner and rejects the stale mutation", async () => {
    const item = fixture();
    try {
      writeFileSync(join(item.root, "race.txt"), "one\n");
      const base = sha256ProjectFile("one\n");
      const update = (id: string, value: string) => executeRemoteFileMutation({
        sourceRoot: item.root,
        journalRoot: item.journal,
        operationScope: "account:chat",
        authorize,
        mutation: {
          operation: "update_file",
          operation_id: id,
          path: "race.txt",
          expected_base: base,
          patch: `--- a/race.txt\n+++ b/race.txt\n@@ -1 +1 @@\n-one\n+${value}\n`,
        },
      });
      const results = await Promise.allSettled([update("race-a", "two"), update("race-b", "three")]);
      assert.equal(results.filter((result) => result.status === "fulfilled").length, 1);
      const rejected = results.find((result): result is PromiseRejectedResult => result.status === "rejected");
      assert.equal(errorCode(rejected?.reason), "file_changed");
      assert.ok(["two\n", "three\n"].includes(readFileSync(join(item.root, "race.txt"), "utf8")));
    } finally {
      item.cleanup();
    }
  });

  // contract-test: supporting surface=cli assertions=projects.files.write-policy-enforcement
  it("denies traversal, symlink components, and protected paths", async () => {
    const item = fixture();
    try {
      mkdirSync(join(item.root, "real"));
      symlinkSync(join(item.root, "real"), join(item.root, "linked"));
      const create = (operationId: string, path: string) => executeRemoteFileMutation({
        sourceRoot: item.root,
        journalRoot: item.journal,
        operationScope: "account:chat",
        authorize,
        mutation: { operation: "create_file", operation_id: operationId, path, expected_base: null, content: "safe\n" },
      });
      await assert.rejects(create("traversal", "../outside.txt"), (error) => errorCode(error) === "invalid_path");
      await assert.rejects(create("symlink", "linked/file.txt"), (error) => errorCode(error) === "invalid_path");
      await assert.rejects(create("protected", ".env"), (error) => errorCode(error) === "protected_path");
      assert.equal(existsSync(join(item.root, "real", "file.txt")), false);
    } finally {
      item.cleanup();
    }
  });

  // contract-test: supporting surface=cli assertions=projects.files.exact-patch
  it("rejects malformed or inexact unified patches", async () => {
    const item = fixture();
    try {
      writeFileSync(join(item.root, "plain.txt"), "actual\n");
      const run = (id: string, patch: string) => executeRemoteFileMutation({
        sourceRoot: item.root,
        journalRoot: item.journal,
        operationScope: "account:chat",
        authorize,
        mutation: {
          operation: "update_file",
          operation_id: id,
          path: "plain.txt",
          expected_base: sha256ProjectFile("actual\n"),
          patch,
        },
      });
      await assert.rejects(
        run("bad-count", "--- a/plain.txt\n+++ b/plain.txt\n@@ -1,2 +1 @@\n-actual\n+next\n"),
        (error) => errorCode(error) === "invalid_patch",
      );
      await assert.rejects(
        run("bad-context", "--- a/plain.txt\n+++ b/plain.txt\n@@ -1 +1 @@\n-other\n+next\n"),
        (error) => errorCode(error) === "invalid_patch",
      );
      assert.equal(readFileSync(join(item.root, "plain.txt"), "utf8"), "actual\n");
    } finally {
      item.cleanup();
    }
  });
});
