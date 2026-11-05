// Test-only oracle: execute the unchanged legacy implementation with synthetic
// deterministic randomness. Never import this harness from application code.
import { webcrypto } from "node:crypto";
import { writeFile } from "node:fs/promises";
let counter = 0;
Object.defineProperty(globalThis, "crypto", { configurable: true, value: {
  subtle: webcrypto.subtle,
  getRandomValues(target) {
    for (let index = 0; index < target.length; index++) target[index] = (counter * 37 + index * 13 + 11) % 256;
    counter++;
    return target;
  },
} });
const legacy = await import("../../../../frontend/packages/openmates-cli/src/remoteAccessCrypto.ts");
const projectKey = Uint8Array.from({ length: 32 }, (_, index) => index);
const vectors = [];
for (const team of [false, true]) {
  const identity = { ownerId: 'owner-"\\☃😀', projectId: "project-1", sourceId: "source-1", sourceSessionId: "session-1", requestingClientId: "browser-1", keyEpoch: 7,
    ...(team ? { contextType: "team", contextId: "team-1", hostMemberId: "host-member", hostDeviceId: "host-device", requesterMemberId: "requester-member", requesterDeviceId: "requester-device" } : {}),
  };
  const requester = await legacy.createRemoteAccessHandshake(projectKey, identity, "requester");
  const source = await legacy.createRemoteAccessHandshake(projectKey, identity, "source");
  const requesterKey = await legacy.deriveRemoteAccessSessionKey(projectKey, identity, "requester", requester.privateKey, requester.handshake, source.handshake);
  const sourceKey = await legacy.deriveRemoteAccessSessionKey(projectKey, identity, "source", source.privateKey, source.handshake, requester.handshake);
  if (!Buffer.from(requesterKey).equals(Buffer.from(sourceKey))) throw new Error("oracle handshake mismatch");
  const requestId = "request-1";
  const requestText = '{"path":"fixture/☃😀","line":"one\\ntwo"}';
  const resultText = '{"ok":true,"value":"synthetic fixture"}';
  const request = await legacy.sealRemoteAccessEnvelope(requesterKey, identity, requestId, "request", new TextEncoder().encode(requestText));
  const result = await legacy.sealRemoteAccessEnvelope(sourceKey, identity, requestId, "result", new TextEncoder().encode(resultText));
  await legacy.openRemoteAccessEnvelope(sourceKey, identity, requestId, "request", request, new legacy.RemoteAccessReplayGuard());
  await legacy.openRemoteAccessEnvelope(requesterKey, identity, requestId, "result", result, new legacy.RemoteAccessReplayGuard());
  vectors.push({ identity, projectKey: Buffer.from(projectKey).toString("base64url"), requester, source, sessionKey: Buffer.from(sourceKey).toString("base64url"), requestId, requestText, resultText, request, result });
}
await writeFile(new URL("./remote_access_vectors.json", import.meta.url), JSON.stringify(vectors, null, 2) + "\n");
