import test from "node:test";
import assert from "node:assert/strict";
import { createProjectFileJobExecutor, type ProjectFileJob } from "../../ui/src/services/projectFileJobExecutor.js";
import { executeHostedProjectFileJob, hostedProjectFileIdentity, projectFileContentHash, type HostedProjectFileAdapter, type HostedProjectFileHead } from "../../ui/src/services/hostedProjectFileExecutor.js";
import { decryptWithAesGcmCombined, encryptWithAesGcmCombined, encryptBytesWithAesGcm, decryptBytesWithAesGcm } from "../src/crypto.js";
import { prepareCliProjectFocusForPreflight } from "../src/projectFileExecutor.js";
import type { OpenMatesWsClient } from "../src/ws.js";

const projectId = "72dcdd3a-c264-4291-812b-02e820ca88c9";
const chatId = "0b59bafd-14d8-46b7-94ab-fcf0df0fbb10";
const projectKey = new Uint8Array(32).fill(17);
function job(overrides: Partial<ProjectFileJob> = {}): ProjectFileJob {
  return { protocol_version: 1, operation_id: "fixture-create-1", chat_id: chatId, project_id: projectId,
    operation: "create_file", arguments: { path: "README.md", expected_base: null, content: "hello\n" },
    lease_token: "fixture-lease-token-long", lease_generation: 1, lease_expires_at: Math.floor(Date.now() / 1000) + 60, ...overrides };
}

// contract-test: supporting surface=cli assertions=projects.files.chat-focus-required,chats.persistence.client-encrypted
test("Project focus preparation persists a new encrypted shell before activation and leaves existing chats stable", async () => {
  const order: string[] = [];
  const payloads: Record<string, unknown>[] = [];
  let acknowledgeStored: (() => void) | undefined;
  const ws = {
    waitForMessage: (type: string) => {
      order.push(`wait:${type}`);
      return new Promise((resolve) => {
        acknowledgeStored = () => {
          order.push("ack:encrypted_metadata_stored");
          resolve({ type, payload: { chat_id: chatId } });
        };
      });
    },
    sendAsync: async (type: string, payload: Record<string, unknown>) => {
      order.push(`send:${type}`);
      payloads.push(payload);
      acknowledgeStored?.();
    },
  } as unknown as OpenMatesWsClient;

  await prepareCliProjectFocusForPreflight({
    ws, chatId, teamId: null, isNewChat: true, encryptedChatKey: "wrapped-chat-key", createdAt: 123,
    activateFocus: async () => { order.push("activate"); },
  });
  order.push("preflight");
  assert.deepEqual(order, [
    "wait:encrypted_metadata_stored",
    "send:encrypted_chat_metadata",
    "ack:encrypted_metadata_stored",
    "activate",
    "preflight",
  ]);
  assert.deepEqual(payloads, [{
    chat_id: chatId,
    encrypted_chat_key: "wrapped-chat-key",
    created_at: 123,
    versions: {},
  }]);

  order.length = 0;
  payloads.length = 0;
  await prepareCliProjectFocusForPreflight({
    ws, chatId, teamId: null, isNewChat: false, encryptedChatKey: "wrapped-chat-key", createdAt: 123,
    activateFocus: async () => { order.push("activate"); },
  });
  order.push("preflight");
  assert.deepEqual(order, ["activate", "preflight"]);
  assert.deepEqual(payloads, []);
});

// contract-test: supporting surface=cli assertions=projects.files.write-policy-enforcement,projects.files.chat-focus-required
test("always-ask releases the lease, approves exact proposal, then claims a fresh lease before writing", async () => {
  const events: Array<{ event: string; payload: Record<string, unknown> }> = [];
  let writes = 0;
  let approvedDigest = "";
  const executor = createProjectFileJobExecutor({
    isActiveChat: (id) => id === chatId,
    send: (event, payload) => { events.push({ event, payload }); },
    resolve: async () => ({ projectKey, writeMode: "always_ask", execute: async () => { writes++; return { created: true }; } }),
    requestApproval: async () => {
      assert.equal(events.at(-1)?.payload.status, "awaiting_approval");
      assert.equal(writes, 0);
      return true;
    },
    approve: async (_request, digest) => { approvedDigest = digest; },
  });
  await executor.request(job());
  assert.equal(writes, 0);
  assert.equal(events.at(-1)?.event, "project_file_operation_claim");
  await executor.request(job({ lease_generation: 2, lease_token: "new-fixture-lease-token" }));
  assert.equal(writes, 1);
  assert.equal(events.at(-1)?.payload.status, "completed");
  assert.equal((events.at(-1)?.payload.result as Record<string, unknown>).proposal_commitment, approvedDigest);
});

