/** Focused coverage for Project ignore/private path enforcement. */

import assert from "node:assert/strict";
import { linkSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, it } from "node:test";

import { createProjectPathPolicy } from "../../ui/src/utils/projectPathPolicy.ts";
import { loadProjectPathPolicy, ProjectPathAccessError } from "../src/projectPathPolicy.ts";
import { listRemoteAccessDirectory, readRemoteAccessTextFile, searchRemoteSource } from "../src/remoteAccess.ts";

function fixture(label: string): { home: string; root: string; state: string } {
  const home = join(tmpdir(), `openmates-path-policy-${label}-${Date.now()}-${Math.random().toString(16).slice(2)}`);
  const root = join(home, "repo");
  const state = join(home, "state");
  mkdirSync(root, { recursive: true });
  return { home, root, state };
}

describe("Project path policy", () => {
  // contract-test: supporting surface=cli assertions=projects.files.ignored-exact-inclusion,projects.files.search-consistent
  it("applies nested Git rules, negation, parent exclusion, and Linux case sensitivity", () => {
    const policy = createProjectPathPolicy({
      ignoreFiles: [
        { path: ".gitignore", content: "*.log\n!important.log\nbuild/\nFoo.txt\n" },
        { path: "src/.gitignore", content: "!keep.log\n*.tmp\n" },
        { path: "build/.gitignore", content: "!visible.txt\n" },
      ],
      privatePaths: [],
    });

    assert.equal(policy.isIgnored("debug.log"), true);
    assert.equal(policy.isIgnored("important.log"), false);
    assert.equal(policy.isIgnored("src/debug.log"), true);
    assert.equal(policy.isIgnored("src/keep.log"), false);
    assert.equal(policy.isIgnored("src/cache.tmp"), true);
    assert.equal(policy.isIgnored("build/visible.txt"), true);
    assert.equal(policy.isIgnored("Foo.txt"), true);
    assert.equal(policy.isIgnored("foo.txt"), false);
  });

  // contract-test: supporting surface=cli assertions=projects.files.ignored-exact-inclusion,projects.files.search-consistent
  it("loads parent and nested ignore files for a selected repository subfolder and plain folders", () => {
    const item = fixture("nested");
    const selected = join(item.root, "selected");
    mkdirSync(join(item.root, ".git"));
    mkdirSync(join(selected, "nested"), { recursive: true });
    writeFileSync(join(item.root, ".gitignore"), "*.secret\n!selected/public.secret\n");
    writeFileSync(join(selected, ".gitignore"), "*.tmp\n!keep.tmp\n");
    writeFileSync(join(selected, "nested", ".gitignore"), "generated.txt\n");
    try {
      const policy = loadProjectPathPolicy(selected, { stateDirectory: item.state, discoverNestedIgnoreFiles: true });
      assert.equal(policy.isIgnored("hidden.secret"), true);
      assert.equal(policy.isIgnored("public.secret"), false);
      assert.equal(policy.isIgnored("cache.tmp"), true);
      assert.equal(policy.isIgnored("keep.tmp"), false);
      assert.equal(policy.isIgnored("nested/generated.txt"), true);

      rmSync(join(item.root, ".git"), { recursive: true });
      const plainPolicy = loadProjectPathPolicy(selected, { stateDirectory: item.state, discoverNestedIgnoreFiles: true });
      assert.equal(plainPolicy.isIgnored("cache.tmp"), true);
      assert.equal(plainPolicy.isIgnored("nested/generated.txt"), true);
    } finally {
      rmSync(item.home, { recursive: true, force: true });
    }
  });

  // contract-test: supporting surface=cli assertions=projects.files.ignored-exact-inclusion,projects.files.search-consistent
  it("prunes ignored dependency trees before bounded nested-ignore discovery", () => {
    const item = fixture("ignored-dependencies");
    mkdirSync(join(item.root, "node_modules"));
    writeFileSync(join(item.root, ".gitignore"), "node_modules/\n");
    for (let index = 0; index < 20; index += 1) {
      mkdirSync(join(item.root, "node_modules", `package-${index}`));
      writeFileSync(join(item.root, "node_modules", `package-${index}`, ".gitignore"), "dist/\n");
    }
    try {
      const policy = loadProjectPathPolicy(item.root, {
        stateDirectory: item.state,
        discoverNestedIgnoreFiles: true,
        maxEntries: 5,
      });
      assert.equal(policy.isIgnored("node_modules/package-19/index.js"), true);
    } finally {
      rmSync(item.home, { recursive: true, force: true });
    }
  });

  // contract-test: supporting surface=cli assertions=projects.files.private-path-deny
  it("persists additive private rules outside the source and denies hardlink aliases", () => {
    const item = fixture("private-alias");
    mkdirSync(join(item.root, "secrets"));
    writeFileSync(join(item.root, "secrets", "token.txt"), "private\n");
    linkSync(join(item.root, "secrets", "token.txt"), join(item.root, "public-copy.txt"));
    try {
      const initial = loadProjectPathPolicy(item.root, {
        trustedPrivatePaths: ["secrets/**"],
        stateDirectory: item.state,
      });
      assert.equal(initial.isPrivate("secrets/token.txt"), true);
      assert.equal(initial.isPrivate("public-copy.txt"), false);
      const retained = loadProjectPathPolicy(item.root, { stateDirectory: item.state });
      assert.equal(retained.isPrivate("secrets/token.txt"), true);
      assert.equal(retained.privateDigest, initial.privateDigest);
      assert.throws(
        () => readRemoteAccessTextFile({
          sourceRoot: item.root,
          relativePath: "public-copy.txt",
          stateDirectory: item.state,
        }),
        /protected hardlink/,
      );
    } finally {
      rmSync(item.home, { recursive: true, force: true });
    }
  });

  // contract-test: supporting surface=cli assertions=projects.files.ignored-exact-inclusion,projects.files.private-path-deny
  it("requires an exact trusted callback for ignored reads and never lets it override private paths", () => {
    const item = fixture("ignored-read");
    writeFileSync(join(item.root, ".gitignore"), "notes.txt\n");
    writeFileSync(join(item.root, "notes.txt"), "approved only\n");
    writeFileSync(join(item.root, ".env"), "TOKEN=private\n");
    try {
      assert.throws(
        () => readRemoteAccessTextFile({ sourceRoot: item.root, relativePath: "notes.txt", stateDirectory: item.state }),
        (error: unknown) => error instanceof ProjectPathAccessError && error.code === "ignored_path_requires_approval",
      );
      assert.equal(readRemoteAccessTextFile({
        sourceRoot: item.root,
        relativePath: "notes.txt",
        stateDirectory: item.state,
        isIgnoredReadApproved: (path) => path === "notes.txt",
      }).content, "approved only\n");
      assert.throws(
        () => readRemoteAccessTextFile({
          sourceRoot: item.root,
          relativePath: ".env",
          stateDirectory: item.state,
          isIgnoredReadApproved: () => true,
        }),
        (error: unknown) => error instanceof ProjectPathAccessError && error.code === "private_path",
      );
    } finally {
      rmSync(item.home, { recursive: true, force: true });
    }
  });

  // contract-test: supporting surface=cli assertions=projects.files.search-scoped,projects.files.private-path-deny
  it("excludes private paths in rg arguments before content search and in fallback/listing", async () => {
    const item = fixture("search-private");
    mkdirSync(join(item.root, "private"));
    writeFileSync(join(item.root, "private", "secret.txt"), "needle\n");
    writeFileSync(join(item.root, "visible.txt"), "needle\n");
    writeFileSync(join(item.root, "linked-source.txt"), "needle\n");
    linkSync(join(item.root, "linked-source.txt"), join(item.root, "linked-alias.txt"));
    try {
      const result = await searchRemoteSource({
        sourceRoot: item.root,
        query: "needle",
        userProtectedPatterns: ["private/**"],
        stateDirectory: item.state,
        runRg: async (args) => {
          const exclusion = args.findIndex((item) => item === "!private/**");
          assert.ok(exclusion > 0);
          assert.equal(args[exclusion - 1], "--iglob");
          assert.ok(args.includes("!linked-source.txt"));
          assert.ok(args.includes("!linked-alias.txt"));
          return [
            JSON.stringify({ type: "match", data: { path: { text: "private/secret.txt" }, line_number: 1, lines: { text: "needle\n" } } }),
            JSON.stringify({ type: "match", data: { path: { text: "visible.txt" }, line_number: 1, lines: { text: "needle\n" } } }),
          ].join("\n");
        },
      });
      assert.deepEqual(result.matches.map(({ path }) => path), ["visible.txt"]);
      assert.deepEqual(
        listRemoteAccessDirectory({ sourceRoot: item.root, relativePath: ".", stateDirectory: item.state }).entries,
        [{ path: "visible.txt", kind: "file" }],
      );
    } finally {
      rmSync(item.home, { recursive: true, force: true });
    }
  });
});
