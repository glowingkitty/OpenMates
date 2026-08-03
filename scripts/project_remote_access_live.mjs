#!/usr/bin/env node
/*
 * Real dev-server verification for the encrypted Project remote-access bridge.
 *
 * API mode proves authenticated WebSocket lifecycle and opaque REST routing.
 * CLI mode starts the compiled foreground command and performs encrypted list,
 * search, and read requests without exposing Project keys to the backend.
 */

import { spawn } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { homedir, platform, release, tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { randomBytes, randomUUID } from "node:crypto";

import { OpenMatesClient } from "../frontend/packages/openmates-cli/src/client.ts";
import {
  decryptBytesWithAesGcm,
  decryptWithAesGcmCombined,
  encryptBytesWithAesGcm,
  encryptWithAesGcmCombined,
} from "../frontend/packages/openmates-cli/src/crypto.ts";
import {
  RemoteAccessReplayGuard,
  createRemoteAccessHandshake,
  deriveRemoteAccessSessionKey,
  openRemoteAccessEnvelope,
  sealRemoteAccessEnvelope,
} from "../frontend/packages/openmates-cli/dist/remoteAccessCrypto.js";
import { startRemoteAccessSource } from "../frontend/packages/openmates-cli/src/remoteAccess.ts";
import { OpenMatesWsClient } from "../frontend/packages/openmates-cli/src/ws.ts";

const ROOT = resolve(import.meta.dirname, "..");
const CLI_DIR = join(ROOT, "frontend", "packages", "openmates-cli");
const USER_AGENT = `OpenMates CLI/0.1 (${platform()} ${release()})`;
const mode = process.argv[2];
const apiUrl = (process.argv[3] || "https://api.dev.openmates.org").replace(/\/$/, "");

if (!new Set(["api", "api-team", "cli", "serve"]).has(mode)) {
  throw new Error("Usage: project_remote_access_live.mjs <api|api-team|cli|serve> <api-url>");
}

function requireValue(condition, message) {
  if (!condition) throw new Error(message);
}

function sessionState(client) {
  const session = client.session;
  requireValue(session, "CLI session is unavailable after test-account login");
  return session;
}

function cookieHeader(client) {
  return Object.entries(sessionState(client).cookies)
    .map(([key, value]) => `${key}=${value}`)
    .join("; ");
}

async function apiRequest(client, path, options = {}) {
  const response = await fetch(`${apiUrl}${path}`, {
    ...options,
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      Cookie: cookieHeader(client),
      "User-Agent": USER_AGENT,
      ...(options.headers ?? {}),
    },
  });
  const text = await response.text();
  let data = {};
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { raw: text };
    }
  }
  return { status: response.status, data };
}

async function expectStatus(client, path, status, options = {}) {
  const response = await apiRequest(client, path, options);
  requireValue(
    response.status === status,
    `${options.method ?? "GET"} ${path} returned ${response.status}, expected ${status}: ${JSON.stringify(response.data)}`,
  );
  return response.data;
}

async function createFixture(client, teamId = null, teamKey = null) {
  const projectId = randomUUID();
  const sourceId = randomUUID();
  const projectKey = randomBytes(32);
  const timestamp = Math.floor(Date.now() / 1000);
  const projectPayload = {
    project_id: projectId,
    encrypted_project_key: teamId ? null : await encryptBytesWithAesGcm(projectKey, client.getMasterKeyBytes()),
    encrypted_name: await encryptWithAesGcmCombined("Remote access live verification", projectKey),
    encrypted_description: await encryptWithAesGcmCombined("", projectKey),
    encrypted_icon: await encryptWithAesGcmCombined("folder", projectKey),
    encrypted_color: await encryptWithAesGcmCombined("default", projectKey),
    pinned: false,
    created_at: timestamp,
    updated_at: timestamp,
    last_opened_at: timestamp,
    key_wrappers: teamId ? [{
      key_type: "team",
      hashed_team_id: "",
      team_key_epoch: 1,
      encrypted_project_key: await encryptBytesWithAesGcm(projectKey, teamKey),
      wrapper_version: 1,
      created_at: timestamp,
    }] : [],
  };
  if (teamId) {
    const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(teamId));
    projectPayload.key_wrappers[0].hashed_team_id = Buffer.from(digest).toString("hex");
    await expectStatus(client, `/v1/projects?team_id=${encodeURIComponent(teamId)}`, 200, {
      method: "POST",
      body: JSON.stringify(projectPayload),
    });
  } else {
    await client.createProject(projectPayload);
  }
  const sourcePayload = {
    source_id: sourceId,
    source_type: "local_folder",
    encrypted_display_name: await encryptWithAesGcmCombined("Live remote source", projectKey),
    encrypted_metadata: await encryptWithAesGcmCombined("{}", projectKey),
    capabilities: ["read", "search", "import"],
    status: "offline",
    created_at: timestamp,
    updated_at: timestamp,
  };
  if (teamId) {
    await expectStatus(
      client,
      `/v1/projects/${projectId}/sources?team_id=${encodeURIComponent(teamId)}`,
      200,
      { method: "POST", body: JSON.stringify(sourcePayload) },
    );
  } else {
    await client.createProjectSource(projectId, sourcePayload);
  }
  return { projectId, sourceId, projectKey: new Uint8Array(projectKey), teamId };
}

