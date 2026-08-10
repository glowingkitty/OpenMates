/**
 * Contract tests for Project remote-access end-to-end envelope encryption.
 *
 * Handshakes are authenticated with the Project key and bind owner, Project,
 * source, session, requester, role, and key epoch. The backend relays these
 * values but cannot derive the resulting source-session key or open envelopes.
 *
 * Spec: docs/specs/cli-remote-access-live-bridge/spec.yml
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  RemoteAccessReplayGuard,
  createRemoteAccessHandshake,
  deriveRemoteAccessSessionKey,
  openRemoteAccessEnvelope,
  sealRemoteAccessEnvelope,
  type RemoteAccessCryptoIdentity,
} from "../src/remoteAccessCrypto.ts";
import {
  createProjectRemoteAccessHandshake,
  deriveProjectRemoteAccessSessionKey,
} from "../../ui/src/services/projectRemoteAccessCrypto.ts";
import { projectRemoteAccessCryptoIdentity } from "../src/remoteAccess.ts";


const identity: RemoteAccessCryptoIdentity = {
  ownerId: "owner-1",
  projectId: "project-1",
  sourceId: "source-1",
  sourceSessionId: "session-1",
  requestingClientId: "browser-1",
  keyEpoch: 1,
};

const teamIdentity: RemoteAccessCryptoIdentity = {
  ...identity,
  contextType: "team",
  contextId: "team-1",
  hostMemberId: "member-host",
  hostDeviceId: "host-device-team",
  requesterMemberId: "member-requester",
  requesterDeviceId: "requester-device-team",
};


describe("remote-access envelope encryption", () => {
  it("keeps Personal v1 host and requester keys aligned despite stray routing identity", async () => {
    const projectKey = crypto.getRandomValues(new Uint8Array(32));
    const requesterIdentity = { ...identity };
    const hostIdentity = projectRemoteAccessCryptoIdentity(
      identity.ownerId,
      identity.sourceSessionId,
      {},
      {
        project_id: identity.projectId,
        source_id: identity.sourceId,
        requesting_client_id: identity.requestingClientId,
        key_epoch: identity.keyEpoch,
        routing_identity: {
          context_type: "team",
          context_id_hash: "stray-team-hash",
          host_member_hash: "stray-host",
          host_device_fingerprint_hash: "stray-host-device",
          requester_member_hash: "stray-requester",
          requester_device_fingerprint_hash: "stray-requester-device",
        },
      } as never,
    );
    const requester = await createRemoteAccessHandshake(projectKey, requesterIdentity, "requester");
    const source = await createRemoteAccessHandshake(projectKey, hostIdentity, "source");
    const requesterKey = await deriveRemoteAccessSessionKey(
      projectKey, requesterIdentity, "requester", requester.privateKey, requester.handshake, source.handshake,
    );
    const sourceKey = await deriveRemoteAccessSessionKey(
      projectKey, hostIdentity, "source", source.privateKey, source.handshake, requester.handshake,
    );

    assert.equal(requester.handshake.version, 1);
    assert.deepEqual(hostIdentity, requesterIdentity);
    assert.deepEqual(requesterKey, sourceKey);
  });

  it("derives the same session key from authenticated CLI and requester handshakes", async () => {
    const projectKey = crypto.getRandomValues(new Uint8Array(32));
    const requester = await createRemoteAccessHandshake(projectKey, identity, "requester");
    const source = await createRemoteAccessHandshake(projectKey, identity, "source");

    const requesterKey = await deriveRemoteAccessSessionKey(
      projectKey, identity, "requester", requester.privateKey, requester.handshake, source.handshake,
    );
    const sourceKey = await deriveRemoteAccessSessionKey(
      projectKey, identity, "source", source.privateKey, source.handshake, requester.handshake,
    );

    assert.deepEqual(requesterKey, sourceKey);
    assert.equal(requester.handshake.version, 1);
    assert.equal("privateKey" in requester.handshake, false);
  });

  it("rejects substituted keys, tampered identities, roles, and key epochs", async () => {
    const projectKey = crypto.getRandomValues(new Uint8Array(32));
    const requester = await createRemoteAccessHandshake(projectKey, identity, "requester");
    const source = await createRemoteAccessHandshake(projectKey, identity, "source");
    const changed = { ...identity, projectId: "project-2" };

    await assert.rejects(
      () => deriveRemoteAccessSessionKey(
        projectKey, changed, "requester", requester.privateKey, requester.handshake, source.handshake,
      ),
      /handshake authentication failed/,
    );
    await assert.rejects(
      () => deriveRemoteAccessSessionKey(
        projectKey,
        identity,
        "requester",
        requester.privateKey,
        requester.handshake,
        { ...source.handshake, publicKey: requester.handshake.publicKey },
      ),
      /handshake authentication failed/,
    );
  });

  it("binds encrypted requests to identity, request, direction, and epoch", async () => {
    const projectKey = crypto.getRandomValues(new Uint8Array(32));
    const requester = await createRemoteAccessHandshake(projectKey, identity, "requester");
    const source = await createRemoteAccessHandshake(projectKey, identity, "source");
    const sessionKey = await deriveRemoteAccessSessionKey(
      projectKey, identity, "requester", requester.privateKey, requester.handshake, source.handshake,
    );
    const envelope = await sealRemoteAccessEnvelope(
      sessionKey,
      identity,
      "request-1",
      "request",
      new TextEncoder().encode(JSON.stringify({ query: "billing" })),
    );

    const plaintext = await openRemoteAccessEnvelope(
      sessionKey, identity, "request-1", "request", envelope, new RemoteAccessReplayGuard(),
    );
    assert.equal(new TextDecoder().decode(plaintext), '{"query":"billing"}');
    await assert.rejects(
      () => openRemoteAccessEnvelope(
        sessionKey, { ...identity, keyEpoch: 2 }, "request-1", "request", envelope, new RemoteAccessReplayGuard(),
      ),
      /envelope authentication failed/,
    );
  });

  it("rejects replayed nonces and request envelopes used as results", async () => {
    const projectKey = crypto.getRandomValues(new Uint8Array(32));
    const requester = await createRemoteAccessHandshake(projectKey, identity, "requester");
    const source = await createRemoteAccessHandshake(projectKey, identity, "source");
    const sessionKey = await deriveRemoteAccessSessionKey(
      projectKey, identity, "source", source.privateKey, source.handshake, requester.handshake,
    );
    const envelope = await sealRemoteAccessEnvelope(
      sessionKey, identity, "request-1", "request", new TextEncoder().encode("safe"),
    );
    const replayGuard = new RemoteAccessReplayGuard();

    await openRemoteAccessEnvelope(sessionKey, identity, "request-1", "request", envelope, replayGuard);
    await assert.rejects(
      () => openRemoteAccessEnvelope(sessionKey, identity, "request-1", "request", envelope, replayGuard),
      /replayed remote-access envelope/,
    );
    await assert.rejects(
      () => openRemoteAccessEnvelope(
        sessionKey, identity, "request-1", "result", envelope, new RemoteAccessReplayGuard(),
      ),
      /envelope authentication failed/,
    );
  });

  it("rejects non-canonical base64url fields", async () => {
    const projectKey = crypto.getRandomValues(new Uint8Array(32));
    const requester = await createRemoteAccessHandshake(projectKey, identity, "requester");
    const source = await createRemoteAccessHandshake(projectKey, identity, "source");
    await assert.rejects(
      () => deriveRemoteAccessSessionKey(
        projectKey,
        identity,
        "requester",
        `${requester.privateKey}=`,
        requester.handshake,
        source.handshake,
      ),
      /invalid remote-access key or envelope field/,
    );
  });

  it("derives matching Team keys with the versioned workspace and peer transcript", async () => {
    const projectKey = crypto.getRandomValues(new Uint8Array(32));
    const requester = await createRemoteAccessHandshake(projectKey, teamIdentity, "requester");
    const source = await createRemoteAccessHandshake(projectKey, teamIdentity, "source");
    const requesterKey = await deriveRemoteAccessSessionKey(
      projectKey, teamIdentity, "requester", requester.privateKey, requester.handshake, source.handshake,
    );
    const sourceKey = await deriveRemoteAccessSessionKey(
      projectKey, teamIdentity, "source", source.privateKey, source.handshake, requester.handshake,
    );

    assert.equal(requester.handshake.version, 2);
    assert.deepEqual(requesterKey, sourceKey);
  });

  it("rejects Personal/Team scope and host/requester member or device substitution", async () => {
    const projectKey = crypto.getRandomValues(new Uint8Array(32));
    const requester = await createRemoteAccessHandshake(projectKey, teamIdentity, "requester");
    const source = await createRemoteAccessHandshake(projectKey, teamIdentity, "source");
    const substitutions: RemoteAccessCryptoIdentity[] = [
      { ...teamIdentity, contextType: "personal" },
      { ...teamIdentity, contextId: "team-2" },
      { ...teamIdentity, hostMemberId: "different-host" },
      { ...teamIdentity, hostDeviceId: "different-host-device" },
      { ...teamIdentity, requesterMemberId: "different-requester" },
      { ...teamIdentity, requesterDeviceId: "different-requester-device" },
    ];

    for (const substituted of substitutions) {
      await assert.rejects(
        () => deriveRemoteAccessSessionKey(
          projectKey, substituted, "requester", requester.privateKey, requester.handshake, source.handshake,
        ),
        /handshake authentication failed/,
      );
    }
  });

  it("keeps CLI source and browser requester transcript v2 interoperable", async () => {
    const projectKey = crypto.getRandomValues(new Uint8Array(32));
    const requester = await createProjectRemoteAccessHandshake(projectKey, teamIdentity, "requester");
    const source = await createRemoteAccessHandshake(projectKey, teamIdentity, "source");
    const requesterKey = await deriveProjectRemoteAccessSessionKey(
      projectKey, teamIdentity, "requester", requester.privateKey, requester.handshake, source.handshake,
    );
    const sourceKey = await deriveRemoteAccessSessionKey(
      projectKey, teamIdentity, "source", source.privateKey, source.handshake, requester.handshake,
    );

    assert.deepEqual(requesterKey, sourceKey);
  });
});
