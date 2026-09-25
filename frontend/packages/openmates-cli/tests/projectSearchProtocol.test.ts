/**
 * Contract coverage for bounded hosted/remote Project file search semantics.
 * Test repositories are created below the system temporary directory.
 * Run: node --test --experimental-strip-types --loader ./tests/loader.mjs tests/projectSearchProtocol.test.ts
 */

import assert from "node:assert/strict";
import { chmodSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, it } from "node:test";

import {
  ProjectSearchProtocolError,
  matchesProjectSearchGlob,
  matchesProjectSearchQuery,
  normalizeProjectSearchRequest,
} from "../../ui/src/utils/projectSearchProtocol.ts";
import {
  readRemoteAccessTextFile,
  runRgCommand,
  searchRemoteSource,
} from "../src/remoteAccess.ts";

function temporaryRepository(label: string): { home: string; root: string } {
  const home = join(tmpdir(), `openmates-${label}-${Date.now()}-${Math.random().toString(16).slice(2)}`);
  const root = join(home, "repo");
  mkdirSync(root, { recursive: true });
  return { home, root };
}

describe("Project search protocol", () => {
  // contract-test: supporting surface=cli assertions=projects.files.search-scoped,projects.files.search-consistent
  it("normalizes the typed wire request and matches bounded literal/glob syntax", () => {
    assert.deepEqual(normalizeProjectSearchRequest({ query: "needle", max_results: 7 }), {
      target: "content",
      mode: "literal",
      query: "needle",
      path: ".",
      maxResults: 7,
    });
    assert.equal(matchesProjectSearchGlob("src/nested/file.ts", "src/**/*.ts"), true);
    assert.equal(matchesProjectSearchGlob("src/nested/file.js", "src/**/*.ts"), false);
    assert.equal(matchesProjectSearchQuery("literal [needle]", { mode: "literal", query: "[needle]" }), true);
    assert.throws(
      () => matchesProjectSearchQuery("anything", { mode: "regex", query: ".*" }),
      (error: unknown) => error instanceof ProjectSearchProtocolError && error.code === "regex_search_unavailable",
    );
    assert.throws(
      () => normalizeProjectSearchRequest({ query: "needle", path: "../outside" }),
      (error: unknown) => error instanceof ProjectSearchProtocolError && error.code === "invalid_search_path",
    );
    for (const glob of ["src/[ab].ts", "src/{one,two}.ts"]) {
      assert.throws(
        () => normalizeProjectSearchRequest({ query: "needle", glob }),
        (error: unknown) => error instanceof ProjectSearchProtocolError && error.code === "invalid_search_glob",
      );
    }
  });

  // contract-test: supporting surface=cli assertions=projects.files.search-scoped,projects.files.search-consistent
  it("uses fixed controlled rg arguments and filters credentials without excluding ordinary source/config", async () => {
    const { home, root } = temporaryRepository("search-rg-contract");
    mkdirSync(join(root, "src"), { recursive: true });
    const calls: Array<{ args: string[]; cwd: string; cap?: number }> = [];
    try {
      const result = await searchRemoteSource({
        sourceRoot: root,
        query: "needle",
        path: "src",
        glob: "**/*.ts",
        maxResults: 2,
        runRg: async (args, cwd, cap) => {
          calls.push({ args, cwd, cap });
          return [
            { path: "src/auth/session.ts", line: 4, text: "needle auth\n" },
            { path: "src/config.ts", line: 5, text: "needle config\n" },
            { path: ".env", line: 1, text: "needle secret\n" },
            { path: "src/third.ts", line: 6, text: "needle third\n" },
          ].map(({ path, line, text }) => JSON.stringify({
            type: "match",
            data: { path: { text: path }, line_number: line, lines: { text } },
          })).join("\n");
        },
      });

      assert.equal(calls[0]?.cwd, root);
      assert.equal(calls[0]?.cap, 3);
      assert.deepEqual(calls[0]?.args.slice(0, 4), ["--no-config", "--hidden", "--color", "never"]);
      assert.ok(calls[0]?.args.includes("--fixed-strings"));
      assert.ok(calls[0]?.args.includes("!.env"));
      assert.ok(!calls[0]?.args.includes("!package.json"));
      assert.ok(!calls[0]?.args.includes("!Dockerfile"));
      assert.ok(!calls[0]?.args.includes("!**/auth/**"));
      assert.deepEqual(calls[0]?.args.slice(-6), ["--glob", "**/*.ts", "--regexp", "needle", "--", "src"]);
      assert.deepEqual(result.matches.map(({ path }) => path), ["src/auth/session.ts", "src/config.ts"]);
      assert.deepEqual({ omitted: result.omitted, excluded: result.excluded, truncated: result.truncated }, {
        omitted: 1,
        excluded: 1,
        truncated: true,
      });
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });

  // contract-test: supporting surface=cli assertions=projects.files.search-scoped,projects.files.search-consistent
  it("supports filename search and preserves literal semantics when rg is absent", async () => {
    const { home, root } = temporaryRepository("search-fallback");
    mkdirSync(join(root, "src", "auth"), { recursive: true });
    writeFileSync(join(root, "src", "auth", "session.ts"), "export const marker = 'needle';\n");
    writeFileSync(join(root, "src", "needle-file.ts"), "ordinary source\n");
    writeFileSync(join(root, "package.json"), "{\"marker\":\"needle\"}\n");
    writeFileSync(join(root, "Dockerfile"), "# needle\n");
    writeFileSync(join(root, ".env"), "TOKEN=needle\n");
    const unavailable = Object.assign(new Error("spawn rg ENOENT"), { code: "ENOENT" });
    try {
      const files = await searchRemoteSource({
        sourceRoot: root,
        target: "files",
        mode: "literal",
        query: "needle",
        path: "src",
        glob: "**/*.ts",
        runRg: async () => { throw unavailable; },
      });
      assert.deepEqual(files.matches, [{ path: "src/needle-file.ts" }]);

      const content = await searchRemoteSource({
        sourceRoot: root,
        target: "content",
        mode: "literal",
        query: "needle",
        runRg: async () => { throw unavailable; },
      });
      assert.deepEqual(
        new Set(content.matches.map(({ path }) => path)),
        new Set(["Dockerfile", "package.json", "src/auth/session.ts"]),
      );
      assert.ok(content.excluded >= 1);
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });

  // contract-test: supporting surface=cli assertions=projects.files.search-scoped,projects.files.search-consistent
  it("searches filenames through bounded rg enumeration without treating the query as a flag", async () => {
    const { home, root } = temporaryRepository("filename-rg");
    const calls: string[][] = [];
    try {
      const result = await searchRemoteSource({
        sourceRoot: root,
        target: "files",
        mode: "literal",
        query: "--token[$()]",
        maxResults: 1,
        runRg: async (args) => {
          calls.push(args);
          return "src/--token[$()].ts\nsrc/other.ts\n.env\n";
        },
      });
      assert.ok(calls[0]?.includes("--files"));
      assert.deepEqual(calls[0]?.slice(-2), ["--", "."]);
      assert.ok(!calls[0]?.includes("--token[$()]"));
      assert.deepEqual(result.matches, [{ path: "src/--token[$()].ts" }]);
      assert.equal(result.excluded, 1);
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });

  // contract-test: supporting surface=cli assertions=projects.files.search-consistent
  it("reports regex_search_unavailable rather than changing regex into literal fallback", async () => {
    const { home, root } = temporaryRepository("search-no-regex");
    const unavailable = Object.assign(new Error("spawn rg ENOENT"), { code: "ENOENT" });
    try {
      await assert.rejects(
        () => searchRemoteSource({
          sourceRoot: root,
          target: "content",
          mode: "regex",
          query: "needle.*value",
          runRg: async () => { throw unavailable; },
        }),
        (error: unknown) => error instanceof ProjectSearchProtocolError && error.code === "regex_search_unavailable",
      );
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });

  // contract-test: supporting surface=cli assertions=projects.files.search-scoped,projects.files.search-consistent
  it("returns one deterministic byte/line bounded read and withholds a base digest for excerpts", () => {
    const { home, root } = temporaryRepository("bounded-read");
    writeFileSync(join(root, "split.txt"), "abc😀xyz");
    writeFileSync(join(root, "many-lines.txt"), `${Array.from({ length: 4_001 }, () => "line").join("\n")}\n`);
    writeFileSync(join(root, "package.json"), "{}\n");
    writeFileSync(join(root, ".env"), "TOKEN=secret\n");
    try {
      const byteBounded = readRemoteAccessTextFile({ sourceRoot: root, relativePath: "split.txt", maxBytes: 6 });
      assert.deepEqual(byteBounded, {
        content: "abc",
        truncated: true,
        sizeBytes: 10,
        lineCount: 1,
        expected_base: null,
      });
      const lineBounded = readRemoteAccessTextFile({ sourceRoot: root, relativePath: "many-lines.txt" });
      assert.equal(lineBounded.lineCount, 4_000);
      assert.equal(lineBounded.truncated, true);
      assert.equal(lineBounded.expected_base, null);
      assert.match(readRemoteAccessTextFile({ sourceRoot: root, relativePath: "package.json" }).expected_base ?? "", /^[a-f0-9]{64}$/);
      assert.throws(() => readRemoteAccessTextFile({ sourceRoot: root, relativePath: ".env" }), /protected/);
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });

  // contract-test: supporting surface=cli assertions=projects.files.search-scoped
  it("bounds rg pending output and does not inherit ripgrep configuration", async () => {
    const { home, root } = temporaryRepository("search-process");
    const bin = join(home, "bin");
    mkdirSync(bin, { recursive: true });
    const fakeRg = join(bin, "rg");
    writeFileSync(fakeRg, `#!/usr/bin/env node
if (process.env.RIPGREP_CONFIG_PATH) process.exit(9);
if (!process.argv.includes("--no-config")) process.exit(8);
process.stdout.write("x".repeat(70000));
`);
    chmodSync(fakeRg, 0o755);
    const previousPath = process.env.PATH;
    const previousConfig = process.env.RIPGREP_CONFIG_PATH;
    process.env.PATH = `${bin}:${previousPath ?? ""}`;
    process.env.RIPGREP_CONFIG_PATH = join(home, "host-rg-config");
    try {
      await assert.rejects(
        () => runRgCommand(["--no-config", "needle"], root),
        /output exceeded its byte limit/,
      );
    } finally {
      process.env.PATH = previousPath;
      if (previousConfig === undefined) delete process.env.RIPGREP_CONFIG_PATH;
      else process.env.RIPGREP_CONFIG_PATH = previousConfig;
      rmSync(home, { recursive: true, force: true });
    }
  });
});
