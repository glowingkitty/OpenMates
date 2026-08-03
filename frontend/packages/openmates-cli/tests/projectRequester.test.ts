/*
 * Contract tests for the production Project remote-file requester.
 *
 * Purpose: prove Personal and Team requester handshakes decrypt only locally.
 * Security: fake transport sees opaque ciphertext while source behavior uses the
 * same Project-authenticated crypto implementation as the foreground CLI.
 * Run: npm run test:unit:projects-cli.
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";

import { decryptWithAesGcmCombined, encryptWithAesGcmCombined } from "../src/crypto.ts";
import { requestProjectRemoteOperation } from "../src/projectRequester.ts";
import {
  createRemoteAccessHandshake,
  deriveRemoteAccessSessionKey,
  sealRemoteAccessEnvelope,
  type RemoteAccessCryptoIdentity,
} from "../src/remoteAccessCrypto.ts";

describe("Project requester", () => {
  it("performs a Personal encrypted operation without exposing arguments to transport", async () => {
    const projectKey = randomBytes(32);
    const sourceSessionId = "source-session-1";
    let encryptedRequest = "";
    let encryptedResult = "";
    const client = {
      whoAmI: async () => ({ id: "owner-1" }),
      createProjectRemoteAccessRequest: async (_projectId: string, _sourceId: string, input: Record<string, unknown>) => {
        encryptedRequest = String(input.encrypted_envelope);
        const bootstrap = JSON.parse(String(await decryptWithAesGcmCombined(encryptedRequest, projectKey)));
        const identity: RemoteAccessCryptoIdentity = {
          ownerId: "owner-1",
          projectId: "project-1",
          sourceId: "source-1",
          sourceSessionId,
          requestingClientId: String(input.requesting_client_id),
          keyEpoch: 1,
        };
        const source = await createRemoteAccessHandshake(projectKey, identity, "source");
        const sessionKey = await deriveRemoteAccessSessionKey(
          projectKey, identity, "source", source.privateKey, source.handshake, bootstrap.requester_handshake,
        );
        encryptedResult = JSON.stringify({
          source_handshake: source.handshake,
          envelope: await sealRemoteAccessEnvelope(
            sessionKey, identity, String(input.request_id), "result",
            new TextEncoder().encode(JSON.stringify({ ok: true, result: { entries: [{ path: "src", kind: "directory" }] } })),
          ),
        });
        return { request_id: input.request_id, status: "delivered", source_session_id: sourceSessionId, key_epoch: 1 };
      },
      getProjectRemoteAccessResult: async () => ({ status: "completed", encrypted_envelope: encryptedResult }),
    };

    const result = await requestProjectRemoteOperation({
      client: client as never,
      projectId: "project-1",
      projectKey,
      source: {
        source_id: "source-1",
        source_type: "local_folder",
        encrypted_display_name: "cipher-name",
        encrypted_metadata: "cipher-metadata",
        status: "connected",
        source_session_id: sourceSessionId,
        key_epoch: 1,
      },
      operation: "list",
      arguments: { path: "src" },
      context: { personal: true },
    });

    assert.deepEqual(result, { entries: [{ path: "src", kind: "directory" }] });
    assert.doesNotMatch(encryptedRequest, /src|path/);
  });

  it("completes bounded Team routing discovery before a v2 request", async () => {
    const projectKey = randomBytes(32);
    const sourceSessionId = "source-session-team";
    const routing = {
      context_type: "team",
      context_id_hash: "context-hash",
      host_member_hash: "host-member",
      host_device_fingerprint_hash: "host-device",
      requester_member_hash: "requester-member",
      requester_device_fingerprint_hash: "requester-device",
    };
    const results = new Map<string, string>();
    let requestCount = 0;
    const client = {
      createProjectRemoteAccessRequest: async (_projectId: string, _sourceId: string, input: Record<string, unknown>) => {
        requestCount += 1;
        const requestId = String(input.request_id);
        const bootstrap = JSON.parse(String(await decryptWithAesGcmCombined(String(input.encrypted_envelope), projectKey)));
        if (bootstrap.type === "routing_discovery") {
          results.set(requestId, await encryptWithAesGcmCombined(JSON.stringify({ type: "routing_discovery_result", nonce: bootstrap.nonce }), projectKey));
        } else {
          const identity: RemoteAccessCryptoIdentity = {
            ownerId: routing.context_id_hash,
            contextType: "team",
            contextId: routing.context_id_hash,
            projectId: "project-1",
            sourceId: "source-1",
            sourceSessionId,
            requestingClientId: String(input.requesting_client_id),
            hostMemberId: routing.host_member_hash,
            hostDeviceId: routing.host_device_fingerprint_hash,
            requesterMemberId: routing.requester_member_hash,
            requesterDeviceId: routing.requester_device_fingerprint_hash,
            keyEpoch: 1,
          };
          const source = await createRemoteAccessHandshake(projectKey, identity, "source");
          const sessionKey = await deriveRemoteAccessSessionKey(projectKey, identity, "source", source.privateKey, source.handshake, bootstrap.requester_handshake);
          results.set(requestId, JSON.stringify({
            source_handshake: source.handshake,
            envelope: await sealRemoteAccessEnvelope(
              sessionKey, identity, requestId, "result",
              new TextEncoder().encode(JSON.stringify({ ok: true, result: { content: "bounded" } })),
            ),
          }));
        }
        return { request_id: requestId, status: "delivered", source_session_id: sourceSessionId, key_epoch: 1, routing_identity: routing };
      },
      getProjectRemoteAccessResult: async (_projectId: string, _sourceId: string, requestId: string) => ({
        status: "completed",
        encrypted_envelope: results.get(requestId)!,
      }),
    };

    const result = await requestProjectRemoteOperation({
      client: client as never,
      projectId: "project-1",
      projectKey,
      source: {
        source_id: "source-1",
        source_type: "local_folder",
        encrypted_display_name: "cipher-name",
        encrypted_metadata: "cipher-metadata",
        status: "connected",
      },
      operation: "read_text",
      arguments: { path: "src/file.ts" },
      context: { teamId: "team-1" },
    });

    assert.equal(requestCount, 2);
    assert.deepEqual(result, { content: "bounded" });
  });
});
