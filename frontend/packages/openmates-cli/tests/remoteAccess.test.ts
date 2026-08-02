/**
 * Unit tests for Project remote-access bridge primitives.
 *
 * Purpose: verify source-root bounds, default cache layout, deterministic
 * high-risk path policy, and capped rg search before CLI bridge wiring.
 * Security: uses injected rg output only; no shell commands or repository files
 * are read by these tests.
 * Run: node --test --experimental-strip-types --loader ./tests/loader.mjs tests/remoteAccess.test.ts
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { chmodSync, mkdirSync, rmSync, symlinkSync, unlinkSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { classifyProjectFileRisk } from "../src/projectFileRisk.ts";
import {
  listRemoteAccessSources,
  discoverRemoteAccessRepositories,
  listRemoteAccessDirectory,
  readRemoteAccessTextFile,
  remoteAccessSourceType,
  resolveRemoteAccessRoots,
  resolveRemoteCachePath,
  runRgCommand,
  searchRemoteSource,
  searchStoredRemoteAccessSource,
  startRemoteAccessSource,
} from "../src/remoteAccess.ts";

describe("Project remote-access bridge primitives", () => {
  it("stores preview cache under ~/.openmates/remote-cache/<source-id> by default", () => {
    assert.equal(
      resolveRemoteCachePath("source-1", "/home/alice"),
      join("/home/alice", ".openmates", "remote-cache", "source-1"),
    );
  });

  it("classifies built-in and user-protected paths as high-risk", () => {
    assert.deepEqual(classifyProjectFileRisk(".env").reasons, ["secret_or_environment_file"]);
    assert.equal(classifyProjectFileRisk("src/App.svelte").isHighRisk, false);
    assert.deepEqual(
      classifyProjectFileRisk("src/components/BillingCard.svelte", ["src/components/**"]).reasons,
      ["user_protected_pattern"],
    );
  });

  it("runs rg inside the source root and filters capped safe matches", async () => {
    const seen: Array<{ args: string[]; cwd: string }> = [];
    const result = await searchRemoteSource({
      query: "Project",
      sourceRoot: "/workspace/repo",
      maxResults: 2,
      runRg: async (args, cwd) => {
        seen.push({ args, cwd });
        return [
          JSON.stringify({ type: "match", data: { path: { text: "src/App.svelte" }, line_number: 4, lines: { text: "Project UI" } } }),
          JSON.stringify({ type: "match", data: { path: { text: ".env" }, line_number: 1, lines: { text: "SECRET=1" } } }),
          JSON.stringify({ type: "match", data: { path: { text: "src/Second.svelte" }, line_number: 8, lines: { text: "Project card" } } }),
          JSON.stringify({ type: "match", data: { path: { text: "src/Third.svelte" }, line_number: 9, lines: { text: "Project row" } } }),
        ].join("\n");
      },
    });

    assert.equal(seen[0]?.cwd, "/workspace/repo");
    const args = seen[0]?.args ?? [];
    assert.deepEqual(args.slice(0, 2), ["--json", "--line-number"]);
    assert.ok(args.includes("!.env"));
    assert.ok(args.includes("!**/*.png"));
    assert.deepEqual(args.slice(-3), ["--", "Project", "."]);
    assert.deepEqual(result.matches.map((match) => match.path), ["src/App.svelte", "src/Second.svelte"]);
    assert.equal(result.omitted, 1);
    assert.equal(result.excluded, 1);
  });

  it("persists local source metadata and searches stored sources", async () => {
    const home = join(tmpdir(), `openmates-remote-access-${Date.now()}-${Math.random().toString(16).slice(2)}`);
    const repo = join(home, "repo");
    mkdirSync(repo, { recursive: true });
    try {
      const source = startRemoteAccessSource({
        sourceId: "source-1",
        projectId: "project-1",
        rootPath: repo,
        sourceType: "local_git_repository",
        displayName: "Local repo",
        homeDirectory: home,
      });

      assert.equal(source.cachePath, join(home, ".openmates", "remote-cache", "source-1"));
      assert.deepEqual(listRemoteAccessSources(home).map((entry) => entry.sourceId), ["source-1"]);

      const result = await searchStoredRemoteAccessSource({
        sourceId: "source-1",
        query: "Project",
        homeDirectory: home,
        runRg: async () => JSON.stringify({ type: "match", data: { path: { text: "src/App.ts" }, line_number: 2, lines: { text: "Project" } } }),
      });

      assert.equal(result.matches[0]?.path, "src/App.ts");
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });

  it("fails visibly for missing source roots and corrupt local metadata", () => {
    const home = join(tmpdir(), `openmates-remote-access-${Date.now()}-${Math.random().toString(16).slice(2)}`);
    mkdirSync(join(home, ".openmates"), { recursive: true });
    try {
      assert.throws(
        () => startRemoteAccessSource({ sourceId: "source-1", rootPath: join(home, "missing"), homeDirectory: home }),
        /does not exist or is not a directory/,
      );
      assert.throws(() => resolveRemoteCachePath("../escape", home), /Remote source ID/);
      assert.throws(
        () => startRemoteAccessSource({ sourceId: "bad/source", rootPath: home, homeDirectory: home }),
        /Remote source ID/,
      );
      writeFileSync(join(home, ".openmates", "remote-sources.json"), "not json\n");
      assert.throws(() => listRemoteAccessSources(home), /Failed to read remote source store/);
      writeFileSync(join(home, ".openmates", "remote-sources.json"), `${JSON.stringify({ sources: [{}] })}\n`);
      assert.throws(() => listRemoteAccessSources(home), /Remote source record 0 is invalid/);
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });

  it("treats rg exit code 1 as an empty result instead of a command failure", async () => {
    const home = join(tmpdir(), `openmates-remote-access-rg-${Date.now()}-${Math.random().toString(16).slice(2)}`);
    const repo = join(home, "repo");
    const bin = join(home, "bin");
    mkdirSync(repo, { recursive: true });
    mkdirSync(bin, { recursive: true });
    const fakeRg = join(bin, "rg");
    writeFileSync(fakeRg, "#!/usr/bin/env node\nprocess.exit(1);\n");
    chmodSync(fakeRg, 0o755);
    const originalPath = process.env.PATH;
    process.env.PATH = `${bin}:${originalPath ?? ""}`;
    try {
      assert.equal(await runRgCommand(["missing"], repo), "");
    } finally {
      process.env.PATH = originalPath;
      rmSync(home, { recursive: true, force: true });
    }
  });

  it("stops real rg output after the requested match cap", async () => {
    const home = join(tmpdir(), `openmates-remote-access-rg-cap-${Date.now()}-${Math.random().toString(16).slice(2)}`);
    const repo = join(home, "repo");
    const bin = join(home, "bin");
    mkdirSync(repo, { recursive: true });
    mkdirSync(bin, { recursive: true });
    const fakeRg = join(bin, "rg");
    writeFileSync(
      fakeRg,
      `#!/usr/bin/env node
let index = 0;
const timer = setInterval(() => {
  index += 1;
  console.log(JSON.stringify({ type: "match", data: { path: { text: "src/" + index + ".ts" }, line_number: index, lines: { text: "Project" } } }));
  if (index >= 10) {
    clearInterval(timer);
  }
}, 10);
`,
    );
    chmodSync(fakeRg, 0o755);
    const originalPath = process.env.PATH;
    process.env.PATH = `${bin}:${originalPath ?? ""}`;
    try {
      const lines = (await runRgCommand(["Project"], repo, 2)).split("\n").filter(Boolean);
      assert.equal(lines.length, 2);
    } finally {
      process.env.PATH = originalPath;
      rmSync(home, { recursive: true, force: true });
    }
  });

  it("rejects invalid search limits so caps cannot be bypassed", async () => {
    await assert.rejects(
      () => searchRemoteSource({ query: "Project", sourceRoot: "/workspace/repo", maxResults: Number.NaN, runRg: async () => "" }),
      /between 1 and 20/,
    );
    await assert.rejects(
      () => searchRemoteSource({ query: "Project", sourceRoot: "/workspace/repo", maxResults: 21, runRg: async () => "" }),
      /between 1 and 20/,
    );
  });

  it("resolves repeated explicit roots as a replacement scope and deduplicates aliases", () => {
    const home = join(tmpdir(), `openmates-remote-roots-${Date.now()}-${Math.random().toString(16).slice(2)}`);
    const cwd = join(home, "workspace");
    const web = join(cwd, "web");
    const api = join(home, "api");
    mkdirSync(web, { recursive: true });
    mkdirSync(api, { recursive: true });
    try {
      assert.deepEqual(resolveRemoteAccessRoots(undefined, cwd), [cwd]);
      assert.deepEqual(resolveRemoteAccessRoots(`./web\n${api}\n./web`, cwd), [web, api]);
      assert.throws(
        () => resolveRemoteAccessRoots(Array.from({ length: 17 }, (_, index) => join(home, String(index))).join("\n"), cwd),
        /at most 16/,
      );
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });

  it("discovers nested and deeply nested repositories without following symlink directories", () => {
    const home = join(tmpdir(), `openmates-remote-discovery-${Date.now()}-${Math.random().toString(16).slice(2)}`);
    const root = join(home, "workspace");
    const outer = join(root, "outer");
    const nested = join(outer, "packages", "nested");
    const deep = join(root, "a", "b", "c", "d", "e", "f", "g", "deep");
    mkdirSync(join(outer, ".git"), { recursive: true });
    mkdirSync(join(nested, ".git"), { recursive: true });
    mkdirSync(join(deep, ".git"), { recursive: true });
    symlinkSync(home, join(root, "outside-link"), "dir");
    try {
      const discovered = discoverRemoteAccessRepositories([root]);
      assert.deepEqual(discovered.repositories.map((item) => item.rootPath), [deep, nested, outer].sort());
      assert.equal(discovered.permissionDenied.length, 0);
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });

  it("classifies explicit ordinary folders separately from Git repositories", () => {
    const home = join(tmpdir(), `openmates-remote-type-${Date.now()}-${Math.random().toString(16).slice(2)}`);
    const folder = join(home, "folder");
    const repository = join(home, "repository");
    mkdirSync(folder, { recursive: true });
    mkdirSync(join(repository, ".git"), { recursive: true });
    try {
      assert.equal(remoteAccessSourceType(folder), "local_folder");
      assert.equal(remoteAccessSourceType(repository), "local_git_repository");
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });

  it("lists only bounded safe entries and reads bounded UTF-8 text", () => {
    const home = join(tmpdir(), `openmates-remote-read-${Date.now()}-${Math.random().toString(16).slice(2)}`);
    const root = join(home, "repo");
    mkdirSync(join(root, "src"), { recursive: true });
    writeFileSync(join(root, "src", "safe.ts"), "export const safe = true;\n");
    writeFileSync(join(root, ".env"), "SECRET=value\n");
    writeFileSync(join(root, "binary.dat"), Buffer.from([0, 1, 2, 3]));
    try {
      const listing = listRemoteAccessDirectory({ sourceRoot: root, relativePath: ".", maxEntries: 10 });
      assert.deepEqual(listing.entries.map((entry) => entry.path), ["src"]);
      assert.equal(listing.excluded, 2);
      const read = readRemoteAccessTextFile({ sourceRoot: root, relativePath: "src/safe.ts", maxBytes: 200_000, maxLines: 4_000 });
      assert.equal(read.content, "export const safe = true;\n");
      assert.throws(
        () => readRemoteAccessTextFile({ sourceRoot: root, relativePath: "binary.dat" }),
        /binary or unsupported/,
      );
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });

  it("excludes Git-ignored files from listing and direct reads", () => {
    const home = join(tmpdir(), `openmates-remote-ignore-${Date.now()}-${Math.random().toString(16).slice(2)}`);
    const root = join(home, "repo");
    mkdirSync(root, { recursive: true });
    const initialized = spawnSync("git", ["init", "--quiet", root]);
    assert.equal(initialized.status, 0);
    writeFileSync(join(root, ".gitignore"), "private-notes.txt\n");
    writeFileSync(join(root, "private-notes.txt"), "ignored plaintext\n");
    writeFileSync(join(root, "visible.txt"), "visible plaintext\n");
    try {
      const listing = listRemoteAccessDirectory({ sourceRoot: root, relativePath: "." });
      assert.deepEqual(listing.entries.map((entry) => entry.path), ["visible.txt"]);
      assert.throws(
        () => readRemoteAccessTextFile({ sourceRoot: root, relativePath: "private-notes.txt" }),
        /ignored/,
      );
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });

  it("rejects a file swapped to an outside-root symlink before open", () => {
    const home = join(tmpdir(), `openmates-remote-race-${Date.now()}-${Math.random().toString(16).slice(2)}`);
    const root = join(home, "repo");
    const safePath = join(root, "safe.txt");
    const outsidePath = join(home, "outside.txt");
    mkdirSync(root, { recursive: true });
    writeFileSync(safePath, "safe\n");
    writeFileSync(outsidePath, "outside secret\n");
    try {
      assert.throws(
        () => readRemoteAccessTextFile({
          sourceRoot: root,
          relativePath: "safe.txt",
          beforeOpen: () => {
            unlinkSync(safePath);
            symlinkSync(outsidePath, safePath);
          },
        }),
        /approved source root|symbolic link/,
      );
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });
});