async function deleteFixture(client, fixture) {
  if (!fixture) return;
  const query = fixture.teamId ? `?team_id=${encodeURIComponent(fixture.teamId)}` : "";
  const response = await apiRequest(client, `/v1/projects/${encodeURIComponent(fixture.projectId)}${query}`, { method: "DELETE" });
  if (response.status !== 200 && response.status !== 404) {
    throw new Error(`Fixture cleanup failed with HTTP ${response.status}`);
  }
}

async function refreshOwnerId(client) {
  const ownerId = await client.refreshWsToken();
  requireValue(typeof ownerId === "string" && ownerId.length > 0, "Authenticated owner identity unavailable");
  return ownerId;
}

function loadIsolatedClient(environmentKey) {
  const sessionPath = process.env[environmentKey];
  requireValue(sessionPath, `${environmentKey} is required; run the Python verifier to create isolated sessions`);
  const session = JSON.parse(readFileSync(sessionPath, "utf-8"));
  requireValue(session.masterKeyStorage === "plaintext" && session.masterKeyExportedB64, "Isolated verifier session is invalid");
  return OpenMatesClient.load({ apiUrl, session });
}

function recordProbe(probes, probe, status, reason = undefined) {
  probes.push({ probe, status, ...(reason ? { reason } : {}) });
}

function cryptoIdentity(ownerId, fixture, sourceSessionId, requestingClientId, routingIdentity = null) {
  const identity = {
    ownerId: routingIdentity?.context_id_hash ?? ownerId,
    projectId: fixture.projectId,
    sourceId: fixture.sourceId,
    sourceSessionId,
    requestingClientId,
    keyEpoch: 1,
  };
  if (!fixture.teamId) return identity;
  requireValue(routingIdentity?.context_type === "team", "Team crypto identity requires server-scoped routing identity");
  return {
    ...identity,
    contextType: "team",
    contextId: routingIdentity.context_id_hash,
    hostMemberId: routingIdentity.host_member_hash,
    hostDeviceId: routingIdentity.host_device_fingerprint_hash,
    requesterMemberId: routingIdentity.requester_member_hash,
    requesterDeviceId: routingIdentity.requester_device_fingerprint_hash,
  };
}

async function expectWsError(promise, expectedCode) {
  try {
    await promise;
  } catch (error) {
    requireValue(error?.code === expectedCode, `Expected ${expectedCode}, received ${error}`);
    return;
  }
  throw new Error(`Expected WebSocket error ${expectedCode}`);
}

function makeWebSocket(client) {
  const session = sessionState(client);
  return new OpenMatesWsClient({
    apiUrl,
    sessionId: session.sessionId,
    wsToken: session.wsToken,
    refreshToken: session.cookies.refresh_token ?? null,
    cookies: session.cookies,
    userAgent: USER_AGENT,
    taskUpdateJobs: false,
  });
}

async function waitForConnectedSource(client, fixture, timeoutMs = 20_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const path = `/v1/projects/${fixture.projectId}/sources${fixture.teamId ? `?team_id=${encodeURIComponent(fixture.teamId)}` : ""}`;
    const response = await apiRequest(client, path);
    requireValue(response.status === 200, `Source list failed with HTTP ${response.status}`);
    const sources = response.data.sources ?? [];
    const source = sources.find((candidate) => candidate.source_id === fixture.sourceId);
    if (source?.status === "connected" && (fixture.teamId || (source.source_session_id && source.key_epoch))) return source;
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 250));
  }
  throw new Error("Remote source did not become connected before the deadline");
}

