import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";

import { createProjectFileJobExecutor, type ProjectFileJob } from "../../ui/src/services/projectFileJobExecutor.ts";
import { verifyProjectIgnoredReadGrant } from "../../ui/src/utils/projectIgnoredReadGrant.ts";
import { decryptWithAesGcmCombined } from "../src/crypto.ts";
import { requestProjectRemoteOperation } from "../src/projectRequester.ts";
import { createRemoteAccessHandshake, deriveRemoteAccessSessionKey, sealRemoteAccessEnvelope, type RemoteAccessCryptoIdentity } from "../src/remoteAccessCrypto.ts";

const projectId = "project-1";
const chatId = "chat-1";
const projectKey = new Uint8Array(32).fill(19);
const readJob = (generation = 1): ProjectFileJob => ({
  protocol_version: 1, operation_id: "read-op-1", chat_id: chatId, project_id: projectId,
  source_id: "source-1", operation: "read_text", arguments: { path: "ignored.txt" },
  lease_token: `fixture-lease-token-${generation}`, lease_generation: generation,
  lease_expires_at: Math.floor(Date.now() / 1000) + 60,
});

describe("Project ignored-file read approval", () => {
  // contract-test: direct surface=cli assertions=projects.files.no-server-decryption-authority,projects.files.chat-focus-required
  it("releases the lease, asks for the exact path, and executes only after a fresh claim", async () => {
    const events: Array<{ event: string; payload: Record<string, unknown> }> = [];
    let calls = 0;
    const executor = createProjectFileJobExecutor({
      isActiveChat: () => true,
      send: (event, payload) => { events.push({ event, payload }); },
      approve: async () => {},
      requestReadApproval: async (request) => {
        assert.deepEqual(request, { projectId, sourceId: "source-1", chatId, operationId: "read-op-1", path: "ignored.txt" });
        assert.equal(events.at(-1)?.payload.status, "awaiting_approval");
        return true;
      },
      resolve: async () => ({
        projectKey, writeMode: "always_ask",
        execute: async (_job, _mutation, approval) => {
          calls += 1;
          if (!approval) throw Object.assign(new Error(), { code: "ignored_path_requires_approval" });
          assert.deepEqual(approval, { path: "ignored.txt", chatId, operationId: "read-op-1" });
          return { content: "approved" };
        },
      }),
    });
    await executor.request(readJob());
    assert.equal(events.at(-1)?.event, "project_file_operation_claim");
    await executor.request(readJob(2));
    assert.equal(calls, 2);
    assert.equal(events.at(-1)?.payload.status, "completed");
  });

  // contract-test: direct surface=cli assertions=projects.files.no-server-decryption-authority,projects.keys.client-wrapped
  it("places a request-bound signed grant outside unchanged model arguments", async () => {
    const key = randomBytes(32);
    const sourceSessionId = "session-1";
    let encryptedResult = "";
    const client = {
      whoAmI: async () => ({ id: "owner-1" }),
      createProjectRemoteAccessRequest: async (_project: string, _source: string, input: Record<string, unknown>) => {
        const bootstrap = JSON.parse(String(await decryptWithAesGcmCombined(String(input.encrypted_envelope), key)));
        assert.deepEqual(bootstrap.arguments, { path: "ignored.txt" });
        assert.equal(Object.hasOwn(bootstrap.arguments, "ignored_read_grant"), false);
        assert.deepEqual(bootstrap.ignored_read_context, { chatId, operationId: "read-op-1" });
        assert.equal(await verifyProjectIgnoredReadGrant(key, bootstrap.ignored_read_grant, {
          projectId, sourceId: "source-1", requestId: String(input.request_id), chatId,
          operationId: "read-op-1", path: "ignored.txt",
        }), true);
        const identity: RemoteAccessCryptoIdentity = {
          ownerId: "owner-1", projectId, sourceId: "source-1", sourceSessionId,
          requestingClientId: String(input.requesting_client_id), keyEpoch: 1,
        };
        const source = await createRemoteAccessHandshake(key, identity, "source");
        const sessionKey = await deriveRemoteAccessSessionKey(key, identity, "source", source.privateKey, source.handshake, bootstrap.requester_handshake);
        encryptedResult = JSON.stringify({ source_handshake: source.handshake, envelope: await sealRemoteAccessEnvelope(
          sessionKey, identity, String(input.request_id), "result", new TextEncoder().encode(JSON.stringify({ ok: true, result: { content: "ok" } })),
        ) });
        return { request_id: input.request_id, status: "delivered", source_session_id: sourceSessionId, key_epoch: 1 };
      },
      getProjectRemoteAccessResult: async () => ({ status: "completed", encrypted_envelope: encryptedResult }),
    };
    const result = await requestProjectRemoteOperation({
      client: client as never, projectId, projectKey: key,
      source: { source_id: "source-1", source_type: "local_folder", encrypted_display_name: "x", encrypted_metadata: "x", status: "connected", source_session_id: sourceSessionId, key_epoch: 1 },
      operation: "read_text", arguments: { path: "ignored.txt" }, context: { personal: true },
      approvedIgnoredRead: { path: "ignored.txt", chatId, operationId: "read-op-1" },
    });
    assert.deepEqual(result, { content: "ok" });
  });

  // contract-test: direct surface=cli assertions=projects.files.no-server-decryption-authority,projects.files.chat-focus-required
  it("leaves ignored reads awaiting without consent UI and never prompts for private paths", async () => {
    const ignoredStatuses: unknown[] = [];
    const ignored = createProjectFileJobExecutor({
      isActiveChat: () => true,
      send: (_event, payload) => { ignoredStatuses.push(payload.status); },
      approve: async () => {},
      resolve: async () => ({
        projectKey, writeMode: "always_ask",
        execute: async () => { throw Object.assign(new Error(), { code: "ignored_path_requires_approval" }); },
      }),
    });
    await ignored.request(readJob());
    assert.deepEqual(ignoredStatuses, ["awaiting_approval"]);

    let privateResult: Record<string, unknown> | undefined;
    const privateExecutor = createProjectFileJobExecutor({
      isActiveChat: () => true,
      send: (_event, payload) => { if (payload.status === "failed") privateResult = payload.result as Record<string, unknown>; },
      approve: async () => {},
      requestReadApproval: async () => assert.fail("Private paths must never request an ignored-file override"),
      resolve: async () => ({
        projectKey, writeMode: "always_ask",
        execute: async () => { throw Object.assign(new Error(), { code: "protected_path" }); },
      }),
    });
    await privateExecutor.request(readJob());
    assert.equal(privateResult?.code, "protected_path");
  });

  // contract-test: direct surface=cli assertions=projects.files.no-server-decryption-authority,projects.files.chat-focus-required
  it("does not reuse consent when a null-source job resolves to a different actual source", async () => {
    let resolvedSource = "source-1";
    let prompts = 0;
    const executor = createProjectFileJobExecutor({
      isActiveChat: () => true,
      send: async () => {},
      approve: async () => {},
      requestReadApproval: async () => { prompts += 1; return true; },
      resolve: async () => ({
        projectKey, sourceId: resolvedSource, writeMode: "always_ask",
        execute: async (_job, _mutation, approval) => {
          if (!approval) throw Object.assign(new Error(), { code: "ignored_path_requires_approval" });
          return { content: "approved" };
        },
      }),
    });
    const sourceLess = { ...readJob(), source_id: null };
    await executor.request(sourceLess);
    assert.equal(prompts, 1);
    resolvedSource = "source-2";
    await executor.request({ ...sourceLess, lease_generation: 2, lease_token: "fixture-lease-token-2" });
    assert.equal(prompts, 2);
  });
});
