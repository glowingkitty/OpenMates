import { describe, expect, it, vi } from "vitest";
import {
  executeHostedProjectFileJob,
  type HostedProjectFile,
  type HostedProjectFileAdapter,
  type HostedProjectFileHead,
} from "../hostedProjectFileExecutor";
import type { ProjectFileJob } from "../projectFileJobExecutor";

const projectId = "72dcdd3a-c264-4291-812b-02e820ca88c9";
const chatId = "0b59bafd-14d8-46b7-94ab-fcf0df0fbb10";

function job(operation: ProjectFileJob["operation"], args: Record<string, unknown>): ProjectFileJob {
  return {
    protocol_version: 1,
    operation_id: `fixture-${operation}`,
    chat_id: chatId,
    project_id: projectId,
    operation,
    arguments: args,
    lease_token: "fixture-lease-token-long",
    lease_generation: 1,
    lease_expires_at: Math.floor(Date.now() / 1000) + 60,
  };
}

function createAdapter(
  files: HostedProjectFile[],
  contents: Record<string, string>,
  overrides: Partial<HostedProjectFileAdapter> = {},
): HostedProjectFileAdapter & { reads: string[] } {
  const reads: string[] = [];
  return {
    projectId,
    projectKey: new Uint8Array(32).fill(7),
    chatKey: new Uint8Array(32).fill(8),
    listFiles: async () => files,
    readHead: async (embedId): Promise<HostedProjectFileHead> => {
      reads.push(embedId);
      if (!(embedId in contents)) throw new Error("missing fixture head");
      return {
        embedKey: new Uint8Array(32),
        content: { code: contents[embedId] },
        revision: 1,
        hasInitialHistory: true,
      };
    },
    encrypt: async () => "ciphertext",
    wrap: async () => "wrapped-key",
    encodeContent: async () => "encoded",
    commit: async () => ({ status: "committed", current_revision: 1 }),
    receipt: async () => null,
    ...overrides,
    reads,
  };
}