// contract-test: supporting surface=cli assertions=projects.files.write-policy-enforcement,projects.files.recovery-authorization
test("missing approval UI never approves, and a stopped chat cannot execute a queued request", async () => {
  const statuses: unknown[] = [];
  let writes = 0;
  const executor = createProjectFileJobExecutor({
    isActiveChat: () => true, send: (_event, payload) => { statuses.push(payload.status); },
    resolve: async () => ({ projectKey, writeMode: "always_ask", execute: async () => { writes++; return {}; } }),
    approve: async () => { assert.fail("Must not infer consent"); },
  });
  await executor.request(job());
  assert.deepEqual(statuses, ["awaiting_approval"]);
  executor.stop();
  await executor.request(job({ lease_generation: 2 }));
  assert.equal(writes, 0);
});

// contract-test: supporting surface=cli assertions=projects.files.recovery-authorization
test("expired leases cannot write", async () => {
  let code: unknown;
  const executor = createProjectFileJobExecutor({
    isActiveChat: () => true, send: (_event, payload) => { code = (payload.result as Record<string, unknown>)?.code; },
    resolve: async () => ({ projectKey, writeMode: "apply_and_show", execute: async () => assert.fail("Expired lease executed") }),
    approve: async () => {},
  });
  await executor.request(job({ lease_expires_at: 1 }));
  assert.equal(code, "lease_expired");
});

// contract-test: supporting surface=cli assertions=projects.files.hosted-ciphertext-commit,projects.files.expected-base,projects.files.exact-patch
test("hosted create publishes ciphertext only and update validates the actual decrypted base", async () => {
  let committed: Record<string, unknown> | undefined;
  const state: { current?: HostedProjectFileHead } = {};
  let embedId = "";
  const adapter: HostedProjectFileAdapter = {
    projectId, projectKey, chatKey: new Uint8Array(32).fill(23),
    listFiles: async () => state.current ? [{ path: "README.md", embedId }] : [],
    readHead: async () => state.current!, encrypt: encryptWithAesGcmCombined, wrap: encryptBytesWithAesGcm,
    encodeContent: async (content) => JSON.stringify(content), receipt: async () => null,
    commit: async (payload) => { committed = payload; return { status: "committed", current_revision: Number(payload.expected_revision) + 1 }; },
  };
  const create = job();
  const created = await executeHostedProjectFileJob(adapter, create, { operation: "create_file", operation_id: create.operation_id, path: "README.md", expected_base: null, content: "hello\n" });
  embedId = String(created.embed_id);
  assert.equal(embedId, await hostedProjectFileIdentity(projectKey, "README.md", "embed"));
  assert.notEqual(embedId, await hostedProjectFileIdentity(new Uint8Array(32).fill(18), "README.md", "embed"));
  assert.equal(JSON.stringify(committed).includes("README.md"), false);
  assert.equal(JSON.stringify(committed).includes("hello"), false);
  const createdFields = committed!.create as Record<string, unknown>;
  const wrapper = (createdFields.key_wrappers as Array<Record<string, unknown>>)[0]!;
  const embedKey = await decryptBytesWithAesGcm(String(wrapper.encrypted_embed_key), projectKey);
  assert.ok(embedKey);
  const content = await decryptWithAesGcmCombined(String((committed!.head as Record<string, unknown>).encrypted_content), embedKey);
  state.current = { embedKey, content: JSON.parse(content!), revision: 1, hasInitialHistory: true };
  const patch = "--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-hello\n+world\n";
  const update = job({ operation: "update_file", operation_id: "fixture-update-1", arguments: { path: "README.md", patch, expected_base: "0".repeat(64) } });
  const mutation = { operation: "update_file" as const, operation_id: update.operation_id, path: "README.md", patch, expected_base: "0".repeat(64) };
  await assert.rejects(executeHostedProjectFileJob(adapter, update, mutation), { code: "stale_base" });
  mutation.expected_base = await projectFileContentHash("hello\n");
  update.arguments.expected_base = mutation.expected_base;
  const changed = await executeHostedProjectFileJob(adapter, update, mutation);
  assert.equal(changed.revision, 2);
  assert.equal((committed!.history_rows as unknown[]).length, 1);
  assert.equal(JSON.stringify(committed).includes("world"), false);
});