async function runApiVerification(hostClient, requesterClient, fixture, ownerId) {
  const probes = [];
  const teamQuery = fixture.teamId ? `team_id=${encodeURIComponent(fixture.teamId)}` : "";
  const withContext = (path) => `${path}${path.includes("?") ? "&" : "?"}${teamQuery}`.replace(/[?&]$/, "");
  const sourceSessionId = randomUUID();
  const hostWs = makeWebSocket(hostClient);
  const takeoverWs = makeWebSocket(requesterClient);
  await hostWs.open();
  try {
    const registeredMessage = hostWs.waitForMessage("project_remote_access_registered", undefined, 10_000);
    await hostWs.sendAsync("project_remote_access_register", {
      source_session_id: sourceSessionId,
      ...(fixture.teamId ? { team_id: fixture.teamId } : {}),
      confirmed_takeover: false,
      bindings: [{
        project_id: fixture.projectId,
        source_id: fixture.sourceId,
        capabilities: ["read", "search", "import"],
        key_epoch: 1,
      }],
    });
    await registeredMessage;

    const source = await waitForConnectedSource(requesterClient, fixture);
    if (!fixture.teamId) {
      requireValue(source.source_session_id === sourceSessionId, "Source listing omitted the exact live session ID");
      requireValue(source.key_epoch === 1, "Source listing omitted the live key epoch");
    } else {
      requireValue(!source.source_session_id, "Team source listing exposed a host session identifier");
    }

    const unauthenticatedEnvelope = await encryptWithAesGcmCombined(
      JSON.stringify({ probe: "unauthenticated", nonce: randomUUID() }),
      fixture.projectKey,
    );
    const unauthenticated = await fetch(
      `${apiUrl}${withContext(`/v1/projects/${fixture.projectId}/sources/${fixture.sourceId}/requests`)}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          request_id: randomUUID(),
          requesting_client_id: "unauthenticated-client",
          operation: "list",
          key_epoch: 1,
          encrypted_envelope: unauthenticatedEnvelope,
        }),
      },
    );
    requireValue([401, 403].includes(unauthenticated.status), `Unauthenticated request returned HTTP ${unauthenticated.status}`);
    recordProbe(probes, "unauthenticated_request_denied", "passed");

    const wrongProjectEnvelope = await encryptWithAesGcmCombined(
      JSON.stringify({ probe: "wrong-project", nonce: randomUUID() }),
      fixture.projectKey,
    );
    await expectStatus(
      requesterClient,
      withContext(`/v1/projects/${randomUUID()}/sources/${fixture.sourceId}/requests`),
      404,
      {
        method: "POST",
        body: JSON.stringify({
          request_id: randomUUID(),
          requesting_client_id: "wrong-project-client",
          operation: "list",
          key_epoch: 1,
          encrypted_envelope: wrongProjectEnvelope,
        }),
      },
    );
    recordProbe(probes, "wrong_project_context_denied", "passed");

    let routingIdentity = null;
    if (fixture.teamId) {
      const discoveryRequestId = randomUUID();
      const discoveryClientId = randomUUID();
      const discoveryEnvelope = await encryptWithAesGcmCombined(
        JSON.stringify({ probe: "team-routing-discovery", nonce: randomUUID() }),
        fixture.projectKey,
      );
      const discoveryDelivered = hostWs.waitForMessage("project_remote_access_request", undefined, 10_000);
      const discovery = await expectStatus(
        requesterClient,
        withContext(`/v1/projects/${fixture.projectId}/sources/${fixture.sourceId}/requests`),
        202,
        {
          method: "POST",
          body: JSON.stringify({
            request_id: discoveryRequestId,
            requesting_client_id: discoveryClientId,
            operation: "list",
            key_epoch: 1,
            encrypted_envelope: discoveryEnvelope,
          }),
        },
      );
      const discoveryFrame = await discoveryDelivered;
      routingIdentity = discovery.routing_identity;
      requireValue(routingIdentity?.context_type === "team", "Team response omitted scoped routing identity");
      requireValue(
        JSON.stringify(discoveryFrame.payload?.routing_identity) === JSON.stringify(routingIdentity),
        "REST and WebSocket Team routing identities differ",
      );
      requireValue(!JSON.stringify(routingIdentity).includes(discoveryClientId), "Team routing identity exposed the requester client identifier");
      const discoveryResult = await encryptWithAesGcmCombined(
        JSON.stringify({ probe: "team-routing-discovery-result", nonce: randomUUID() }),
        fixture.projectKey,
      );
      const discoveryAck = hostWs.waitForMessage("project_remote_access_completion_ack", undefined, 10_000);
      await hostWs.sendAsync("project_remote_access_complete", {
        source_session_id: sourceSessionId,
        team_id: fixture.teamId,
        project_id: fixture.projectId,
        source_id: fixture.sourceId,
        request_id: discoveryRequestId,
        key_epoch: 1,
        encrypted_envelope: discoveryResult,
      });
      await discoveryAck;
      await expectStatus(
        hostClient,
        withContext(`/v1/projects/${fixture.projectId}/sources/${fixture.sourceId}/requests/${discoveryRequestId}?requesting_client_id=${discoveryClientId}`),
        404,
      );
      await expectStatus(
        requesterClient,
        withContext(`/v1/projects/${fixture.projectId}/sources/${fixture.sourceId}/requests/${discoveryRequestId}?requesting_client_id=${discoveryClientId}`),
        200,
      );
      await expectStatus(
        requesterClient,
        `/v1/projects/${fixture.projectId}/sources/${fixture.sourceId}/requests`,
        404,
        {
          method: "POST",
          body: JSON.stringify({
            request_id: randomUUID(),
            requesting_client_id: randomUUID(),
            operation: "list",
            key_epoch: 1,
            encrypted_envelope: discoveryEnvelope,
          }),
        },
      );
      recordProbe(probes, "team_request_without_team_context_denied", "passed");
    }

    const requestId = randomUUID();
    const requestingClientId = randomUUID();
    const identity = cryptoIdentity(ownerId, fixture, sourceSessionId, requestingClientId, routingIdentity);
    const requesterHandshake = await createRemoteAccessHandshake(fixture.projectKey, identity, "requester");
    requireValue(requesterHandshake.handshake.version === (fixture.teamId ? 2 : 1), "Unexpected remote-access protocol version");
    const bootstrap = await encryptWithAesGcmCombined(JSON.stringify({
      requesting_client_id: requestingClientId,
      requester_handshake: requesterHandshake.handshake,
      operation: "list",
      arguments: { path: "." },
    }), fixture.projectKey);
    const deliveredMessage = hostWs.waitForMessage("project_remote_access_request", undefined, 10_000);
    const created = await expectStatus(
      requesterClient,
      withContext(`/v1/projects/${fixture.projectId}/sources/${fixture.sourceId}/requests`),
      202,
      {
        method: "POST",
        body: JSON.stringify({
          request_id: requestId,
          requesting_client_id: requestingClientId,
          operation: "list",
          key_epoch: 1,
          encrypted_envelope: bootstrap,
        }),
      },
    );
    requireValue(created.request_id === requestId && created.status === "delivered", "Request was not delivered immediately");
    const delivered = await deliveredMessage;
    requireValue(delivered.payload?.encrypted_envelope === bootstrap, "WebSocket delivery changed encrypted bootstrap ciphertext");
    if (fixture.teamId) {
      requireValue(JSON.stringify(created.routing_identity) === JSON.stringify(routingIdentity), "Team routing identity changed between requests");
    }
    const openedBootstrap = JSON.parse(await decryptWithAesGcmCombined(delivered.payload.encrypted_envelope, fixture.projectKey));
    requireValue(openedBootstrap.requesting_client_id === requestingClientId, "Source could not authenticate requester bootstrap context");
    const sourceHandshake = await createRemoteAccessHandshake(fixture.projectKey, identity, "source");
    const sourceKey = await deriveRemoteAccessSessionKey(
      fixture.projectKey,
      identity,
      "source",
      sourceHandshake.privateKey,
      sourceHandshake.handshake,
      openedBootstrap.requester_handshake,
    );
    const requesterKey = await deriveRemoteAccessSessionKey(
      fixture.projectKey,
      identity,
      "requester",
      requesterHandshake.privateKey,
      requesterHandshake.handshake,
      sourceHandshake.handshake,
    );
    requireValue(Buffer.from(sourceKey).equals(Buffer.from(requesterKey)), "Requester/source transcript keys differ");
    const resultEnvelope = await sealRemoteAccessEnvelope(
      sourceKey,
      identity,
      requestId,
      "result",
      new TextEncoder().encode(JSON.stringify({ ok: true, result: { entries: [] } })),
    );
    const encryptedResult = JSON.stringify({ source_handshake: sourceHandshake.handshake, envelope: resultEnvelope });
    const completionAck = hostWs.waitForMessage("project_remote_access_completion_ack", undefined, 10_000);
    await hostWs.sendAsync("project_remote_access_complete", {
      source_session_id: sourceSessionId,
      ...(fixture.teamId ? { team_id: fixture.teamId } : {}),
      project_id: fixture.projectId,
      source_id: fixture.sourceId,
      request_id: requestId,
      key_epoch: 1,
      encrypted_envelope: encryptedResult,
    });
    await completionAck;

    await expectStatus(
      hostClient,
      withContext(`/v1/projects/${fixture.projectId}/sources/${fixture.sourceId}/requests/${requestId}?requesting_client_id=${requestingClientId}`),
      404,
    );
    recordProbe(probes, "cross_session_polling_denied", "passed");
    await expectStatus(
      requesterClient,
      withContext(`/v1/projects/${fixture.projectId}/sources/${fixture.sourceId}/requests/${requestId}?requesting_client_id=wrong-client`),
      404,
    );
    const result = await expectStatus(
      requesterClient,
      withContext(`/v1/projects/${fixture.projectId}/sources/${fixture.sourceId}/requests/${requestId}?requesting_client_id=${requestingClientId}`),
      200,
    );
    requireValue(result.encrypted_envelope === encryptedResult, "Result retrieval changed encrypted result ciphertext");
    const parsedResult = JSON.parse(result.encrypted_envelope);
    const wrongIdentity = fixture.teamId
      ? { ...identity, contextId: `${identity.contextId}-wrong` }
      : { ...identity, projectId: randomUUID() };
    try {
      await openRemoteAccessEnvelope(
        requesterKey, wrongIdentity, requestId, "result", parsedResult.envelope, new RemoteAccessReplayGuard(),
      );
      throw new Error("Wrong-context envelope replay was accepted");
    } catch (error) {
      requireValue(/authentication failed/.test(String(error)), `Unexpected wrong-context error: ${error}`);
    }
    recordProbe(probes, "wrong_context_crypto_replay_denied", "passed");
    const plaintext = await openRemoteAccessEnvelope(
      requesterKey, identity, requestId, "result", parsedResult.envelope, new RemoteAccessReplayGuard(),
    );
    requireValue(JSON.parse(new TextDecoder().decode(plaintext)).ok === true, "Requester could not decrypt crypto-backed result");
    recordProbe(probes, fixture.teamId ? "team_v2_transcript_envelope" : "personal_v1_compatibility", "passed");

    const replayError = hostWs.waitForMessage("project_remote_access_completion_ack", undefined, 10_000);
    await hostWs.sendAsync("project_remote_access_complete", {
      source_session_id: sourceSessionId,
      ...(fixture.teamId ? { team_id: fixture.teamId } : {}),
      project_id: fixture.projectId,
      source_id: fixture.sourceId,
      request_id: requestId,
      key_epoch: 1,
      encrypted_envelope: encryptedResult,
    });
    await expectWsError(replayError, "request_already_completed");
    recordProbe(probes, "completion_replay_denied", "passed");

    const pendingRequestId = randomUUID();
    const pendingClientId = randomUUID();
    const pendingIdentity = cryptoIdentity(ownerId, fixture, sourceSessionId, pendingClientId, routingIdentity);
    const pendingHandshake = await createRemoteAccessHandshake(fixture.projectKey, pendingIdentity, "requester");
    const pendingBootstrap = await encryptWithAesGcmCombined(JSON.stringify({
      requesting_client_id: pendingClientId,
      requester_handshake: pendingHandshake.handshake,
      operation: "list",
      arguments: { path: "." },
    }), fixture.projectKey);
    const pendingDelivered = hostWs.waitForMessage("project_remote_access_request", undefined, 10_000);
    await expectStatus(
      requesterClient,
      withContext(`/v1/projects/${fixture.projectId}/sources/${fixture.sourceId}/requests`),
      202,
      {
        method: "POST",
        body: JSON.stringify({
          request_id: pendingRequestId,
          requesting_client_id: pendingClientId,
          operation: "list",
          key_epoch: 1,
          encrypted_envelope: pendingBootstrap,
        }),
      },
    );
    await pendingDelivered;

    await takeoverWs.open();
    const replacementSessionId = randomUUID();
    const conflict = takeoverWs.waitForMessage("project_remote_access_registered", undefined, 10_000);
    await takeoverWs.sendAsync("project_remote_access_register", {
      source_session_id: replacementSessionId,
      ...(fixture.teamId ? { team_id: fixture.teamId } : {}),
      confirmed_takeover: false,
      bindings: [{
        project_id: fixture.projectId,
        source_id: fixture.sourceId,
        capabilities: ["read", "search", "import"],
        key_epoch: 1,
      }],
    });
    await expectWsError(conflict, "takeover_confirmation_required");
    const replaced = takeoverWs.waitForMessage("project_remote_access_registered", undefined, 10_000);
    await takeoverWs.sendAsync("project_remote_access_register", {
      source_session_id: replacementSessionId,
      ...(fixture.teamId ? { team_id: fixture.teamId } : {}),
      confirmed_takeover: true,
      bindings: [{
        project_id: fixture.projectId,
        source_id: fixture.sourceId,
        capabilities: ["read", "search", "import"],
        key_epoch: 1,
      }],
    });
    const replacedPayload = await replaced;
    requireValue(replacedPayload.payload?.replaced_session_id === sourceSessionId, "Confirmed takeover did not replace the old source session");
    recordProbe(probes, "confirmed_takeover_replaces_session", "passed");

    const staleHeartbeat = hostWs.waitForMessage("project_remote_access_heartbeat_ack", undefined, 10_000);
    await hostWs.sendAsync("project_remote_access_heartbeat", {
      source_session_id: sourceSessionId,
      ...(fixture.teamId ? { team_id: fixture.teamId } : {}),
    });
    await expectWsError(staleHeartbeat, "source_offline");
    const staleCompletion = hostWs.waitForMessage("project_remote_access_completion_ack", undefined, 10_000);
    await hostWs.sendAsync("project_remote_access_complete", {
      source_session_id: sourceSessionId,
      ...(fixture.teamId ? { team_id: fixture.teamId } : {}),
      project_id: fixture.projectId,
      source_id: fixture.sourceId,
      request_id: pendingRequestId,
      key_epoch: 1,
      encrypted_envelope: await encryptWithAesGcmCombined(
        JSON.stringify({ probe: "stale-completion", nonce: randomUUID() }), fixture.projectKey,
      ),
    });
    await expectWsError(staleCompletion, "request_already_completed");
    recordProbe(probes, "stale_session_lifecycle_denied", "passed");

    const disconnectedMessage = takeoverWs.waitForMessage("project_remote_access_disconnected", undefined, 10_000);
    await takeoverWs.sendAsync("project_remote_access_disconnect", {
      source_session_id: replacementSessionId,
      ...(fixture.teamId ? { team_id: fixture.teamId } : {}),
    });
    await disconnectedMessage;
    recordProbe(
      probes,
      "cross_account_denial",
      "not_run",
      "requires a separately approved second test account; backend unit coverage is retained",
    );
    recordProbe(
      probes,
      "removed_member_denial",
      "not_run",
      "requires a separately approved second test account; backend unit coverage is retained",
    );
    return probes;
  } finally {
    hostWs.close();
    takeoverWs.close();
  }
}

async function requestCliOperation(client, fixture, ownerId, source, operation, args) {
  const requestId = randomUUID();
  const requestingClientId = randomUUID();
  const identity = {
    ownerId,
    projectId: fixture.projectId,
    sourceId: fixture.sourceId,
    sourceSessionId: source.source_session_id,
    requestingClientId,
    keyEpoch: source.key_epoch,
  };
  const requester = await createRemoteAccessHandshake(fixture.projectKey, identity, "requester");
  const bootstrap = await encryptWithAesGcmCombined(JSON.stringify({
    requesting_client_id: requestingClientId,
    requester_handshake: requester.handshake,
    operation,
    arguments: args,
  }), fixture.projectKey);
  await expectStatus(
    client,
    `/v1/projects/${fixture.projectId}/sources/${fixture.sourceId}/requests`,
    202,
    {
      method: "POST",
      body: JSON.stringify({
        request_id: requestId,
        requesting_client_id: requestingClientId,
        operation,
        key_epoch: source.key_epoch,
        encrypted_envelope: bootstrap,
      }),
    },
  );

  const deadline = Date.now() + 45_000;
  let result;
  while (Date.now() < deadline) {
    const response = await apiRequest(
      client,
      `/v1/projects/${fixture.projectId}/sources/${fixture.sourceId}/requests/${requestId}?requesting_client_id=${requestingClientId}`,
    );
    if (response.status === 200) {
      result = response.data;
      break;
    }
    requireValue(response.status === 404, `Result poll failed with HTTP ${response.status}`);
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 250));
  }
  requireValue(result, `Encrypted ${operation} result timed out`);
  const payload = JSON.parse(result.encrypted_envelope);
  const sessionKey = await deriveRemoteAccessSessionKey(
    fixture.projectKey,
    identity,
    "requester",
    requester.privateKey,
    requester.handshake,
    payload.source_handshake,
  );
  const plaintext = await openRemoteAccessEnvelope(
    sessionKey,
    identity,
    requestId,
    "result",
    payload.envelope,
    new RemoteAccessReplayGuard(),
  );
  return JSON.parse(new TextDecoder().decode(plaintext));
}

function waitForCliConnected(child) {
  return new Promise((resolvePromise, reject) => {
    let output = "";
    const timeout = setTimeout(
      () => reject(new Error(`Foreground CLI did not connect before the deadline: ${output}`)),
      30_000,
    );
    child.stdout.setEncoding("utf-8");
    child.stdout.on("data", (chunk) => {
      output += chunk;
      if (/"state"\s*:\s*"connected"/.test(output)) {
        clearTimeout(timeout);
        resolvePromise();
      }
    });
    child.stderr.setEncoding("utf-8");
    child.stderr.on("data", (chunk) => {
      output += chunk;
    });
    child.once("exit", (code) => {
      clearTimeout(timeout);
      reject(new Error(`Foreground CLI exited before connecting (${code}): ${output}`));
    });
  });
}

async function runCliVerification(client, fixture, ownerId) {
  const rootPath = join(tmpdir(), `openmates-remote-access-live-${randomUUID()}`);
  const sourceStorePath = join(homedir(), ".openmates", "remote-sources.json");
  const originalSourceStore = existsSync(sourceStorePath) ? readFileSync(sourceStorePath) : null;
  mkdirSync(join(rootPath, "src"), { recursive: true });
  writeFileSync(join(rootPath, "src", "sample.txt"), "remote access live needle\nsecond line\n");
  writeFileSync(join(rootPath, ".env"), "REMOTE_ACCESS_SECRET=not-for-server\n");
  startRemoteAccessSource({
    sourceId: fixture.sourceId,
    projectId: fixture.projectId,
    rootPath,
    sourceType: "local_folder",
    displayName: "Live verification source",
  });

  const child = spawn("node", ["dist/cli.js", "remote-access", "--path", rootPath, "--json"], {
    cwd: CLI_DIR,
    env: { ...process.env, OPENMATES_API_URL: apiUrl },
    stdio: ["ignore", "pipe", "pipe"],
  });
  try {
    await waitForCliConnected(child);
    const source = await waitForConnectedSource(client, fixture);
    const listed = await requestCliOperation(client, fixture, ownerId, source, "list", { path: "." });
    requireValue(listed.ok === true, `List failed: ${JSON.stringify(listed)}`);
    requireValue(listed.result.entries.some((entry) => entry.path === "src"), "List result omitted the safe src directory");
    requireValue(!listed.result.entries.some((entry) => entry.path === ".env"), "List result exposed a protected file");

    const searched = await requestCliOperation(client, fixture, ownerId, source, "search", { query: "needle" });
    requireValue(searched.ok === true, `Search failed: ${JSON.stringify(searched)}`);
    requireValue(
      searched.result.matches.some((match) => match.path.replace(/^\.\//, "") === "src/sample.txt"),
      `Search did not return the expected safe match: ${JSON.stringify(searched.result)}`,
    );

    const read = await requestCliOperation(client, fixture, ownerId, source, "read_text", { path: "src/sample.txt" });
    requireValue(read.ok === true, `Read failed: ${JSON.stringify(read)}`);
    requireValue(read.result.content.includes("remote access live needle"), "Read did not return expected cleartext to the requester");

    const protectedRead = await requestCliOperation(client, fixture, ownerId, source, "read_text", { path: ".env" });
    requireValue(protectedRead.ok === false && protectedRead.error === "protected_path", "Protected read did not fail with a sanitized encrypted error");
  } finally {
    if (child.exitCode === null) {
      child.kill("SIGINT");
      await new Promise((resolvePromise) => child.once("exit", resolvePromise));
    }
    if (originalSourceStore) writeFileSync(sourceStorePath, originalSourceStore);
    else rmSync(sourceStorePath, { force: true });
    rmSync(rootPath, { recursive: true, force: true });
  }

  const deadline = Date.now() + 10_000;
  while (Date.now() < deadline) {
    const sources = await client.listProjectSources(fixture.projectId);
    const source = sources.find((candidate) => candidate.source_id === fixture.sourceId);
    if (source?.status === "offline") return;
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 250));
  }
  throw new Error("Source did not report offline after foreground CLI shutdown");
}

async function stopForegroundCli(child) {
  if (child.exitCode !== null) return;
  child.kill("SIGINT");
  await new Promise((resolvePromise) => child.once("exit", resolvePromise));
}

async function runServeFixture(client, fixture) {
  const rootPath = join(tmpdir(), `openmates-remote-access-serve-${randomUUID()}`);
  const sourceStorePath = join(homedir(), ".openmates", "remote-sources.json");
  const originalSourceStore = existsSync(sourceStorePath) ? readFileSync(sourceStorePath) : null;
  mkdirSync(join(rootPath, "src"), { recursive: true });
  writeFileSync(join(rootPath, "src", "remote-demo.ts"), 'export const remoteDemo = "OpenMates live remote preview";\nexport const imported = true;\n');
  writeFileSync(join(rootPath, ".env"), "REMOTE_ACCESS_SECRET=not-for-server\n");
  startRemoteAccessSource({
    sourceId: fixture.sourceId,
    projectId: fixture.projectId,
    rootPath,
    sourceType: "local_folder",
    displayName: "Live remote source",
  });
  const child = spawn("node", ["dist/cli.js", "remote-access", "--path", rootPath, "--json"], {
    cwd: CLI_DIR,
    env: { ...process.env, OPENMATES_API_URL: apiUrl },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let bridgeStopped = false;
  try {
    await waitForCliConnected(child);
    await waitForConnectedSource(client, fixture);
    process.stdout.write(`${JSON.stringify({
      event: "fixture_ready",
      project_id: fixture.projectId,
      source_id: fixture.sourceId,
    })}\n`);
    await new Promise((resolvePromise) => {
      process.once("SIGUSR1", () => {
        void stopForegroundCli(child).then(() => {
          bridgeStopped = true;
          process.stdout.write(`${JSON.stringify({ event: "bridge_stopped" })}\n`);
        });
      });
      process.once("SIGINT", resolvePromise);
      process.once("SIGTERM", resolvePromise);
    });
  } finally {
    if (!bridgeStopped) await stopForegroundCli(child);
    if (originalSourceStore) writeFileSync(sourceStorePath, originalSourceStore);
    else rmSync(sourceStorePath, { force: true });
    rmSync(rootPath, { recursive: true, force: true });
  }
}

const isolatedApiMode = mode === "api" || mode === "api-team";
const client = isolatedApiMode ? loadIsolatedClient("OPENMATES_REMOTE_HOST_SESSION") : OpenMatesClient.load({ apiUrl });
const requesterClient = isolatedApiMode ? loadIsolatedClient("OPENMATES_REMOTE_REQUESTER_SESSION") : client;
requireValue(client.hasSession() && requesterClient.hasSession(), "Run the test-account login helper before live verification");
requireValue(
  !isolatedApiMode || sessionState(client).sessionId !== sessionState(requesterClient).sessionId,
  "Host and requester must use independently authenticated sessions",
);
const ownerId = await refreshOwnerId(client);
const requesterOwnerId = isolatedApiMode ? await refreshOwnerId(requesterClient) : ownerId;
requireValue(ownerId === requesterOwnerId, "One-account verifier sessions resolved to different account owners");
let fixture;
let teamId;
let teamKey;
let probes = [];
try {
  if (mode === "api-team") {
    teamId = randomUUID();
    teamKey = randomBytes(32);
    await expectStatus(client, "/v1/teams", 200, {
      method: "POST",
      body: JSON.stringify({
        team_id: teamId,
        encrypted_name: await encryptWithAesGcmCombined("Remote access live verification", teamKey),
        encrypted_team_key: await encryptBytesWithAesGcm(teamKey, client.getMasterKeyBytes()),
        created_at: Math.floor(Date.now() / 1000),
      }),
    });
  }
  fixture = await createFixture(client, teamId ?? null, teamKey ?? null);
  const record = (await client.listProjects({ includeArchived: true, teamId: teamId ?? null, personal: !teamId }))
    .find((item) => item.project_id === fixture.projectId);
  requireValue(record, "Created Project was not readable through the authenticated API");
  if (!teamId) {
    const decryptedKey = await decryptBytesWithAesGcm(record.encrypted_project_key, client.getMasterKeyBytes());
    requireValue(decryptedKey && Buffer.from(decryptedKey).equals(Buffer.from(fixture.projectKey)), "Created Project key did not round-trip");
  }
  if (mode === "api" || mode === "api-team") probes = await runApiVerification(client, requesterClient, fixture, ownerId);
  else if (mode === "cli") await runCliVerification(client, fixture, ownerId);
  else await runServeFixture(client, fixture);
  process.stdout.write(`${JSON.stringify({ success: true, mode, api_url: apiUrl, probes })}\n`);
} finally {
  await deleteFixture(client, fixture);
  if (teamId) {
    const response = await apiRequest(client, `/v1/teams/${teamId}`, { method: "DELETE" });
    requireValue([200, 404].includes(response.status), `Team cleanup failed with HTTP ${response.status}`);
  }
}