// contract-test: supporting surface=cli assertions=projects.files.ignored-exact-inclusion,projects.files.private-path-deny
describe("hosted Project path policy", () => {
  it("applies nested ignore negation and hides private metadata before content search", async () => {
    const files = [
      { path: ".gitignore", embedId: "root-ignore" },
      { path: "src/.gitignore", embedId: "nested-ignore" },
      { path: ".openmates/permissions.yml", embedId: "permissions" },
      { path: "README.md", embedId: "readme" },
      { path: "debug.log", embedId: "debug" },
      { path: "build/output.js", embedId: "build" },
      { path: "build/.gitignore", embedId: "ignored-nested-control" },
      { path: "src/generated/drop.ts", embedId: "drop" },
      { path: "src/generated/keep.ts", embedId: "keep" },
      { path: "vault/passwords.txt", embedId: "vault-secret" },
      { path: "internal/plan.txt", embedId: "settings-secret" },
      { path: "internal/hidden/.gitignore", embedId: "private-nested-control" },
    ];
    const adapter = createAdapter(files, {
      "root-ignore": "*.log\nbuild/\n",
      "nested-ignore": "generated/*\n!generated/keep.ts\n",
      permissions: "file_access:\n  private_paths:\n    - vault/**\n",
      readme: "needle\n",
      debug: "needle\n",
      build: "needle\n",
      "ignored-nested-control": "!output.js\n",
      drop: "needle\n",
      keep: "needle\n",
      "vault-secret": "needle secret\n",
      "settings-secret": "needle secret\n",
      "private-nested-control": "!plan.txt\n",
    }, { privatePaths: ["internal/**"] });

    const listed = await executeHostedProjectFileJob(adapter, job("list", { path: "." }));
    const paths = (listed.entries as Array<{ path: string }>).map((entry) => entry.path);
    expect(paths).toContain("README.md");
    expect(paths).toContain("src/generated/keep.ts");
    expect(paths).not.toContain("debug.log");
    expect(paths).not.toContain("build/output.js");
    expect(paths).not.toContain("src/generated/drop.ts");
    expect(paths).not.toContain("vault/passwords.txt");
    expect(paths).not.toContain("internal/plan.txt");
    expect(paths).not.toContain("internal/hidden/.gitignore");
    expect(paths).not.toContain(".openmates/permissions.yml");
    expect(adapter.reads).not.toContain("ignored-nested-control");
    expect(adapter.reads).not.toContain("private-nested-control");

    adapter.reads.length = 0;
    const searched = await executeHostedProjectFileJob(adapter, job("search", {
      query: "needle",
      target: "content",
      mode: "literal",
      path: ".",
      max_results: 20,
    }));
    expect((searched.matches as Array<{ path: string }>).map((match) => match.path)).toEqual([
      "README.md",
      "src/generated/keep.ts",
    ]);
    expect(adapter.reads).not.toContain("debug");
    expect(adapter.reads).not.toContain("build");
    expect(adapter.reads).not.toContain("ignored-nested-control");
    expect(adapter.reads).not.toContain("drop");
    expect(adapter.reads).not.toContain("vault-secret");
    expect(adapter.reads).not.toContain("settings-secret");
    expect(adapter.reads).not.toContain("private-nested-control");
  });

  // contract-test: supporting surface=cli assertions=projects.files.private-path-deny
  it("taints every alias of an embed linked through protected metadata", async () => {
    const adapter = createAdapter([
      { path: ".env", embedId: "shared-private-head" },
      { path: "src/alias.ts", embedId: "shared-private-head" },
      { path: "src/allowed.ts", embedId: "allowed-head" },
    ], {
      "shared-private-head": "needle secret\n",
      "allowed-head": "needle allowed\n",
    });

    const listed = await executeHostedProjectFileJob(adapter, job("list", { path: "." }));
    expect((listed.entries as Array<{ path: string }>).map((entry) => entry.path)).toEqual([
      "src/allowed.ts",
    ]);

    adapter.reads.length = 0;
    const searched = await executeHostedProjectFileJob(adapter, job("search", {
      query: "needle",
      target: "content",
      mode: "literal",
      path: ".",
      max_results: 20,
    }));
    expect(searched.matches).toEqual([
      { path: "src/allowed.ts", line: 1, snippet: "needle allowed" },
    ]);
    expect(adapter.reads).toEqual(["allowed-head"]);

    adapter.reads.length = 0;
    await expect(executeHostedProjectFileJob(adapter, job("read_text", { path: "src/alias.ts" })))
      .rejects.toMatchObject({ code: "file_not_found" });
    expect(adapter.reads).toEqual([]);
  });

  // contract-test: supporting surface=cli assertions=projects.files.ignored-exact-inclusion
  it("requires an exact ephemeral grant for an ignored direct read without exposing siblings", async () => {
    const approved = vi.fn(async (path: string) => path === "ignored/one.txt");
    const adapter = createAdapter([
      { path: ".gitignore", embedId: "ignore" },
      { path: "ignored/one.txt", embedId: "one" },
      { path: "ignored/two.txt", embedId: "two" },
    ], {
      ignore: "ignored/*\n",
      one: "first\n",
      two: "second\n",
    }, { isIgnoredReadApproved: approved });

    const included = await executeHostedProjectFileJob(adapter, job("read_text", { path: "ignored/one.txt" }));
    expect(included.content).toBe("first\n");
    expect(approved).toHaveBeenCalledWith("ignored/one.txt", expect.objectContaining({ operation: "read_text" }));

    adapter.reads.length = 0;
    await expect(executeHostedProjectFileJob(adapter, job("read_text", { path: "ignored/two.txt" })))
      .rejects.toMatchObject({ code: "ignored_path_requires_approval" });
    expect(adapter.reads).toEqual(["ignore"]);

    approved.mockClear();
    const listed = await executeHostedProjectFileJob(adapter, job("list", { path: "." }));
    expect((listed.entries as Array<{ path: string }>).map((entry) => entry.path)).not.toContain("ignored/one.txt");
    expect(approved).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=cli assertions=projects.files.private-path-deny
  it("denies private reads and writes before decrypting the target or invoking mutation services", async () => {
    const receipt = vi.fn(async () => null);
    const commit = vi.fn(async () => ({ status: "committed", current_revision: 1 }));
    const approveIgnored = vi.fn(async () => true);
    const adapter = createAdapter([
      { path: ".openmates/permissions.yml", embedId: "permissions" },
      { path: "private/token.txt", embedId: "private-token" },
    ], {
      permissions: "file_access:\n  private_paths:\n    - private/**\n",
      "private-token": "secret\n",
    }, { receipt, commit, isIgnoredReadApproved: approveIgnored });

    await expect(executeHostedProjectFileJob(adapter, job("read_text", { path: "private/token.txt" })))
      .rejects.toMatchObject({ code: "protected_path" });
    expect(adapter.reads).not.toContain("private-token");
    expect(approveIgnored).not.toHaveBeenCalled();

    await expect(executeHostedProjectFileJob(adapter, job("create_file", { path: "private/new.txt" }), {
      operation: "create_file",
      operation_id: "fixture-create_file",
      path: "private/new.txt",
      expected_base: null,
      content: "secret\n",
    })).rejects.toMatchObject({ code: "protected_path" });
    expect(receipt).not.toHaveBeenCalled();
    expect(commit).not.toHaveBeenCalled();

    await expect(executeHostedProjectFileJob(adapter, job("create_file", { path: ".openmates/permissions.yml" }), {
      operation: "create_file",
      operation_id: "fixture-create_file",
      path: ".openmates/permissions.yml",
      expected_base: null,
      content: "file_access: {}\n",
    })).rejects.toMatchObject({ code: "protected_path" });

    await expect(executeHostedProjectFileJob(adapter, job("create_file", { path: ".gitignore" }), {
      operation: "create_file",
      operation_id: "fixture-create_file",
      path: ".gitignore",
      expected_base: null,
      content: "private/\n",
    })).rejects.toMatchObject({ code: "protected_path" });
  });

  // contract-test: supporting surface=cli assertions=projects.files.private-path-deny
  it("fails closed for ambiguous or malformed encrypted policy controls", async () => {
    const duplicate = createAdapter([
      { path: ".openmates/permissions.yml", embedId: "permissions-a" },
      { path: ".openmates/permissions.yml", embedId: "permissions-b" },
      { path: "README.md", embedId: "readme" },
    ], { "permissions-a": "file_access: {}\n", "permissions-b": "file_access: {}\n", readme: "visible\n" });
    await expect(executeHostedProjectFileJob(duplicate, job("list", { path: "." })))
      .rejects.toMatchObject({ code: "protected_path" });
    expect(duplicate.reads).toEqual([]);

    const malformed = createAdapter([
      { path: ".openmates/permissions.yml", embedId: "permissions" },
      { path: "README.md", embedId: "readme" },
    ], { permissions: "file_access:\n  private_paths: [unterminated\n", readme: "visible\n" });
    await expect(executeHostedProjectFileJob(malformed, job("read_text", { path: "README.md" })))
      .rejects.toMatchObject({ code: "protected_path" });
    expect(malformed.reads).toEqual(["permissions"]);
  });
});
