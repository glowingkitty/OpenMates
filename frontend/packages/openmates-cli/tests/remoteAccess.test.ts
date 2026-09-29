// contract-test-file: infrastructure
/**
 * Unit tests for Project remote-access bridge primitives.
 *
 * Purpose: verify source-root bounds, default cache layout, deterministic
 * high-risk path policy, and capped rg search before CLI bridge wiring.
 * Security: temporary repositories prove both injected rg output and the
 * bounded no-rg fallback without reading the real workspace.
 * Run: node --test --experimental-strip-types --loader ./tests/loader.mjs tests/remoteAccess.test.ts
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { chmodSync, linkSync, mkdirSync, rmSync, symlinkSync, unlinkSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { classifyProjectFileReadRisk, classifyProjectFileRisk } from "../src/projectFileRisk.ts";
import { readProjectFileVersion } from "../src/remoteFileWrites.ts";
import { ProjectSearchProtocolError } from "../../ui/src/utils/projectSearchProtocol.ts";
import {
  listRemoteAccessSources,
  projectRemoteAccessCryptoIdentity,
  discoverRemoteAccessRepositories,
  listRemoteAccessDirectory,
  projectRemoteAccessLifecyclePayload,
  readRemoteAccessImageChunk,
  readRemoteAccessFileChunk,
  readRemoteAccessTextFile,
  remoteAccessOperationErrorCode,
  remoteAccessHostingCandidates,
  remoteAccessSourceType,
  resolveRemoteAccessRoots,
  resolveRemoteCachePath,
  runRgCommand,
  searchRemoteSource,
  searchStoredRemoteAccessSource,
  startRemoteAccessSource,
} from "../src/remoteAccess.ts";

describe("Project remote-access bridge primitives", () => {
  it("uses the authenticated owner for Personal frames even with stray Team routing identity", () => {
    const frame = {
      project_id: "project-1",
      source_id: "source-1",
      requesting_client_id: "requester-client",
      key_epoch: 1,
      routing_identity: {
        context_type: "team",
        context_id_hash: "stray-team-hash",
        host_member_hash: "stray-host",
        host_device_fingerprint_hash: "stray-host-device",
        requester_member_hash: "stray-requester",
        requester_device_fingerprint_hash: "stray-requester-device",
      },
    };

    assert.deepEqual(
      projectRemoteAccessCryptoIdentity("owner-1", "session-1", {}, frame as never),
      {
        ownerId: "owner-1",
        projectId: "project-1",
        sourceId: "source-1",
        sourceSessionId: "session-1",
        requestingClientId: "requester-client",
        keyEpoch: 1,
      },
    );
  });

  it("uses scoped routing identity for Team v2 frames", () => {
    const routingIdentity = {
      context_type: "team",
      context_id_hash: "team-hash",
      host_member_hash: "host-hash",
      host_device_fingerprint_hash: "host-device-hash",
      requester_member_hash: "requester-hash",
      requester_device_fingerprint_hash: "requester-device-hash",
    };
    const identity = projectRemoteAccessCryptoIdentity(
      "owner-1",
      "session-1",
      { teamId: "team-1" },
      {
        project_id: "project-1",
        source_id: "source-1",
        requesting_client_id: "requester-client",
        key_epoch: 2,
        routing_identity: routingIdentity,
      } as never,
    );

    assert.deepEqual(identity, {
      ownerId: "team-hash",
      contextType: "team",
      contextId: "team-hash",
      hostMemberId: "host-hash",
      hostDeviceId: "host-device-hash",
      requesterMemberId: "requester-hash",
      requesterDeviceId: "requester-device-hash",
      projectId: "project-1",
      sourceId: "source-1",
      sourceSessionId: "session-1",
      requestingClientId: "requester-client",
      keyEpoch: 2,
    });
  });

  it("includes Team context on every source lifecycle message", () => {
    const bindings = [{
      source: { sourceId: "source-1", projectId: "project-1" },
      projectKey: new Uint8Array(32),
      keyEpoch: 1,
      teamId: "team-1",
    }];

    assert.deepEqual(projectRemoteAccessLifecyclePayload("session-1", bindings), {
      source_session_id: "session-1",
      team_id: "team-1",
    });
  });

  it("stores preview cache under ~/.openmates/remote-cache/<source-id> by default", () => {
    assert.equal(
      resolveRemoteCachePath("source-1", "/home/alice"),
      join("/home/alice", ".openmates", "remote-cache", "source-1"),
    );
  });

  it("uses OPENMATES_STATE_DIR for the default source registry and cache", () => {
    const base = join(tmpdir(), `openmates-remote-state-${Date.now()}-${Math.random().toString(16).slice(2)}`);
    const state = join(base, "private-state");
    const project = join(base, "project");
    mkdirSync(state, { recursive: true });
    mkdirSync(project, { recursive: true });
    writeFileSync(join(project, "README.md"), "fixture\n");
    const previous = process.env.OPENMATES_STATE_DIR;
    process.env.OPENMATES_STATE_DIR = state;
    try {
      const source = startRemoteAccessSource({ sourceId: "isolated-source", projectId: "project-1", rootPath: project });
      assert.equal(source.cachePath, join(state, "remote-cache", "isolated-source"));
      assert.deepEqual(listRemoteAccessSources().map((entry) => entry.sourceId), ["isolated-source"]);
      assert.equal(listRemoteAccessSources(base).length, 0, "explicit homeDirectory keeps legacy ~/.openmates compatibility");
    } finally {
      if (previous === undefined) delete process.env.OPENMATES_STATE_DIR;
      else process.env.OPENMATES_STATE_DIR = previous;
      rmSync(base, { recursive: true, force: true });
    }
  });

  it("rejects a source root that could expose the private OpenMates state directory", async () => {
    const home = join(tmpdir(), `openmates-private-state-${Date.now()}-${Math.random().toString(16).slice(2)}`);
    const state = join(home, ".openmates");
    const project = join(home, "projects", "safe-project");
    mkdirSync(state, { recursive: true });
    mkdirSync(project, { recursive: true });
    writeFileSync(join(state, "session.json"), "private fixture\n");
    writeFileSync(join(project, "source.ts"), "export const safe = true;\n");
    const previousState = process.env.OPENMATES_STATE_DIR;
    process.env.OPENMATES_STATE_DIR = state;
    try {
      assert.throws(() => resolveRemoteAccessRoots(home, home), /overlaps OpenMates private state/);
      assert.throws(
        () => startRemoteAccessSource({ sourceId: "unsafe", rootPath: home, homeDirectory: home }),
        /overlaps OpenMates private state/,
      );
      assert.throws(() => listRemoteAccessDirectory({ sourceRoot: home, relativePath: "." }), /private state/);
      assert.throws(
        () => readRemoteAccessTextFile({ sourceRoot: home, relativePath: ".openmates/session.json" }),
        /private state/,
      );
      await assert.rejects(
        () => searchRemoteSource({
          query: "private",
          sourceRoot: home,
          runRg: async () => { throw new Error("search must not start"); },
        }),
        /private state/,
      );
      assert.throws(
        () => readProjectFileVersion({ sourceRoot: home, path: ".openmates/session.json" }),
        (error: unknown) => error instanceof Error && /unavailable or protected/.test(error.message),
      );
      assert.deepEqual(
        listRemoteAccessDirectory({ sourceRoot: project, relativePath: "." }).entries,
        [{ path: "source.ts", kind: "file", sizeBytes: Buffer.byteLength("export const safe = true;\n") }],
      );
    } finally {
      if (previousState === undefined) delete process.env.OPENMATES_STATE_DIR;
      else process.env.OPENMATES_STATE_DIR = previousState;
      rmSync(home, { recursive: true, force: true });
    }
  });

  it("classifies built-in and user-protected paths as high-risk", () => {
    assert.deepEqual(classifyProjectFileRisk(".env").reasons, ["secret_or_environment_file"]);
    assert.equal(classifyProjectFileRisk("src/App.svelte").isHighRisk, false);
    assert.deepEqual(
      classifyProjectFileRisk("src/components/BillingCard.svelte", ["src/components/**"]).reasons,
      ["user_protected_pattern"],
    );
    assert.equal(classifyProjectFileReadRisk("package.json").isHighRisk, false);
    assert.equal(classifyProjectFileReadRisk("Dockerfile").isHighRisk, false);
    assert.equal(classifyProjectFileReadRisk("src/auth/session.ts").isHighRisk, false);
    assert.deepEqual(classifyProjectFileReadRisk(".env").reasons, ["credential_file"]);
  });

  it("runs rg inside the source root and filters capped safe matches", async () => {
    const home = join(tmpdir(), `openmates-remote-search-${Date.now()}-${Math.random().toString(16).slice(2)}`);
    const repo = join(home, "repo");
    mkdirSync(repo, { recursive: true });
    const seen: Array<{ args: string[]; cwd: string }> = [];
    try {
      const result = await searchRemoteSource({
        query: "Project",
        sourceRoot: repo,
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

      assert.equal(seen[0]?.cwd, repo);
      const args = seen[0]?.args ?? [];
      assert.deepEqual(args.slice(0, 4), ["--no-config", "--hidden", "--color", "never"]);
      assert.ok(args.includes("--fixed-strings"));
      assert.ok(args.includes("!.env"));
      assert.ok(args.includes("!**/*.png"));
      assert.deepEqual(args.slice(-4), ["--regexp", "Project", "--", "."]);
      assert.deepEqual(result.matches.map((match) => match.path), ["src/App.svelte", "src/Second.svelte"]);
      assert.equal(result.omitted, 1);
      assert.equal(result.excluded, 1);
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
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

  it("falls back to bounded safe text search when rg is unavailable", async () => {
    const home = join(tmpdir(), `openmates-remote-access-no-rg-${Date.now()}-${Math.random().toString(16).slice(2)}`);
    const repo = join(home, "repo");
    mkdirSync(join(repo, "src"), { recursive: true });
    writeFileSync(join(repo, "src", "match.ts"), "first line\nremoteDemo value\n");
    writeFileSync(join(repo, ".env"), "remoteDemo=secret\n");
    try {
      const missingExecutable = Object.assign(new Error("spawn rg ENOENT"), { code: "ENOENT" });
      const result = await searchRemoteSource({
        query: "remoteDemo",
        sourceRoot: repo,
        runRg: async () => { throw missingExecutable; },
      });

      assert.deepEqual(result.matches, [{ path: "src/match.ts", line: 2, snippet: "remoteDemo value\n" }]);
      assert.equal(result.omitted, 0);
      assert.ok(result.excluded >= 1);
    } finally {
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
    const home = join(tmpdir(), `openmates-remote-limits-${Date.now()}-${Math.random().toString(16).slice(2)}`);
    mkdirSync(home, { recursive: true });
    try {
      await assert.rejects(
        () => searchRemoteSource({ query: "Project", sourceRoot: home, maxResults: Number.NaN, runRg: async () => "" }),
        (error: unknown) => error instanceof ProjectSearchProtocolError && error.code === "invalid_search_limit",
      );
      await assert.rejects(
        () => searchRemoteSource({ query: "Project", sourceRoot: home, maxResults: 101, runRg: async () => "" }),
        (error: unknown) => error instanceof ProjectSearchProtocolError && error.code === "invalid_search_limit",
      );
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
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

  it("does not scan nested repositories when an explicit source path is approved", () => {
    const roots = ["/approved/repository"];
    const explicit = remoteAccessHostingCandidates(roots, true, () => {
      throw new Error("recursive discovery must not run for --path");
    });
    assert.deepEqual(explicit, { candidateRoots: roots, permissionDenied: [] });
    const automatic = remoteAccessHostingCandidates(roots, false, () => ({
      repositories: [{ rootPath: "/approved/repository/nested", displayName: "nested" }],
      permissionDenied: [],
    }));
    assert.deepEqual(automatic.candidateRoots, ["/approved/repository/nested"]);
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
    mkdirSync(join(root, "src", "nested"));
    writeFileSync(join(root, "src", "safe.ts"), "export const safe = true;\n");
    writeFileSync(join(root, "src", ".hidden"), "PRIVATE_CHILD_SENTINEL\n");
    writeFileSync(join(root, "src", ".gitignore"), "secret.txt\n");
    writeFileSync(join(root, "src", "secret.txt"), "NESTED_IGNORED_SENTINEL\n");
    writeFileSync(join(root, ".env"), "SECRET=value\n");
    writeFileSync(join(root, "binary.dat"), Buffer.from([0, 1, 2, 3]));
    writeFileSync(join(root, "image.png"), Buffer.from([137, 80, 78, 71, 0]));
    try {
      const listing = listRemoteAccessDirectory({ sourceRoot: root, relativePath: ".", maxEntries: 10 });
      assert.deepEqual(listing.entries, [
        { path: "binary.dat", kind: "file", sizeBytes: 4 },
        { path: "image.png", kind: "file", previewable: false, sizeBytes: 5 },
        { path: "src", kind: "directory", children: [{ path: "src/nested", kind: "directory" }, { path: "src/safe.ts", kind: "file" }], childFileCount: 1, childFolderCount: 1, childFileSizeBytes: Buffer.byteLength("export const safe = true;\n"), childSummaryTruncated: false },
      ]);
      assert.equal(listing.excluded, 1);
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

  it("pages more than 500 readable entries without returning private or hidden paths", () => {
    const root = join(tmpdir(), `openmates-remote-pages-${Date.now()}-${Math.random().toString(16).slice(2)}`);
    const linkedTarget = `${root}-linked-target`;
    mkdirSync(root, { recursive: true });
    try {
      writeFileSync(join(root, ".gitignore"), "file-0200.txt\n");
      writeFileSync(join(root, ".env"), "SECRET=value\n");
      writeFileSync(join(root, ".hidden"), "hidden\n");
      for (let index = 0; index < 610; index += 1) {
        writeFileSync(join(root, `file-${String(index).padStart(4, "0")}.txt`), "x");
      }
      writeFileSync(linkedTarget, "outside fixture");
      linkSync(linkedTarget, join(root, "linked.txt"));

      const pages = [];
      let cursor: string | undefined;
      do {
        const page = listRemoteAccessDirectory({ sourceRoot: root, relativePath: ".", maxEntries: 200, cursor });
        pages.push(page);
        cursor = page.nextCursor;
      } while (cursor !== undefined);

      assert.deepEqual(pages.map((page) => page.entries.length), [200, 200, 200, 9]);
      assert.deepEqual(pages.map((page) => page.omitted), [409, 209, 9, 0]);
      assert.deepEqual(pages.map((page) => page.truncated), [true, true, true, false]);
      assert.deepEqual(pages.slice(0, -1).map((page) => page.nextCursor),
        ["file-0199.txt", "file-0400.txt", "file-0600.txt"]);
      assert.equal(pages.at(-1)?.nextCursor, undefined);
      const paths = pages.flatMap((page) => page.entries.map((entry) => entry.path));
      assert.equal(paths.length, 609);
      assert.equal(new Set(paths).size, paths.length);
      assert.equal(paths[0], "file-0000.txt");
      assert.equal(paths.at(-1), "file-0609.txt");
      assert.ok(!paths.includes("file-0200.txt"));
      assert.ok(!paths.some((path) => path.startsWith(".") || path === "linked.txt"));
      assert.equal(pages[0]?.excluded, 5);
      assert.equal(pages[1]?.excluded, 2, "only later ignored and hard-linked entries count after the cursor");
    } finally {
      rmSync(root, { recursive: true, force: true });
      rmSync(linkedTarget, { force: true });
    }
  });

  it("rejects invalid directory cursors and page sizes", () => {
    const root = join(tmpdir(), `openmates-remote-cursor-${Date.now()}-${Math.random().toString(16).slice(2)}`);
    mkdirSync(root, { recursive: true });
    try {
      for (const cursor of ["", ".", "..", "../other", "nested/file", "nested\\file", "a\0b", "x".repeat(256), 7]) {
        assert.throws(
          () => listRemoteAccessDirectory({ sourceRoot: root, relativePath: ".", cursor: cursor as string }),
          /cursor must be a valid entry basename/,
        );
      }
      for (const maxEntries of [0, 501, 1.5, NaN, "20"]) {
        assert.throws(
          () => listRemoteAccessDirectory({ sourceRoot: root, relativePath: ".", maxEntries: maxEntries as number }),
          /entry limit must be between 1 and 500/,
        );
      }
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("finds safe folders and files of every extension by case-insensitive name search", async () => {
    const root = join(tmpdir(), `openmates-file-search-${Date.now()}-${Math.random().toString(16).slice(2)}`);
    mkdirSync(join(root, "DesignAssets"), { recursive: true });
    mkdirSync(join(root, ".HiddenDesign"));
    writeFileSync(join(root, "DesignAssets", "logo.PNG"), Buffer.from([0, 1, 2]));
    writeFileSync(join(root, "Design.pdf"), Buffer.from([0, 1, 2]));
    writeFileSync(join(root, "design.bin"), Buffer.from([0, 1, 2]));
    writeFileSync(join(root, ".HiddenDesign", "secret.pdf"), "hidden");
    writeFileSync(join(root, ".gitignore"), "ignored-design.pdf\n");
    writeFileSync(join(root, "ignored-design.pdf"), "ignored");
    writeFileSync(join(root, ".env"), "secret");
    const linkedTarget = `${root}-hardlink-target`;
    writeFileSync(linkedTarget, "linked");
    linkSync(linkedTarget, join(root, "linked-design.pdf"));
    try {
      const expected = [
        { path: "design.bin", kind: "file" },
        { path: "Design.pdf", kind: "file" },
        { path: "DesignAssets", kind: "directory" },
        { path: "DesignAssets/logo.PNG", kind: "file" },
      ];
      const unavailable = Object.assign(new Error("rg unavailable"), { code: "ENOENT" });
      for (const runRg of [runRgCommand, async () => { throw unavailable; }]) {
        const result = await searchRemoteSource({ sourceRoot: root, target: "files", query: "DESIGN", path: ".", runRg });
        assert.deepEqual(result.matches, expected);
        assert.equal(result.omitted, 0);
        const rootPriority = await searchRemoteSource({
          sourceRoot: root, target: "files", query: "DESIGN", path: ".", priorityPath: ".", runRg,
        });
        assert.deepEqual(rootPriority.matches, expected);
        const bounded = await searchRemoteSource({ sourceRoot: root, target: "files", query: "DESIGN", path: ".", maxResults: 2, runRg });
        assert.deepEqual(bounded.matches, expected.slice(0, 2));
        assert.equal(bounded.omitted, 2);
        assert.equal(bounded.truncated, true);
      }
    } finally {
      rmSync(root, { recursive: true, force: true });
      rmSync(linkedTarget, { force: true });
    }
  });

  it("prioritizes the current folder before the 100-result filename cap", async () => {
    const root = join(tmpdir(), `openmates-priority-search-${Date.now()}-${Math.random().toString(16).slice(2)}`);
    mkdirSync(join(root, "a-elsewhere"), { recursive: true });
    mkdirSync(join(root, "z-current"));
    try {
      for (let index = 0; index < 105; index += 1) {
        writeFileSync(join(root, "a-elsewhere", `match-${String(index).padStart(3, "0")}.txt`), "x");
      }
      writeFileSync(join(root, "z-current", "match-local.pdf"), "pdf");
      const unavailable = Object.assign(new Error("rg unavailable"), { code: "ENOENT" });
      for (const runRg of [runRgCommand, async () => { throw unavailable; }]) {
        const result = await searchRemoteSource({
          sourceRoot: root, target: "files", query: "match", path: ".", priorityPath: "z-current",
          maxResults: 100, runRg,
        });
        assert.deepEqual(result.matches[0], { path: "z-current/match-local.pdf", kind: "file" });
        assert.equal(result.matches.length, 100);
        assert.equal(result.omitted, 6);
      }
      await assert.rejects(
        () => searchRemoteSource({ sourceRoot: root, target: "files", query: "match", path: ".", priorityPath: "../outside", runRg: runRgCommand }),
        /invalid_search_path/,
      );
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("ranks direct children before more than 100 matching descendants", async () => {
    const root = join(tmpdir(), `openmates-direct-child-search-${Date.now()}-${Math.random().toString(16).slice(2)}`);
    mkdirSync(join(root, "current", "a-nested"), { recursive: true });
    try {
      for (let index = 0; index < 105; index += 1) {
        writeFileSync(join(root, "current", "a-nested", `match-${String(index).padStart(3, "0")}.txt`), "x");
      }
      writeFileSync(join(root, "current", "match-direct.pdf"), "pdf");
      const unavailable = Object.assign(new Error("rg unavailable"), { code: "ENOENT" });
      for (const runRg of [runRgCommand, async () => { throw unavailable; }]) {
        const result = await searchRemoteSource({
          sourceRoot: root, target: "files", query: "match", path: ".", priorityPath: "current",
          maxResults: 100, runRg,
        });
        assert.deepEqual(result.matches[0], { path: "current/match-direct.pdf", kind: "file" });
        assert.equal(result.matches.length, 100);
        assert.equal(result.omitted, 6);
      }
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("returns bounded safe filename matches when the source exceeds the alias scan limit", async () => {
    const root = join(tmpdir(), `openmates-large-file-search-${Date.now()}-${Math.random().toString(16).slice(2)}`);
    mkdirSync(join(root, "z-current"), { recursive: true });
    try {
      writeFileSync(join(root, "z-current", "match-local.pdf"), "pdf");
      for (let index = 0; index < 10_001; index += 1) {
        writeFileSync(join(root, `filler-${String(index).padStart(5, "0")}.txt`), "x");
      }
      const result = await searchRemoteSource({
        sourceRoot: root, target: "files", query: "match", path: ".", priorityPath: "z-current",
        runRg: async () => { throw new Error("rg must not run after truncated alias scan"); },
      });
      assert.deepEqual(result.matches[0], { path: "z-current/match-local.pdf", kind: "file" });
      assert.equal(result.truncated, true);
      assert.ok(result.omitted >= 1);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("bounds immediate folder summaries without reading file contents", () => {
    const root = join(tmpdir(), `openmates-folder-summary-${Date.now()}-${Math.random().toString(16).slice(2)}`);
    mkdirSync(join(root, "bulk"), { recursive: true });
    try {
      for (let index = 0; index < 201; index += 1) {
        writeFileSync(join(root, "bulk", `file-${String(index).padStart(3, "0")}.txt`), "x");
      }
      const folder = listRemoteAccessDirectory({ sourceRoot: root, relativePath: "." }).entries.find((entry) => entry.path === "bulk");
      assert.equal(folder?.childFileCount, 200);
      assert.equal(folder?.childFolderCount, 0);
      assert.equal(folder?.childFileSizeBytes, 200);
      assert.equal(folder?.children?.length, 3);
      assert.equal(folder?.childSummaryTruncated, true);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  // contract-test: supporting surface=cli assertions=projects.files.private-path-deny,projects.files.no-server-decryption-authority
  it("reads a large raster image in bounded chunks and denies ignored or unsupported files", () => {
    const root = join(tmpdir(), `openmates-remote-image-${Date.now()}-${Math.random().toString(16).slice(2)}`);
    mkdirSync(root, { recursive: true });
    const png = Buffer.alloc(300_000, 7);
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]).copy(png);
    writeFileSync(join(root, "diagram.png"), png);
    writeFileSync(join(root, "unsafe.svg"), '<svg onload="alert(1)"/>');
    writeFileSync(join(root, ".gitignore"), "ignored.png\n");
    writeFileSync(join(root, "ignored.png"), png);
    writeFileSync(join(root, "oversized.png"), Buffer.concat([png.subarray(0, 8), Buffer.alloc(2 * 1024 * 1024)]));
    try {
      const first = readRemoteAccessImageChunk({ sourceRoot: root, relativePath: "diagram.png", offset: 0 });
      const second = readRemoteAccessImageChunk({ sourceRoot: root, relativePath: "diagram.png", offset: 128 * 1024 });
      const third = readRemoteAccessImageChunk({ sourceRoot: root, relativePath: "diagram.png", offset: 256 * 1024 });
      assert.equal(first.mime_type, "image/png");
      assert.equal(first.size_bytes, png.length);
      assert.equal(first.content_hash, second.content_hash);
      assert.equal(second.content_hash, third.content_hash);
      assert.deepEqual(Buffer.concat([first, second, third].map((chunk) => Buffer.from(chunk.content_base64, "base64"))), png);
      assert.throws(() => readRemoteAccessImageChunk({ sourceRoot: root, relativePath: "diagram.png", offset: 1 }), /offset is invalid/);
      assert.throws(() => readRemoteAccessImageChunk({ sourceRoot: root, relativePath: "unsafe.svg", offset: 0 }), /unsupported/);
      assert.throws(() => readRemoteAccessImageChunk({ sourceRoot: root, relativePath: "oversized.png", offset: 0 }), /safe image limit/);
      assert.throws(() => readRemoteAccessImageChunk({ sourceRoot: root, relativePath: "ignored.png", offset: 0 }), /ignored/);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  // contract-test: supporting surface=cli assertions=projects.files.connected-embed-previews,projects.files.private-path-deny
  it("downloads exact binary and empty files in bounded chunks under the source path policy", () => {
    const root = join(tmpdir(), `openmates-remote-download-${Date.now()}-${Math.random().toString(16).slice(2)}`);
    mkdirSync(root, { recursive: true });
    const binary = Buffer.alloc(280_000);
    for (let index = 0; index < binary.length; index += 1) binary[index] = index % 251;
    writeFileSync(join(root, "unknown.dat"), binary);
    writeFileSync(join(root, "empty.dat"), Buffer.alloc(0));
    writeFileSync(join(root, ".gitignore"), "ignored.dat\n");
    writeFileSync(join(root, "ignored.dat"), binary);
    const large = Buffer.alloc(5 * 1024 * 1024 + 17);
    for (let index = 0; index < large.length; index += 1) large[index] = index % 251;
    writeFileSync(join(root, "large.dat"), large);
    try {
      const chunks = [0, 128 * 1024, 256 * 1024].map((offset) =>
        readRemoteAccessFileChunk({ sourceRoot: root, relativePath: "unknown.dat", offset }));
      assert.equal(new Set(chunks.map((chunk) => chunk.file_identity)).size, 1);
      assert.deepEqual(Buffer.concat(chunks.map((chunk) => Buffer.from(chunk.content_base64, "base64"))), binary);
      const empty = readRemoteAccessFileChunk({ sourceRoot: root, relativePath: "empty.dat", offset: 0 });
      assert.equal(empty.size_bytes, 0);
      assert.equal(empty.content_base64, "");
      assert.throws(() => readRemoteAccessFileChunk({ sourceRoot: root, relativePath: "unknown.dat", offset: 1 }), /offset is invalid/);
      assert.throws(() => readRemoteAccessFileChunk({ sourceRoot: root, relativePath: "ignored.dat", offset: 0 }), /ignored/);
      const largeChunks = Array.from({ length: Math.ceil(large.length / (128 * 1024)) }, (_, index) =>
        readRemoteAccessFileChunk({ sourceRoot: root, relativePath: "large.dat", offset: index * 128 * 1024 }));
      assert.equal(new Set(largeChunks.map((chunk) => chunk.file_identity)).size, 1);
      assert.ok(largeChunks.every((chunk) => chunk.size_bytes === large.length));
      assert.ok(largeChunks.every((chunk) => Buffer.from(chunk.content_base64, "base64").length <= 128 * 1024));
      assert.ok(largeChunks.every((chunk) => chunk.chunk_hash === createHash("sha256")
        .update(Buffer.from(chunk.content_base64, "base64")).digest("hex")));
      assert.deepEqual(Buffer.concat(largeChunks.map((chunk) => Buffer.from(chunk.content_base64, "base64"))), large);
      assert.throws(() => readRemoteAccessFileChunk({ sourceRoot: root, relativePath: "large.dat", offset: largeChunks.length * 128 * 1024 }), /offset is invalid/);
    } finally {
      rmSync(root, { recursive: true, force: true });
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

  // contract-test: supporting surface=cli assertions=projects.files.private-path-deny
  it("reports a direct private file read with the stable public protected-path code", () => {
    const home = join(tmpdir(), `openmates-remote-private-${Date.now()}-${Math.random().toString(16).slice(2)}`);
    const root = join(home, "repo");
    mkdirSync(join(root, ".openmates"), { recursive: true });
    mkdirSync(join(root, "private"), { recursive: true });
    writeFileSync(
      join(root, ".openmates", "permissions.yml"),
      "schema_version: 1\npresets: []\nfile_access:\n  private_paths:\n    - private/\n",
    );
    writeFileSync(join(root, "private", "customer-export.csv"), "PRIVATE_DUMMY_CANARY\n");
    try {
      let readError: unknown;
      assert.throws(
        () => readRemoteAccessTextFile({ sourceRoot: root, relativePath: "private/customer-export.csv" }),
        (error: unknown) => {
          readError = error;
          return true;
        },
      );
      assert.equal(remoteAccessOperationErrorCode(readError), "protected_path");
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