// contract-test: supporting surface=cli assertions=projects.files.commit-replay
test("hosted committed receipt resolves a retry before stale validation or a second commit", async () => {
  const currentJob = job();
  const output = await executeHostedProjectFileJob({
    projectId, projectKey, chatKey: new Uint8Array(32), listFiles: async () => [{ path: "README.md", embedId: "fixture-embed" }],
    readHead: async () => assert.fail("Receipt should avoid reread"), encrypt: encryptWithAesGcmCombined,
    wrap: encryptBytesWithAesGcm, encodeContent: async () => "", commit: async () => assert.fail("Must not commit twice"),
    receipt: async () => ({ status: "committed", current_revision: 1 }),
  }, currentJob, { operation: "create_file", operation_id: currentJob.operation_id, path: "README.md", expected_base: null, content: "hello\n" });
  assert.equal(output.idempotent, true);
});

// contract-test: supporting surface=cli assertions=projects.files.search-scoped,projects.files.search-consistent
test("hosted search excludes protected candidate paths before decrypting them", async () => {
  const read: string[] = [];
  const files = [
    { path: ".env", embedId: "secret-env" },
    { path: ".ssh/id_ed25519", embedId: "secret-key" },
    { path: ".git/config", embedId: "git-config" },
    { path: "package.json", embedId: "package" },
    { path: "Dockerfile", embedId: "docker" },
    { path: "src/auth/session.ts", embedId: "auth" },
  ];
  const adapter: HostedProjectFileAdapter = {
    projectId, projectKey, chatKey: new Uint8Array(32), listFiles: async () => files,
    readHead: async (embedId) => {
      read.push(embedId);
      return { embedKey: new Uint8Array(32), content: { code: "needle\n" }, revision: 1, hasInitialHistory: true };
    },
    encrypt: encryptWithAesGcmCombined, wrap: encryptBytesWithAesGcm, encodeContent: async () => "",
    commit: async () => assert.fail("Search must not commit"), receipt: async () => null,
  };
  const result = await executeHostedProjectFileJob(adapter, job({
    operation: "search",
    arguments: { query: "needle", target: "content", mode: "literal", path: ".", max_results: 20 },
  }));
  assert.deepEqual(result.matches, [
    { path: "package.json", line: 1, snippet: "needle" },
    { path: "Dockerfile", line: 1, snippet: "needle" },
    { path: "src/auth/session.ts", line: 1, snippet: "needle" },
  ]);
  assert.deepEqual(read, ["package", "docker", "auth"]);
  assert.equal(result.excluded, 3);
  assert.equal(result.truncated, false);
});

// contract-test: supporting surface=cli assertions=projects.files.search-consistent
test("hosted search reports truncation only for a known extra match or an unexamined candidate cap", async () => {
  const baseAdapter: HostedProjectFileAdapter = {
    projectId, projectKey, chatKey: new Uint8Array(32),
    listFiles: async () => [
      { path: "one.ts", embedId: "one" },
      { path: "two.ts", embedId: "two" },
    ],
    readHead: async () => ({ embedKey: new Uint8Array(32), content: { code: "needle\n" }, revision: 1, hasInitialHistory: true }),
    encrypt: encryptWithAesGcmCombined, wrap: encryptBytesWithAesGcm, encodeContent: async () => "",
    commit: async () => assert.fail("Search must not commit"), receipt: async () => null,
  };
  const exact = await executeHostedProjectFileJob(baseAdapter, job({
    operation: "search",
    arguments: { query: ".ts", target: "files", mode: "literal", path: ".", max_results: 2 },
  }));
  assert.deepEqual({ omitted: exact.omitted, truncated: exact.truncated }, { omitted: 0, truncated: false });

  const extra = await executeHostedProjectFileJob(baseAdapter, job({
    operation: "search",
    arguments: { query: ".ts", target: "files", mode: "literal", path: ".", max_results: 1 },
  }));
  assert.deepEqual({ omitted: extra.omitted, truncated: extra.truncated }, { omitted: 1, truncated: true });
});
